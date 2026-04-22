"""Core file business logic — upload, quota accounting, overwrite.

Transaction strategy:
  Phase 1 (no DB): validate bytes + sniff MIME
  Phase 2 (short TX): lock user row, check quota, insert file row as 'uploading'
  Phase 3 (no DB): stream bytes to B2                  ← long I/O, released lock
  Phase 4 (short TX): atomic status swap (old→deleting, new→ready) + audit log
  Phase 5 (no DB): fire Celery tasks (cleanup old key, verify checksum)

Any failure in phases 1–3 leaves the new row in 'uploading' or 'failed', which
the beat-scheduled cleanup task reaps. The old (pre-overwrite) row stays READY
the entire time, so users see no visible disruption on a failed re-upload.
"""
from __future__ import annotations

import io
import logging
from datetime import timedelta
from typing import Literal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from ninja.files import UploadedFile

from apps.storage import service as storage_service
from apps.storage.exceptions import StorageError
from apps.storage.keys import generate_storage_key

from .exceptions import QuotaExceededError
from .models import AuditLog, File
from .validators import (
    canonical_mime_for,
    read_head,
    sanitize_svg,
    sniff_mime,
    validate_extension,
    validate_mime_matches_extension,
    validate_size,
)

User = get_user_model()
logger = logging.getLogger(__name__)


def _compute_storage_used(user) -> int:
    total = (
        File.objects.filter(owner=user, status=File.Status.READY)
        .aggregate(total=Sum("size"))
        .get("total")
    )
    return total or 0


def _ensure_quota(user, *, incoming_size: int, same_name: str) -> None:
    """Quota check that credits the size of any existing file with the same name
    (because that file will be evicted if the upload completes)."""
    used = _compute_storage_used(user)
    reclaimable = (
        File.objects.filter(
            owner=user, name=same_name, status=File.Status.READY
        )
        .aggregate(total=Sum("size"))
        .get("total")
    ) or 0

    projected = used - reclaimable + incoming_size
    if projected > user.storage_quota:
        raise QuotaExceededError(
            used=used, quota=user.storage_quota, incoming=incoming_size
        )


def upload_file(user, upload: UploadedFile) -> File:
    # ── Phase 1: validate ──────────────────────────────────────────
    validate_size(upload.size)
    ext = validate_extension(upload.name)

    head = read_head(upload)
    sniffed = sniff_mime(head)
    validate_mime_matches_extension(ext, sniffed)

    # SVG: sanitize in memory before we allocate a storage key or a DB row.
    if ext == "svg":
        upload.seek(0)
        raw = upload.read()
        upload.seek(0)
        cleaned = sanitize_svg(raw)
        # Wrap cleaned bytes into a seekable BinaryIO the uploader can consume.
        source_stream: io.BufferedIOBase = io.BytesIO(cleaned)
        stored_size = len(cleaned)
    else:
        source_stream = upload.file
        source_stream.seek(0)
        stored_size = upload.size

    canonical_mime = canonical_mime_for(ext)
    display_name = upload.name

    # ── Phase 2: reserve row under quota lock (short TX) ───────────
    storage_key = generate_storage_key(user.id, ext)

    with transaction.atomic():
        # Lock the user row so two concurrent uploads can't both slip under quota.
        User.objects.select_for_update().filter(pk=user.pk).exists()
        _ensure_quota(user, incoming_size=stored_size, same_name=display_name)

        file_row = File.objects.create(
            owner=user,
            name=display_name,
            storage_key=storage_key,
            size=stored_size,
            mime_type=canonical_mime,
            extension=ext,
            status=File.Status.UPLOADING,
        )

    # ── Phase 3: upload to object store (no DB TX held) ────────────
    try:
        storage_service.upload_stream(storage_key, source_stream, canonical_mime)
    except StorageError:
        File.objects.filter(pk=file_row.pk).update(
            status=File.Status.FAILED, updated_at=timezone.now()
        )
        raise

    # ── Phase 4: atomic swap (short TX) ────────────────────────────
    with transaction.atomic():
        # Re-fetch our row under lock. If the user DELETEd it while phase 3
        # was streaming, it's now in DELETING — let the delete task clean up.
        locked_new = File.objects.select_for_update().get(pk=file_row.pk)
        if locked_new.status != File.Status.UPLOADING:
            logger.info(
                "upload_file: row %s changed status to %s during upload; skipping swap",
                file_row.pk, locked_new.status,
            )
            file_row.refresh_from_db()
            return file_row

        existing_qs = (
            File.objects.select_for_update()
            .filter(owner=user, name=display_name, status=File.Status.READY)
            .exclude(pk=file_row.pk)
        )
        existing = existing_qs.first()
        if existing:
            existing.status = File.Status.DELETING
            existing.save(update_fields=["status", "updated_at"])

        locked_new.status = File.Status.READY
        locked_new.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            user=user,
            action=(AuditLog.Action.OVERWRITE if existing else AuditLog.Action.UPLOAD),
            file_id=locked_new.id,
            file_name=display_name,
            metadata={"size": stored_size, "mime": canonical_mime},
        )

    # ── Phase 5: async cleanup & integrity ─────────────────────────
    # Deferred import to avoid module-level Celery init at settings-load time.
    from . import tasks

    if existing:
        tasks.delete_storage_object.delay(existing.storage_key, str(existing.id))
    tasks.verify_checksum.delay(str(file_row.id))

    file_row.refresh_from_db()
    return file_row


