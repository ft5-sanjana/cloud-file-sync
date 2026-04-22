"""Storage key generation — user-supplied names never reach the bucket."""
from __future__ import annotations

import uuid


def generate_storage_key(user_id: int, extension: str) -> str:
    """
    Produce a deterministic-prefix, UUID-suffixed key.

    Example: `users/42/3e94f8c2-78a3-4b11-9a7b-0e1e6a5dfae1.pdf`

    The user prefix lets us list/reconcile a single user's objects efficiently
    and limits damage radius if a single key is ever exposed.
    """
    clean_ext = extension.lower().lstrip(".")
    return f"users/{user_id}/{uuid.uuid4()}.{clean_ext}"
