"""File & folder management endpoints.

All endpoints enforce per-user ownership through `get_user_file` /
`get_user_folder` / filtered querysets. Unauthorized access returns 404
(not 403) to avoid leaking existence to the wrong user.

Folder download is the only endpoint that accepts a query-string token
instead of the Authorization header — a `<a href>` click from the
browser can't send headers, so we mint a signed token (see
services.issue_folder_download_token) that ties (user, folder) to a
short TTL.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from django.contrib.auth import get_user_model
from django.http import StreamingHttpResponse
from django_ratelimit.core import is_ratelimited
from ninja import File as NinjaFile
from ninja import Form, Router
from ninja.files import UploadedFile

from apps.accounts.auth import jwt_auth
from apps.common.pagination import MAX_PAGE_SIZE, paginate_queryset
from apps.storage.exceptions import StorageError

from .exceptions import (
    FileBusyError,
    FileValidationError,
    FolderConflictError,
    FolderNotFoundError,
    FolderTooLargeError,
    QuotaExceededError,
)
from .models import File
from .schemas import (
    ErrorOut,
    FileListOut,
    FileOut,
    FolderCreateIn,
    FolderDeleteResultOut,
    FolderDownloadUrlOut,
    FolderListOut,
    FolderOut,
    SignedUrlMode,
    SignedUrlOut,
    StorageUsageOut,
)
from .selectors import (
    compute_storage_usage,
    get_user_file,
    get_user_folder,
    list_user_files,
    list_user_folders,
)
from .services import (
    build_folder_zip,
    create_folder,
    delete_file,
    delete_folder,
    ensure_folder_path,
    issue_folder_download_token,
    issue_signed_url,
    upload_file,
    verify_folder_download_token,
)

logger = logging.getLogger(__name__)
User = get_user_model()

router = Router(tags=["files"])
storage_router = Router(tags=["storage"])
folders_router = Router(tags=["folders"])


# ── POST /api/files — upload ─────────────────────────────────────
@router.post(
    "",
    response={
        201: FileOut,
        400: ErrorOut,
        404: ErrorOut,
        409: ErrorOut,
        413: ErrorOut,
        429: ErrorOut,
        503: ErrorOut,
    },
    auth=jwt_auth,
)
def upload(
    request,
    file: UploadedFile = NinjaFile(...),
    folder_id: Optional[UUID] = Form(None),
    relative_path: Optional[str] = Form(None),
):
    """Single-file upload, optionally scoped to a folder.

    Two folder-placement modes:
    - `folder_id` alone: upload directly into that folder. Used by the
      per-file upload flow when the user is already navigated into a
      folder in the UI.
    - `relative_path` (with or without folder_id): materialize the
      folder chain under folder_id (or root) and put the file at the
      leaf. Used by the bulk folder upload flow — each file carries its
      own browser-provided webkitRelativePath.

    Rate limit intentionally lifted to 500/h to accommodate folder
    uploads — a 100-file folder would have exhausted the old 30/h budget
    on the first try.
    """
    if is_ratelimited(
        request, group="files:upload", key="user", rate="500/h",
        method="POST", increment=True,
    ):
        return 429, ErrorOut(
            code="RATE_LIMITED",
            message="Too many uploads. Please slow down and try again later.",
        )

    # Resolve the destination folder (if any). `folder_id` is checked
    # before the heavy work so we fail fast on a bogus folder reference.
    target_folder = None
    if folder_id is not None:
        target_folder = get_user_folder(request.user, folder_id)
        if target_folder is None:
            return 404, ErrorOut(
                code="FOLDER_NOT_FOUND", message="Folder not found."
            )

    # Materialize relative_path (creates intermediate folders as needed).
    # The relative path is the directory part — the filename itself is
    # carried by `file.name` and is NOT included here. The browser's
    # `webkitRelativePath` is "folderA/folderB/file.txt"; the client is
    # expected to strip the filename before sending.
    if relative_path:
        try:
            target_folder = ensure_folder_path(
                request.user, relative_path, base=target_folder
            )
        except FileValidationError as exc:
            return 400, ErrorOut(code=exc.code, message=exc.message)
        except FolderConflictError as exc:
            return 409, ErrorOut(code=exc.code, message=exc.message)

    try:
        row = upload_file(request.user, file, folder=target_folder)
    except FileValidationError as exc:
        status = 413 if exc.code == "FILE_TOO_LARGE" else 400
        return status, ErrorOut(code=exc.code, message=exc.message)
    except QuotaExceededError as exc:
        return 409, ErrorOut(code=exc.code, message=exc.message)
    except StorageError:
        return 503, ErrorOut(
            code="STORAGE_UNAVAILABLE",
            message="The storage service is temporarily unavailable. Please retry.",
        )
    return 201, FileOut.from_model(row)


# ── GET /api/files — list with search, folder scope & pagination ─
@router.get("", response=FileListOut, auth=jwt_auth)
def list_files(
    request,
    q: Optional[str] = None,
    folder_id: Optional[UUID] = None,
    page: int = 1,
    page_size: int = 50,
):
    """List files. `folder_id` absent → root. Search `q` spans the
    entire tree regardless of folder_id — users don't usually know
    *where* the file is when they're searching for it."""
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    page = max(1, page)

    # Verify the folder exists + belongs to the caller. Skip this check
    # for search (folder_id is ignored anyway) so a lingering
    # ?folder_id=... query param doesn't break a user's search URL.
    if folder_id is not None and not q:
        if get_user_folder(request.user, folder_id) is None:
            return FileListOut(items=[], total=0, page=page, page_size=page_size)

    qs = list_user_files(request.user, q=q, folder_id=folder_id)
    result = paginate_queryset(qs, page=page, page_size=page_size)
    return FileListOut(
        items=[FileOut.from_model(f) for f in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


# ── GET /api/files/{id} — single-file detail ────────────────────
@router.get("/{file_id}", response={200: FileOut, 404: ErrorOut}, auth=jwt_auth)
def get_file(request, file_id: UUID):
    row = get_user_file(request.user, file_id, statuses=(File.Status.READY,))
    if row is None:
        return 404, ErrorOut(code="NOT_FOUND", message="File not found.")
    return 200, FileOut.from_model(row)


# ── DELETE /api/files/{id} ──────────────────────────────────────
# Synchronous contract: by the time we return 204, every B2 version and
# delete marker for this key is gone. If the purge fails we return 502 so
# the client can retry — we do NOT report success on half-completed work.
@router.delete(
    "/{file_id}",
    response={204: None, 404: ErrorOut, 409: ErrorOut, 502: ErrorOut},
    auth=jwt_auth,
)
def delete_file_endpoint(request, file_id: UUID):
    row = get_user_file(
        request.user,
        file_id,
        statuses=(
            File.Status.READY,
            File.Status.UPLOADING,
            File.Status.FAILED,
            File.Status.DELETING,
        ),
    )
    if row is None:
        return 404, ErrorOut(code="NOT_FOUND", message="File not found.")
    try:
        delete_file(request.user, row)
    except FileBusyError as exc:
        return 409, ErrorOut(code=exc.code, message=exc.message)
    except StorageError:
        logger.exception("delete_file: B2 purge failed id=%s", file_id)
        return 502, ErrorOut(
            code="STORAGE_PURGE_FAILED",
            message=(
                "Could not fully remove the file from storage. "
                "The deletion will be retried automatically — please try again."
            ),
        )
    return 204, None


# ── GET /api/files/{id}/signed-url ──────────────────────────────
@router.get(
    "/{file_id}/signed-url",
    response={
        200: SignedUrlOut,
        404: ErrorOut,
        409: ErrorOut,
        429: ErrorOut,
        503: ErrorOut,
    },
    auth=jwt_auth,
)
def get_signed_url(
    request,
    file_id: UUID,
    mode: SignedUrlMode = "download",
):
    if is_ratelimited(
        request, group="files:signed-url", key="user", rate="120/h",
        method="GET", increment=True,
    ):
        return 429, ErrorOut(
            code="RATE_LIMITED",
            message="Too many link requests. Please try again shortly.",
        )
    row = get_user_file(request.user, file_id)
    if row is None:
        return 404, ErrorOut(code="NOT_FOUND", message="File not found.")
    if row.status != File.Status.READY:
        return 409, ErrorOut(
            code="NOT_READY",
            message="File is not ready for access yet.",
        )
    try:
        payload = issue_signed_url(request.user, row, mode=mode)
    except StorageError:
        return 503, ErrorOut(
            code="STORAGE_UNAVAILABLE",
            message="The storage service is temporarily unavailable.",
        )
    return 200, SignedUrlOut(**payload)


# ── GET /api/storage/usage ──────────────────────────────────────
@storage_router.get("/usage", response=StorageUsageOut, auth=jwt_auth)
def storage_usage(request):
    data = compute_storage_usage(request.user)
    return StorageUsageOut(**data)


# ═══════════════════════════════════════════════════════════════════
# Folder endpoints
# ═══════════════════════════════════════════════════════════════════

def _folder_out_from(folder) -> FolderOut:
    """Build a FolderOut with direct counts filled in from annotations
    if present, otherwise 0. `list_user_folders` annotates these; a
    single-folder fetch doesn't, which is fine — the single-folder
    endpoints don't return counts in the MVP."""
    file_count = getattr(folder, "file_count_", 0) or 0
    subfolder_count = getattr(folder, "subfolder_count_", 0) or 0
    return FolderOut.from_model(
        folder, file_count=file_count, subfolder_count=subfolder_count
    )


# ── GET /api/folders — list siblings under optional parent ──────
@folders_router.get("", response=FolderListOut, auth=jwt_auth)
def list_folders(request, parent_id: Optional[UUID] = None):
    """Return folders directly under `parent_id` (or at root if omitted).
    The UI calls this once per navigation, pairing the result with the
    files list to render a folder view."""
    if parent_id is not None:
        if get_user_folder(request.user, parent_id) is None:
            return FolderListOut(items=[])
    folders = list_user_folders(request.user, parent_id=parent_id)
    return FolderListOut(items=[_folder_out_from(f) for f in folders])


# ── POST /api/folders — create ──────────────────────────────────
@folders_router.post(
    "",
    response={201: FolderOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def create_folder_endpoint(request, payload: FolderCreateIn):
    try:
        folder = create_folder(
            request.user, name=payload.name, parent_id=payload.parent_id
        )
    except FileValidationError as exc:
        return 400, ErrorOut(code=exc.code, message=exc.message)
    except FolderNotFoundError as exc:
        return 404, ErrorOut(code=exc.code, message=exc.message)
    except FolderConflictError as exc:
        return 409, ErrorOut(code=exc.code, message=exc.message)
    return 201, FolderOut.from_model(folder, file_count=0, subfolder_count=0)


# ── DELETE /api/folders/{id} — synchronous recursive delete ─────
@folders_router.delete(
    "/{folder_id}",
    response={
        200: FolderDeleteResultOut,
        404: ErrorOut,
        409: ErrorOut,
        413: ErrorOut,
        502: ErrorOut,
    },
    auth=jwt_auth,
)
def delete_folder_endpoint(request, folder_id: UUID):
    folder = get_user_folder(request.user, folder_id)
    if folder is None:
        return 404, ErrorOut(code="FOLDER_NOT_FOUND", message="Folder not found.")
    try:
        result = delete_folder(request.user, folder)
    except FileBusyError as exc:
        return 409, ErrorOut(code=exc.code, message=exc.message)
    except FolderTooLargeError as exc:
        return 413, ErrorOut(code=exc.code, message=exc.message)
    except StorageError:
        logger.exception("delete_folder: B2 purge failed id=%s", folder_id)
        return 502, ErrorOut(
            code="STORAGE_PURGE_FAILED",
            message=(
                "Could not fully remove one or more files from storage. "
                "The deletion will be retried automatically — please try again."
            ),
        )
    return 200, FolderDeleteResultOut(**result)


# ── GET /api/folders/{id}/download-url ──────────────────────────
# Returns a signed-token URL the browser can navigate to with a plain
# <a href>. The token is re-validated by the download endpoint below.
@folders_router.get(
    "/{folder_id}/download-url",
    response={200: FolderDownloadUrlOut, 404: ErrorOut, 413: ErrorOut},
    auth=jwt_auth,
)
def folder_download_url(request, folder_id: UUID):
    folder = get_user_folder(request.user, folder_id)
    if folder is None:
        return 404, ErrorOut(code="FOLDER_NOT_FOUND", message="Folder not found.")

    # Cap check up-front — cheaper than letting the user click through,
    # wait, then hit 413 on the download endpoint with no ZIP to show.
    from .selectors import list_files_in_subtree
    from .services import FOLDER_SUBTREE_FILE_CAP

    count = list_files_in_subtree(folder).count()
    if count > FOLDER_SUBTREE_FILE_CAP:
        return 413, ErrorOut(
            code="FOLDER_TOO_LARGE",
            message=(
                f"Folder contains {count} files, which exceeds the limit of "
                f"{FOLDER_SUBTREE_FILE_CAP} for a single download."
            ),
        )

    payload = issue_folder_download_token(request.user, folder)
    # Absolute URL so the frontend can use it as-is. `request.build_absolute_uri`
    # respects the request's host/scheme — proxies should be configured so
    # the scheme is correct (SECURE_PROXY_SSL_HEADER in settings).
    url = request.build_absolute_uri(
        f"/api/folders/{folder.id}/download?token={payload['token']}"
    )
    return 200, FolderDownloadUrlOut(
        url=url,
        expires_at=payload["expires_at"],
        filename=payload["filename"],
    )


# ── GET /api/folders/{id}/download — streams ZIP ────────────────
# Token-authenticated — no JWT header. The token is bound to (user,
# folder) and expires in a few minutes. Auth here is explicit token
# verification; we deliberately do NOT set `auth=jwt_auth`.
@folders_router.get(
    "/{folder_id}/download",
    response={200: None, 403: ErrorOut, 404: ErrorOut, 413: ErrorOut, 502: ErrorOut},
    auth=None,
)
def folder_download(request, folder_id: UUID, token: str):
    try:
        token_user_id, token_folder_id = verify_folder_download_token(token)
    except ValueError as exc:
        return 403, ErrorOut(code="INVALID_TOKEN", message=str(exc))

    # Defense in depth — token carries folder_id, but the URL carries it
    # too. A mismatch means the URL was tampered with; refuse.
    if token_folder_id != folder_id:
        return 403, ErrorOut(
            code="INVALID_TOKEN", message="Token does not match this folder."
        )

    try:
        user = User.objects.get(pk=token_user_id, is_active=True)
    except User.DoesNotExist:
        return 403, ErrorOut(code="INVALID_TOKEN", message="Unknown user for token.")

    folder = get_user_folder(user, folder_id)
    if folder is None:
        return 404, ErrorOut(code="FOLDER_NOT_FOUND", message="Folder not found.")

    try:
        spool, filename = build_folder_zip(user, folder)
    except FolderTooLargeError as exc:
        return 413, ErrorOut(code=exc.code, message=exc.message)
    except StorageError as exc:
        logger.exception("folder_download: ZIP build failed id=%s", folder_id)
        return 502, ErrorOut(
            code="STORAGE_UNAVAILABLE",
            message="Could not build the archive. Please try again.",
        )

    # Stream the ZIP out. SpooledTemporaryFile is readable as a file-like
    # object — Django's StreamingHttpResponse will iterate it in chunks
    # and close it when done.
    def _iter_spool(spool_file, chunk_size: int = 64 * 1024):
        try:
            while True:
                chunk = spool_file.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            spool_file.close()

    response = StreamingHttpResponse(
        _iter_spool(spool), content_type="application/zip"
    )
    # RFC 5987-style filename for unicode folder names.
    import urllib.parse as _urlparse
    quoted = _urlparse.quote(filename, safe="")
    response["Content-Disposition"] = (
        f"attachment; filename*=UTF-8''{quoted}"
    )
    return response
