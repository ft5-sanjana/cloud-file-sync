"""High-level object-store operations the rest of the app uses.

Rules:
- Never leak boto3-specific exceptions upward — translate to StorageError.
- Never return B2 URLs directly; always go through presign_get.
- upload_stream must stream, not buffer; callers may pass 100MB+ files.
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import IO, Literal, Optional

from botocore.exceptions import ClientError
from django.conf import settings

from .client import get_client
from .exceptions import StorageError

logger = logging.getLogger(__name__)


def upload_stream(key: str, fileobj: IO[bytes], content_type: str) -> None:
    """Stream `fileobj` to the bucket under `key`. Raises StorageError on failure.

    boto3 handles multipart transparently for files over 8MB. `fileobj` must
    be a binary, seekable stream — Django's TemporaryUploadedFile satisfies
    this (we also set FILE_UPLOAD_MAX_MEMORY_SIZE low to force disk spill).
    """
    client = get_client()
    try:
        client.upload_fileobj(
            fileobj,
            settings.B2_BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": content_type},
        )
    except ClientError as exc:
        logger.exception("B2 upload failed: key=%s", key)
        raise StorageError(f"Upload failed: {exc}") from exc


def delete_object(key: str) -> None:
    """Idempotent delete — missing-key is treated as success."""
    client = get_client()
    try:
        client.delete_object(Bucket=settings.B2_BUCKET_NAME, Key=key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("NoSuchKey", "404"):
            return
        logger.exception("B2 delete failed: key=%s", key)
        raise StorageError(f"Delete failed: {exc}") from exc


Disposition = Literal["inline", "attachment"]


def presign_get(
    key: str,
    *,
    ttl_seconds: Optional[int] = None,
    disposition: Optional[Disposition] = None,
    filename: Optional[str] = None,
) -> str:
    """Issue a short-lived presigned GET URL.

    - `disposition="inline"` for preview (browser renders)
    - `disposition="attachment"` for download (browser saves)
    - `filename` is encoded via RFC 5987 to preserve unicode display names
    """
    client = get_client()
    params: dict[str, str] = {
        "Bucket": settings.B2_BUCKET_NAME,
        "Key": key,
    }
    if disposition:
        if filename:
            quoted = urllib.parse.quote(filename, safe="")
            params["ResponseContentDisposition"] = (
                f"{disposition}; filename*=UTF-8''{quoted}"
            )
        else:
            params["ResponseContentDisposition"] = disposition

    try:
        return client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=ttl_seconds or settings.SIGNED_URL_TTL_SECONDS,
        )
    except ClientError as exc:
        logger.exception("B2 presign failed: key=%s", key)
        raise StorageError(f"Presign failed: {exc}") from exc
