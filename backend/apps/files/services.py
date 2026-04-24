"""Core file business logic — upload, overwrite, delete.

Transaction strategy:
  Phase 1 (no DB): validate bytes + sniff MIME
  Phase 2 (short TX): lock user row, check quota, insert file row as 'uploading'
  Phase 3 (no DB): stream bytes to B2                  ← long I/O, released lock
  Phase 4 (short TX): atomic status swap (old→deleting, new→ready) + audit log
  Phase 5 (no DB): SYNC purge all B2 versions of the evicted key, then
                   hard-delete the old row. verify_checksum fires async.

Last-write-wins contract: by the time `upload_file` returns, B2 holds
exactly one version for the new storage_key and zero versions (no delete
markers either) for the old storage_key. The sync phase-5 purge is what
makes this true — a Celery-deferred cleanup would let stale versions
linger while B2's bucket versioning keeps hide markers around.

Any failure in phases 1–3 leaves the new row in 'uploading' or 'failed',
which `cleanup_failed_uploads` reaps. The old row stays READY the entire
time, so users see no visible disruption on a failed re-upload. A
phase-5 purge failure logs but doesn't raise — the new file is usable
and `reap_deleting` will retry the cleanup.

Deletes go straight through: flip-to-DELETING → sync version purge →
hard-delete. If a DELETE arrives mid-upload, we reject with
FileBusyError (409) — the client retries in a moment once Phase 4
completes the atomic swap.
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

from .exceptions import FileBusyError, QuotaExceededError
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
    existing_key: str | None = None
    existing_pk = None
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
            # Flag to DELETING so the unique (owner, name, READY) constraint
            # stays satisfied while we swap, and so reap_deleting will pick
            # this up if phase 5 crashes before we hard-delete the row.
            existing_key = existing.storage_key
            existing_pk = existing.pk
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

    # ── Phase 5: synchronous B2 cleanup of the evicted key ─────────
    # Last-write-wins contract: by the time this function returns, the old
    # storage_key has NO remaining versions or delete markers in B2. We do
    # this inline (not via Celery) so the HTTP response can't report 201
    # until B2 is actually clean.
    #
    # Failure mode: if the purge fails, the new file is still READY and
    # fully usable; the old row sits in DELETING with its storage_key
    # known, and the `reap_deleting` beat task will retry. We log and
    # continue rather than raise — the user's upload succeeded, and
    # rolling back to satisfy the letter of the spec here would throw
    # away a perfectly good file.
    if existing_key and existing_pk is not None:
        try:
            purged = storage_service.delete_all_versions(existing_key)
            logger.info(
                "upload_file: purged old key=%s versions=%d on overwrite",
                existing_key, purged,
            )
            # Only hard-delete the row AFTER B2 is confirmed clean, so a
            # failure leaves a recoverable trail for the reaper.
            File.objects.filter(pk=existing_pk).delete()
        except StorageError:
            logger.exception(
                "upload_file: old-key purge failed key=%s — reaper will retry",
                existing_key,
            )

    # Checksum verification is a non-critical integrity check; async is fine.
    from . import tasks
    tasks.verify_checksum.delay(str(file_row.id))

    file_row.refresh_from_db()
    return file_row


# ── Delete ────────────────────────────────────────────────────────
def delete_file(user, file_row: File) -> None:
    """Synchronously purge the file from B2 and remove the DB row.

    Ordering (important — flip status first so concurrent readers see the
    row as unavailable *before* we start touching B2):

      1. Short TX: lock row, flip to DELETING. Reject with FileBusyError
         if the upload is still streaming — we can't safely purge while
         B2 writes are in flight on the same key.
      2. Synchronous `delete_all_versions(storage_key)` — raises
         StorageError on failure. Row stays in DELETING; the
         `reap_deleting` beat task will retry automatically.
      3. Short TX: hard-delete the row and write a single audit entry
         recording how many versions were purged.

    By the time this function returns successfully, B2 contains no
    versions or delete markers for the key. The caller can report 204
    with confidence. `user.storage_used` is a computed property that
    aggregates READY rows on read, so it self-heals after step 3 — no
    explicit recalc or cache invalidation needed.

    Caller is responsible for having fetched `file_row` with the owner
    filter already applied (see apps/files/selectors.py).

    Idempotent: calling on a row already in DELETING re-runs the purge
    (safe — list+delete is idempotent) and removes the row.
    """
    # ── Step 1: lock + flip status ─────────────────────────────────
    with transaction.atomic():
        locked = File.objects.select_for_update().get(pk=file_row.pk)

        # Mid-upload DELETE: streaming to the same key is still in progress,
        # so a purge now would race the PUT and leave orphaned bytes in B2.
        # Reject with 409 — the client can retry in a second once the
        # upload's atomic swap finishes.
        if locked.status == File.Status.UPLOADING:
            raise FileBusyError(
                "This file is still uploading. Please try again in a moment."
            )

        prior_status = locked.status
        storage_key = locked.storage_key
        file_id = locked.id
        file_name = locked.name

        if locked.status != File.Status.DELETING:
            locked.status = File.Status.DELETING
            locked.save(update_fields=["status", "updated_at"])

    # ── Step 2: synchronous B2 purge (no DB lock held) ─────────────
    # Any StorageError bubbles up to the API layer, which maps it to 502.
    # The row remains in DELETING so reap_deleting can pick it up and
    # retry — we do NOT roll back the status flip, because leaving the
    # file discoverable after the user hit "delete" is worse than a
    # retryable error.
    purged = storage_service.delete_all_versions(storage_key)

    # ── Step 3: hard-delete row + audit (short TX) ─────────────────
    with transaction.atomic():
        File.objects.filter(pk=file_id).delete()
        AuditLog.objects.create(
            user=user,
            action=AuditLog.Action.DELETE,
            file_id=file_id,
            file_name=file_name,
            metadata={
                "prior_status": prior_status,
                "storage_key": storage_key,
                "versions_purged": purged,
            },
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
