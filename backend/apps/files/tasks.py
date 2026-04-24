"""Celery tasks for file lifecycle management.

All tasks are idempotent — safe to retry or run multiple times without
corrupting state.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.storage import service as storage_service
from apps.storage.client import get_client
from apps.storage.exceptions import StorageError
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(StorageError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def delete_storage_object(self, storage_key: str, file_id: str) -> None:
    """Backstop purge: remove every B2 version of `storage_key` and the row.

    Primary delete/overwrite paths in `services.py` now call
    `delete_all_versions` inline. This task exists purely as a safety net
    for rows that got stuck in DELETING — e.g. the API process crashed
    between the status flip and the sync purge, or the sync purge hit a
    transient B2 failure. `reap_deleting` schedules us for those rows.

    Idempotent end-to-end: listing + versioned deletion is safe to retry,
    and a missing row is logged and ignored.
    """
    from .models import AuditLog, File

    purged = storage_service.delete_all_versions(storage_key)

    with transaction.atomic():
        try:
            row = File.objects.select_for_update().get(pk=file_id)
        except File.DoesNotExist:
            logger.info("delete_storage_object: row already gone id=%s", file_id)
            return
        owner = row.owner
        name = row.name
        row.delete()
        AuditLog.objects.create(
            user=owner,
            action=AuditLog.Action.DELETE,
            file_id=file_id,
            file_name=name,
            metadata={"storage_key": storage_key, "versions_purged": purged},
        )


@shared_task(
    bind=True,
    autoretry_for=(StorageError,),
    retry_backoff=True,
    max_retries=3,
)
def verify_checksum(self, file_id: str) -> None:
    """Stream the stored object, compute SHA-256, persist to the row.

    Non-blocking post-upload step. Failure only means the checksum column
    stays NULL — file is still usable.
    """
    from .models import File

    try:
        row = File.objects.get(pk=file_id, status=File.Status.READY)
    except File.DoesNotExist:
        logger.info("verify_checksum: file not ready or missing id=%s", file_id)
        return

    client = get_client()
    hasher = hashlib.sha256()
    try:
        response = client.get_object(Bucket=settings.B2_BUCKET_NAME, Key=row.storage_key)
        body = response["Body"]
        for chunk in iter(lambda: body.read(1024 * 1024), b""):
            hasher.update(chunk)
    except Exception as exc:
        raise StorageError(f"checksum read failed: {exc}") from exc

    File.objects.filter(pk=file_id).update(
        checksum_sha256=hasher.hexdigest(), updated_at=timezone.now()
    )


@shared_task
def cleanup_failed_uploads(max_age_minutes: int = 60) -> int:
    """Reap rows stuck in UPLOADING or FAILED longer than `max_age_minutes`.

    For UPLOADING rows we also attempt a best-effort B2 delete in case the
    object landed after the row was flagged. Returns count reaped.
    """
    from .models import File

    cutoff = timezone.now() - timedelta(minutes=max_age_minutes)
    stale = File.objects.filter(
        status__in=(File.Status.UPLOADING, File.Status.FAILED),
        updated_at__lt=cutoff,
    )

    count = 0
    for row in stale:
        # Use version-aware purge: stuck UPLOADING rows may have partial
        # multipart writes or a completed PUT that never got swapped to
        # READY — either way we want the key gone, not just marker-hidden.
        try:
            storage_service.delete_all_versions(row.storage_key)
        except StorageError:
            logger.warning(
                "cleanup_failed_uploads: storage purge failed key=%s",
                row.storage_key,
            )
        row.delete()
        count += 1
    if count:
        logger.info("cleanup_failed_uploads: reaped %d stale row(s)", count)
    return count


@shared_task
def reap_deleting(max_age_minutes: int = 30) -> int:
    """Retry rows stuck in DELETING (worker died or B2 flapped).

    Safe to run repeatedly — delete_storage_object is idempotent.
    """
    from .models import File

    cutoff = timezone.now() - timedelta(minutes=max_age_minutes)
    stuck = File.objects.filter(status=File.Status.DELETING, updated_at__lt=cutoff)
    count = 0
    for row in stuck:
        delete_storage_object.delay(row.storage_key, str(row.id))
        count += 1
    return count
