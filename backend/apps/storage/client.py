"""Single boto3 S3 client against the Backblaze B2 S3-compatible endpoint.

Memoized because client construction is non-trivial (TLS, config resolution)
and the client is fully thread-safe for concurrent requests.
"""
from __future__ import annotations

from threading import Lock
from typing import Any

import boto3
from botocore.config import Config
from django.conf import settings

_client: Any = None
_lock = Lock()


def get_client():
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            _client = boto3.client(
                "s3",
                endpoint_url=settings.B2_ENDPOINT_URL or None,
                aws_access_key_id=settings.B2_KEY_ID or None,
                aws_secret_access_key=settings.B2_APPLICATION_KEY or None,
                region_name=settings.B2_REGION or None,
                config=Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                    connect_timeout=5,
                    read_timeout=60,
                ),
            )
    return _client


def reset_client() -> None:
    """Test helper — clear the memoized client (e.g. when env changes in tests)."""
    global _client
    with _lock:
        _client = None
