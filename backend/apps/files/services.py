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
import re
import tempfile
import zipfile
from datetime import timedelta
from typing import Literal, Optional
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from ninja.files import UploadedFile

from apps.storage import service as storage_service
from apps.storage.exceptions import StorageError
from apps.storage.keys import generate_storage_key, generate_storage_key_with_path

from . import selectors
from .exceptions import (
    FileBusyError,
    FolderConflictError,
    FolderNotFoundError,
    FolderTooLargeError,
    QuotaExceededError,
)
from .models import AuditLog, File, Folder
from .validators import (
    canonical_mime_for,
    read_head,
    sanitize_svg,
    sniff_mime,
    validate_extension,
    validate_folder_name,
    validate_mime_matches_extension,
    validate_relative_folder_path,
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


def _ensure_quota(
    user,
    *,
    incoming_size: int,
    same_name: str,
    folder: Optional[Folder] = None,
) -> None:
    """Quota check that credits the size of any existing file with the same name
    *in the same folder scope* (because that file will be evicted if the
    upload completes)."""
    used = _compute_storage_used(user)
    reclaim_qs = File.objects.filter(
        owner=user, name=same_name, status=File.Status.READY
    )
    # Scope reclaim to the same folder — a same-named file in a different
    # folder is NOT evicted, so we must not credit its size here.
    if folder is None:
        reclaim_qs = reclaim_qs.filter(folder__isnull=True)
    else:
        reclaim_qs = reclaim_qs.filter(folder=folder)

    reclaimable = reclaim_qs.aggregate(total=Sum("size")).get("total") or 0

    projected = used - reclaimable + incoming_size
    if projected > user.storage_quota:
        raise QuotaExceededError(
            used=used, quota=user.storage_quota, incoming=incoming_size
        )


def upload_file(
    user,
    upload: UploadedFile,
    *,
    folder: Optional[Folder] = None,
) -> File:
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
    # Key layout mirrors the folder hierarchy so the bucket is
    # human-browsable for ops/debug. The UUID filename still carries
    # the collision-safety we rely on in Phase 5.
    if folder is not None:
        storage_key = generate_storage_key_with_path(user.id, folder.path, ext)
    else:
        storage_key = generate_storage_key(user.id, ext)

    with transaction.atomic():
        # Lock the user row so two concurrent uploads can't both slip under quota.
        User.objects.select_for_update().filter(pk=user.pk).exists()
        _ensure_quota(
            user,
            incoming_size=stored_size,
            same_name=display_name,
            folder=folder,
        )

        file_row = File.objects.create(
            owner=user,
            name=display_name,
            storage_key=storage_key,
            size=stored_size,
            mime_type=canonical_mime,
            extension=ext,
            status=File.Status.UPLOADING,
            folder=folder,
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
        # Same-name overwrite is scoped to the same folder — a "notes.txt"
        # at root is a different file from a "notes.txt" under /work.
        if folder is None:
            existing_qs = existing_qs.filter(folder__isnull=True)
        else:
            existing_qs = existing_qs.filter(folder=folder)
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


# ═══════════════════════════════════════════════════════════════════
# Folder operations
# ═══════════════════════════════════════════════════════════════════

# Hard cap on how many files a single synchronous folder delete or ZIP
# will process. Over this, we return 413 and point the user at
# delete-per-file / per-file download. These operations run inline on a
# web worker so we can't let them drag into tens of minutes.
FOLDER_SUBTREE_FILE_CAP = 100

# TTL on the signed folder-download token. Short — the token goes in a
# URL the user clicks once. Keep it tight to limit replay exposure.
FOLDER_DOWNLOAD_TOKEN_TTL_SECONDS = 5 * 60

_FOLDER_DOWNLOAD_SIGNER_SALT = "files.folder_download"

# Characters that are unsafe as a ZIP filename on Windows/macOS. Replace
# with underscores when composing the download filename — the folder
# NAME itself is already sanitized by validate_folder_name, but we add a
# defensive pass here in case of edge cases (emoji, etc., which are
# allowed as names but can trip certain archivers).
_ZIP_FILENAME_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _compose_child_path(parent: Optional[Folder], name: str) -> str:
    """Build the materialized path for a folder with the given parent and
    name. Root folders (parent=None) get path = name; sub-folders get
    path = parent.path + "/" + name. Matches the convention in Folder's
    model docstring."""
    if parent is None:
        return name
    return f"{parent.path}/{name}"


# Reserve headroom inside Folder.path (1024 chars) so that appending a
# file's storage-key suffix (`/{uuid}.{ext}` ≈ 45 chars) plus the
# `users/<user_id>/` prefix (≈ 20 chars) never overflows
# File.storage_key's 512-char column. Cap the path at a conservative
# 400 chars so even a 36-char UUID + 10-char ext + prefix fits with
# margin.
MAX_FOLDER_PATH_LENGTH = 400


def _ensure_composed_path_fits(path: str) -> None:
    """Raise FolderNameInvalidError when a composed folder path would
    exceed the safe budget. We validate this on every create path so
    we never commit a row whose children would break storage-key
    insertion."""
    if len(path) > MAX_FOLDER_PATH_LENGTH:
        from .exceptions import FolderNameInvalidError
        raise FolderNameInvalidError(
            f"Folder path would exceed {MAX_FOLDER_PATH_LENGTH} characters. "
            f"Use shorter names or a shallower nesting level."
        )


def create_folder(
    user,
    *,
    name: str,
    parent_id: Optional[UUID] = None,
) -> Folder:
    """Create a single folder under `parent_id` (or at root). Raises
    FolderConflictError on sibling name collision, FolderNotFoundError
    if `parent_id` is given but doesn't belong to `user`.

    The sibling-uniqueness guarantee ultimately comes from the two
    partial unique indexes on Folder; we convert IntegrityError into
    FolderConflictError so the API surface can return a clean 409.
    """
    clean_name = validate_folder_name(name)

    parent: Optional[Folder] = None
    if parent_id is not None:
        parent = selectors.get_user_folder(user, parent_id)
        if parent is None:
            raise FolderNotFoundError("Parent folder not found.")

    path = _compose_child_path(parent, clean_name)
    _ensure_composed_path_fits(path)

    try:
        with transaction.atomic():
            folder = Folder.objects.create(
                owner=user,
                parent=parent,
                name=clean_name,
                path=path,
            )
            AuditLog.objects.create(
                user=user,
                action=AuditLog.Action.FOLDER_CREATE,
                file_id=None,
                file_name=clean_name,
                metadata={"path": path, "parent_id": str(parent_id) if parent_id else None},
            )
    except IntegrityError as exc:
        # Postgres partial unique constraint fired — name collides with a
        # sibling. We deliberately don't distinguish root vs non-root
        # here; the user-visible message is the same either way.
        raise FolderConflictError() from exc

    return folder


def ensure_folder_path(
    user,
    relative_path: str,
    *,
    base: Optional[Folder] = None,
) -> Optional[Folder]:
    """Walk/create the folder chain described by `relative_path`, starting
    from `base` (or root if None). Returns the deepest Folder, or `base`
    when the path is empty. Used by the folder-upload flow so the client
    only has to send the relative path per file and the server lazily
    materializes the hierarchy.

    Idempotent — an existing folder at each segment is reused, not
    re-created. Concurrent calls racing to materialize the same chain
    can have at most one loser per segment; we catch that case and
    re-fetch so the loser sees the same result as the winner."""
    segments = validate_relative_folder_path(relative_path)
    if not segments:
        return base

    current = base
    for segment in segments:
        # Scoped sibling lookup. Use pk-based filters so we don't care
        # about `current` being None (=root).
        qs = Folder.objects.filter(owner=user, name=segment)
        if current is None:
            qs = qs.filter(parent__isnull=True)
        else:
            qs = qs.filter(parent=current)

        existing = qs.first()
        if existing:
            current = existing
            continue

        # Create the missing segment. If two uploads race on the same
        # chain, one hits IntegrityError on the partial unique — fall
        # back to a re-fetch so both threads converge on the same row.
        composed_path = _compose_child_path(current, segment)
        _ensure_composed_path_fits(composed_path)
        try:
            with transaction.atomic():
                current = Folder.objects.create(
                    owner=user,
                    parent=current,
                    name=segment,
                    path=composed_path,
                )
                AuditLog.objects.create(
                    user=user,
                    action=AuditLog.Action.FOLDER_CREATE,
                    file_id=None,
                    file_name=segment,
                    metadata={
                        "path": current.path,
                        "parent_id": str(current.parent_id) if current.parent_id else None,
                        "auto": True,
                    },
                )
        except IntegrityError:
            # Lost a race; re-fetch and proceed.
            current = qs.first()
            if current is None:
                # Genuine constraint failure with no sibling — re-raise
                # as conflict so the caller sees something sensible.
                raise FolderConflictError()

    return current


def delete_folder(user, folder: Folder) -> dict:
    """Synchronously delete `folder` and every descendant + every file
    under it. Returns {folders_deleted, files_deleted, versions_purged}.

    Ordering matters for the last-write-wins contract we maintain for
    individual files. For each file we:
      1. Flip status → DELETING (short TX, row-locked).
      2. Run `delete_all_versions` to purge B2 versions + markers.
      3. Hard-delete the DB row in a short TX with an audit entry.
    Then we delete the Folder rows bottom-up (deepest path first) so the
    FK constraint stays satisfied and any partial failure is recoverable.

    Cap: if the subtree holds more than FOLDER_SUBTREE_FILE_CAP ready
    files, we refuse with FolderTooLargeError. The sync endpoint can't
    safely take longer than the HTTP timeout, and the MVP doesn't
    include the background-task fallback that would lift the cap.

    Failure handling: if a B2 purge fails mid-walk, we raise immediately
    and leave the remaining files intact. Already-purged files are
    already gone from the DB, so the user sees a partial delete and can
    retry. `reap_deleting` will catch any file stuck in DELETING.
    """
    files_qs = selectors.list_files_in_subtree(folder)
    file_count = files_qs.count()
    if file_count > FOLDER_SUBTREE_FILE_CAP:
        raise FolderTooLargeError(file_count, FOLDER_SUBTREE_FILE_CAP)

    # Snapshot subtree metadata BEFORE we start deleting. Mutating the
    # tree while iterating it via the ORM is asking for trouble.
    subtree_folder_ids = selectors.subtree_folder_ids(folder)
    files_snapshot = list(
        files_qs.values("id", "name", "storage_key", "size")
    )

    total_versions_purged = 0
    files_deleted = 0

    for entry in files_snapshot:
        file_id = entry["id"]
        storage_key = entry["storage_key"]
        file_name = entry["name"]

        # Step 1: lock + flip to DELETING.
        with transaction.atomic():
            row = File.objects.select_for_update().filter(pk=file_id).first()
            if row is None:
                # Already cleaned up by a racing delete; count + skip.
                continue
            if row.status == File.Status.UPLOADING:
                # An upload is still streaming to this key. We can't
                # safely purge right now. Surface it as busy so the user
                # can retry the folder delete in a moment.
                raise FileBusyError(
                    "A file in this folder is still uploading. "
                    "Please try again in a moment."
                )
            if row.status != File.Status.DELETING:
                row.status = File.Status.DELETING
                row.save(update_fields=["status", "updated_at"])

        # Step 2: sync B2 purge.
        purged = storage_service.delete_all_versions(storage_key)
        total_versions_purged += purged

        # Step 3: hard-delete + audit.
        with transaction.atomic():
            File.objects.filter(pk=file_id).delete()
            AuditLog.objects.create(
                user=user,
                action=AuditLog.Action.DELETE,
                file_id=file_id,
                file_name=file_name,
                metadata={
                    "storage_key": storage_key,
                    "versions_purged": purged,
                    "via_folder_delete": True,
                    "folder_path": folder.path,
                },
            )
        files_deleted += 1

    # Delete folders deepest-first so FK constraints stay satisfied
    # (children have parent FKs on CASCADE, but deleting deepest-first
    # also means each row we remove has zero children, which keeps the
    # plan cheap and makes the intent obvious).
    folders_to_delete = list(
        Folder.objects.filter(pk__in=subtree_folder_ids)
        .order_by("-path")  # deeper paths sort after shallower ones
        .values("id", "name", "path")
    )

    with transaction.atomic():
        Folder.objects.filter(
            pk__in=[f["id"] for f in folders_to_delete]
        ).delete()
        AuditLog.objects.create(
            user=user,
            action=AuditLog.Action.FOLDER_DELETE,
            file_id=None,
            file_name=folder.name,
            metadata={
                "path": folder.path,
                "folders_deleted": len(folders_to_delete),
                "files_deleted": files_deleted,
                "versions_purged": total_versions_purged,
            },
        )

    return {
        "folders_deleted": len(folders_to_delete),
        "files_deleted": files_deleted,
        "versions_purged": total_versions_purged,
    }


# ── Folder download ZIP ──────────────────────────────────────────

def build_folder_zip(user, folder: Folder) -> tuple[tempfile.SpooledTemporaryFile, str]:
    """Build a ZIP of `folder`'s entire subtree and return (stream, filename).

    The stream is a SpooledTemporaryFile — it stays in RAM until 10 MB,
    then spills to disk. Caller is responsible for closing it (StreamingHttpResponse
    will do this automatically). It is positioned at offset 0, ready to
    stream back to the client.

    Each file's path inside the ZIP mirrors the subtree structure
    relative to `folder` — opening the archive reproduces the folder
    tree the user sees in the UI.

    Errors bubble up as StorageError if a file's bytes can't be fetched
    from B2. The caller should let that propagate to the HTTP layer as
    502. We don't attempt partial ZIPs; a half-complete archive is a
    worse UX than a clean failure.
    """
    files_qs = selectors.list_files_in_subtree(folder)
    file_count = files_qs.count()
    if file_count > FOLDER_SUBTREE_FILE_CAP:
        raise FolderTooLargeError(file_count, FOLDER_SUBTREE_FILE_CAP)

    # `folder.path` is the subtree root — strip it from each file's
    # folder path to get the ZIP-relative path. +1 for the trailing /.
    root_prefix = folder.path
    root_strip_len = len(root_prefix) + 1  # "work/projects/" — 14 chars stripped

    spool = tempfile.SpooledTemporaryFile(
        max_size=10 * 1024 * 1024,  # 10 MB in-RAM threshold
        mode="w+b",
    )

    # ZIP_STORED keeps CPU low; most user files (pdf/docx/png/jpeg) are
    # already compressed. ZIP_DEFLATED would burn CPU for no real win.
    try:
        with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            # Prefetch folder paths so we can reconstruct the arcname
            # without hitting the DB per-file.
            folder_path_by_id = {
                f.id: f.path
                for f in Folder.objects.filter(
                    owner=user,
                    pk__in=selectors.subtree_folder_ids(folder),
                ).only("id", "path")
            }

            # Track arcnames we've already used — if two files share a
            # name in the same folder (shouldn't happen per our unique
            # constraints, but defence in depth), we dedupe with a
            # numeric suffix so the ZIP stays valid.
            used_arcnames: set[str] = set()

            for file_row in files_qs.iterator(chunk_size=50):
                folder_path = folder_path_by_id.get(file_row.folder_id, "")
                # Relative path inside the ZIP: strip the subtree-root prefix.
                if folder_path == root_prefix:
                    rel_dir = ""
                elif folder_path.startswith(root_prefix + "/"):
                    rel_dir = folder_path[root_strip_len:]
                else:
                    # File's folder sits outside the subtree — shouldn't
                    # happen given how we select, but don't crash.
                    rel_dir = ""

                arcname = _make_unique_arcname(
                    rel_dir, file_row.name, used_arcnames
                )
                used_arcnames.add(arcname)

                # Write an entry header, then stream bytes from B2
                # straight into the zipfile's write stream. This keeps
                # us off the "hold a full file in memory" path.
                info = zipfile.ZipInfo(filename=arcname)
                info.date_time = file_row.updated_at.timetuple()[:6]
                info.compress_type = zipfile.ZIP_STORED
                with zf.open(info, mode="w", force_zip64=True) as entry_stream:
                    storage_service.download_to_stream(
                        file_row.storage_key, entry_stream
                    )

        spool.seek(0)
    except Exception:
        spool.close()
        raise

    filename = _safe_zip_filename(folder.name)
    AuditLog.objects.create(
        user=user,
        action=AuditLog.Action.FOLDER_DOWNLOAD,
        file_id=None,
        file_name=folder.name,
        metadata={"path": folder.path, "file_count": file_count},
    )
    return spool, filename


def _make_unique_arcname(rel_dir: str, name: str, used: set[str]) -> str:
    """Return `rel_dir/name`, appending `_<n>` before the extension if
    the arcname is already in `used`. Keeps ZIP entries unambiguous."""
    base = f"{rel_dir}/{name}" if rel_dir else name
    if base not in used:
        return base

    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 1
    while True:
        candidate_name = f"{stem}_{n}.{ext}" if ext else f"{stem}_{n}"
        candidate = f"{rel_dir}/{candidate_name}" if rel_dir else candidate_name
        if candidate not in used:
            return candidate
        n += 1


def _safe_zip_filename(folder_name: str) -> str:
    cleaned = _ZIP_FILENAME_UNSAFE.sub("_", folder_name).strip().rstrip(".") or "folder"
    return f"{cleaned}.zip"


# ── Signed folder-download token ─────────────────────────────────

def issue_folder_download_token(user, folder: Folder) -> dict:
    """Return {url, expires_at, filename} for a one-click folder download.

    The browser can't send an Authorization header on a vanilla `<a href>`
    click, so we mint a short-lived signed token tied to (user, folder)
    and embed it in the URL. The download endpoint verifies the token
    and re-checks ownership before streaming the ZIP.
    """
    signer = TimestampSigner(salt=_FOLDER_DOWNLOAD_SIGNER_SALT)
    token = signer.sign(f"{user.id}:{folder.id}")
    expires_at = timezone.now() + timedelta(seconds=FOLDER_DOWNLOAD_TOKEN_TTL_SECONDS)
    return {
        "token": token,
        "expires_at": expires_at,
        "filename": _safe_zip_filename(folder.name),
    }


def verify_folder_download_token(token: str) -> tuple[int, UUID]:
    """Validate a folder-download token and return (user_id, folder_id).

    Raises `ValueError` for bad/expired tokens. The endpoint wrapper
    converts these into 403 so the error surface stays small and
    predictable.
    """
    signer = TimestampSigner(salt=_FOLDER_DOWNLOAD_SIGNER_SALT)
    try:
        value = signer.unsign(
            token, max_age=FOLDER_DOWNLOAD_TOKEN_TTL_SECONDS
        )
    except SignatureExpired as exc:
        raise ValueError("Token has expired.") from exc
    except BadSignature as exc:
        raise ValueError("Invalid token.") from exc

    try:
        user_id_str, folder_id_str = value.split(":", 1)
        return int(user_id_str), UUID(folder_id_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Malformed token payload.") from exc