# ── Delete ────────────────────────────────────────────────────────
def delete_file(user, file_row: File) -> None:
    """Soft-flag the row to DELETING and enqueue a Celery task to finish the job.

    Caller is responsible for having fetched `file_row` with the owner filter
    already applied (see apps/files/selectors.py).

    Idempotent: calling on a row already in DELETING is a no-op.
    """
    # Deferred import — avoids circular (tasks imports services indirectly).
    from . import tasks

    if file_row.status == File.Status.DELETING:
        return

    with transaction.atomic():
        locked = File.objects.select_for_update().get(pk=file_row.pk)
        if locked.status == File.Status.DELETING:
            return
        prior_status = locked.status
        locked.status = File.Status.DELETING
        locked.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            user=user,
            action=AuditLog.Action.DELETE,
            file_id=locked.id,
            file_name=locked.name,
            metadata={"prior_status": prior_status, "storage_key": locked.storage_key},
        )

        # Delay the B2 delete if upload was still in flight — gives the PUT time
        # to either land (so we can remove the object) or fail cleanly. Without
        # this, the delete call might arrive before the upload, orphaning bytes.
        storage_key = locked.storage_key
        pk_str = str(locked.id)
        countdown = 30 if prior_status == File.Status.UPLOADING else 0

        # Dispatch AFTER commit so the worker doesn't race the transaction.
        transaction.on_commit(
            lambda: tasks.delete_storage_object.apply_async(
                args=[storage_key, pk_str], countdown=countdown
            )
        )


# ── Signed URL issuance ───────────────────────────────────────────
def issue_signed_url(
    user,
    file_row: File,
    *,
    mode: Literal["preview", "download"],
) -> dict:
    """Return {url, expires_at, mode}. Logs the issuance for audit."""
    ttl = settings.SIGNED_URL_TTL_SECONDS
    disposition = "inline" if mode == "preview" else "attachment"

    url = storage_service.presign_get(
        file_row.storage_key,
        ttl_seconds=ttl,
        disposition=disposition,
        filename=file_row.name,
    )

    AuditLog.objects.create(
        user=user,
        action=(
            AuditLog.Action.PREVIEW if mode == "preview" else AuditLog.Action.DOWNLOAD
        ),
        file_id=file_row.id,
        file_name=file_row.name,
        metadata={"ttl": ttl},
    )

    return {
        "url": url,
        "expires_at": timezone.now() + timedelta(seconds=ttl),
        "mode": mode,
    }
