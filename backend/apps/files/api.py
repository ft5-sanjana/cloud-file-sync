"""File management endpoints. M2 ships the upload endpoint only."""
from __future__ import annotations

import logging

from ninja import File as NinjaFile
from ninja import Router
from ninja.files import UploadedFile

from apps.accounts.auth import jwt_auth
from apps.storage.exceptions import StorageError

from .exceptions import FileValidationError, QuotaExceededError
from .schemas import ErrorOut, FileOut
from .services import upload_file

logger = logging.getLogger(__name__)

router = Router(tags=["files"])


@router.post(
    "",
    response={
        201: FileOut,
        400: ErrorOut,
        409: ErrorOut,
        413: ErrorOut,
        503: ErrorOut,
    },
    auth=jwt_auth,
)
def upload(request, file: UploadedFile = NinjaFile(...)):
    try:
        row = upload_file(request.user, file)
    except FileValidationError as exc:
        status = 413 if exc.code == "FILE_TOO_LARGE" else 400
        return status, ErrorOut(code=exc.code, message=exc.message)
    except QuotaExceededError as exc:
        return 409, ErrorOut(code=exc.code, message=exc.message)
    except StorageError:
        # Detail suppressed — don't leak internal paths/errors to clients.
        return 503, ErrorOut(
            code="STORAGE_UNAVAILABLE",
            message="The storage service is temporarily unavailable. Please retry.",
        )
    return 201, FileOut.from_model(row)
