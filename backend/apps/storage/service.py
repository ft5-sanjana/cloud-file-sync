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
    """Idempotent delete of the *current* version of `key`.

    NOTE: On a versioned bucket (B2 buckets are versioned by default) this
    only writes a delete marker — it does NOT purge prior versions. For
    user-facing deletes and overwrite cleanup, use `delete_all_versions`
    instead. This function is retained for unversioned contexts and
    callers that specifically want marker-based deletion.
    """
    client = get_client()
    try:
        client.delete_object(Bucket=settings.B2_BUCKET_NAME, Key=key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("NoSuchKey", "404"):
            return
        logger.exception("B2 delete failed: key=%s", key)
        raise StorageError(f"Delete failed: {exc}") from exc


def delete_all_versions(key: str) -> int:
    """Permanently remove every version *and* delete marker for `key`.

    Returns the number of versioned objects purged (0 if the key had no
    versions at all). Idempotent — calling on an already-clean key is a
    no-op that returns 0.

    Implementation details worth preserving:
    - Paginates `list_object_versions` (pages cap at 1000 entries).
    - Includes BOTH `Versions` and `DeleteMarkers` — leaving markers behind
      is exactly the "hidden version" leak we're fixing.
    - Filters results to `Key == key` exactly. `Prefix` alone would match
      sibling keys such as `<key>.bak` or `<key>-foo`.
    - Batches `delete_objects` at 1000 targets per call (S3 hard limit).
    - `VersionId == "null"` is the literal sentinel for objects that were
      written before versioning was enabled; it's passed through as-is.
    - Per-object errors from `delete_objects` bubble up as StorageError so
      the caller can decide to retry or surface a 502 to the user.

    Required IAM/app-key permissions:
    - `s3:ListBucketVersions` (B2 native: listBuckets/listFiles)
    - `s3:DeleteObjectVersion` (B2 native: deleteFiles)
    """
    client = get_client()
    bucket = settings.B2_BUCKET_NAME
    purged = 0

    try:
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket, Prefix=key):
            targets: list[dict[str, str]] = []
            for entry in page.get("Versions", []) or []:
                if entry.get("Key") == key:
                    targets.append(
                        {"Key": entry["Key"], "VersionId": entry["VersionId"]}
                    )
            for entry in page.get("DeleteMarkers", []) or []:
                if entry.get("Key") == key:
                    targets.append(
                        {"Key": entry["Key"], "VersionId": entry["VersionId"]}
                    )

            # Chunk at 1000 to respect the S3 DeleteObjects cap. In practice
            # one page yields ≤1000 so this rarely splits, but the loop is
            # cheap and makes the invariant explicit.
            for start in range(0, len(targets), 1000):
                chunk = targets[start : start + 1000]
                if not chunk:
                    continue
                resp = client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": chunk, "Quiet": True},
                )
                errors = resp.get("Errors") or []
                if errors:
                    logger.error(
                        "B2 delete_objects partial failure: key=%s errors=%s",
                        key, errors,
                    )
                    raise StorageError(
                        f"Failed to purge {len(errors)} version(s) of {key}: {errors[0]}"
                    )
                purged += len(chunk)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        # NoSuchBucket is a config error, not transient — still raise.
        if error_code in ("NoSuchKey", "404"):
            return purged
        logger.exception("B2 list/delete versions failed: key=%s", key)
        raise StorageError(f"Version purge failed for {key}: {exc}") from exc

    logger.info("B2 purge complete: key=%s versions_removed=%d", key, purged)
    return purged


def download_to_stream(key: str, target: IO[bytes]) -> None:
    """Stream the object at `key` into `target` (a writable binary stream).

    Used by the folder ZIP builder — it appends each file's bytes to a
    zipfile write-through stream. Uses boto3's `download_fileobj`, which
    chunks the transfer and never holds the full object in memory.

    Raises StorageError on any transport or S3-side failure. NoSuchKey is
    *not* swallowed here: missing bytes mid-zip is a data-integrity event
    the caller needs to know about.
    """
    client = get_client()
    try:
        client.download_fileobj(settings.B2_BUCKET_NAME, key, target)
    except ClientError as exc:
        logger.exception("B2 download failed: key=%s", key)
        raise StorageError(f"Download failed for {key}: {exc}") from exc


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
