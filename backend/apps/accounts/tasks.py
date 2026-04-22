"""Celery tasks for account lifecycle.

Only one job here right now: purge every B2 object that belonged to a
deleted account. Called from `services.delete_account` via
`transaction.on_commit`, so the DB user row is gone by the time this runs.
"""
from __future__ import annotations

import logging

from celery import shared_task

from apps.storage import service as storage_service
from apps.storage.exceptions import StorageError

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(StorageError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def purge_b2_objects(self, storage_keys: list[str], user_email: str) -> None:
    """Delete the B2 objects for a deleted user.

    Per-key errors are swallowed at the storage layer (missing keys are
    treated as success by `delete_object`). Any broader StorageError
    triggers the whole task to retry via Celery — we don't try to be
    clever and skip over the failed key, because partial success on a
    retry would surface as spurious "not found" events.

    `user_email` is here only for the audit log / structured log line;
    the user row is already gone by the time we're called.
    """
    if not storage_keys:
        return

    logger.info(
        "purge_b2_objects start user=%s count=%s", user_email, len(storage_keys)
    )

    for key in storage_keys:
        storage_service.delete_object(key)

    logger.info(
        "purge_b2_objects done user=%s count=%s", user_email, len(storage_keys)
    )
