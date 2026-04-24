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


def generate_storage_key_with_path(
    user_id: int, folder_path: str, extension: str
) -> str:
    """Path-preserving variant for files inside folders.

    Example: `users/42/work/reports/3e94f8c2-...-....pdf`

    `folder_path` is the materialized folder.path WITHOUT leading or trailing
    slashes (empty string = root, in which case this collapses back to the
    flat `generate_storage_key` layout).

    The filename itself stays a UUID — user-supplied names never reach the
    bucket, and the UUID is what lets Phase-5 overwrite purges target the
    *exact* evicted object without collateral damage to sibling files.

    Embedding folder_path in the prefix means a server-side rename or move
    (out of scope for the MVP) would require re-keying; we accept that
    tradeoff because the prefix is what makes listing a folder subtree a
    single cheap ListObjectsV2 call instead of an index scan on DB rows.
    """
    clean_ext = extension.lower().lstrip(".")
    clean_path = folder_path.strip("/")
    if clean_path:
        return f"users/{user_id}/{clean_path}/{uuid.uuid4()}.{clean_ext}"
    return f"users/{user_id}/{uuid.uuid4()}.{clean_ext}"
