"""File management endpoints.

All endpoints enforce per-user ownership through `get_user_file` / filtered
querysets. Unauthorized access returns 404 (not 403) to avoid leaking file
existence to the wrong user.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from django_ratelimit.core import is_ratelimited
from ninja import File as NinjaFile
from ninja import Router
from ninja.files import UploadedFile

from apps.accounts.auth import jwt_auth
from apps.common.pagination import MAX_PAGE_SIZE, paginate_queryset
from apps.storage.exceptions import StorageError

from .exceptions import FileBusyError, FileValidationError, QuotaExceededError
from .models import File
from .schemas import (
    ErrorOut,
    FileListOut,
    FileOut,
    SignedUrlMode,
    SignedUrlOut,
    StorageUsageOut,
)
from .selectors import compute_storage_usage, get_user_file, list_user_files
from .services import delete_file, issue_signed_url, upload_file

logger = logging.getLogger(__name__)

router = Router(tags=["files"])
storage_router = Router(tags=["storage"])


# ── POST /api/files — upload ─────────────────────────────────────
@router.post(
    "",
    response={
        201: FileOut,
        400: ErrorOut,
        409: ErrorOut,
        413: ErrorOut,
        429: ErrorOut,
        503: ErrorOut,
    },
    auth=jwt_auth,
)
def upload(request, file: UploadedFile = NinjaFile(...)):
    # Per-user cap: 30 uploads/hour. Authenticated → key on user; IP fallback
    # isn't reached here because jwt_auth rejects unauthenticated callers first.
    if is_ratelimited(
        request, group="files:upload", key="user", rate="30/h",
        method="POST", increment=True,
    ):
        return 429, ErrorOut(
            code="RATE_LIMITED",
            message="Too many uploads. Please slow down and try again later.",
        )
    try:
        row = upload_file(request.user, file)
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


# ── GET /api/files — list with search & pagination ──────────────
@router.get("", response=FileListOut, auth=jwt_auth)
def list_files(
    request,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    # Clamp page_size defensively (Ninja doesn't auto-validate bare query args).
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    page = max(1, page)

    qs = list_user_files(request.user, q=q)
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
        # Row has been flagged DELETING; the reap_deleting beat task will
        # retry the purge. Surface a retryable error to the client.
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
    # Caps both preview and download traffic at 120/hour per user — enough
    # for ordinary browsing, tight enough to blunt URL-harvesting abuse.
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
