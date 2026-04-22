"""Business logic for account creation, authentication, and lifecycle.

Thin service layer keeps view handlers focused on HTTP concerns (parsing,
response shaping, cookie management) and isolates rules that need to be
tested/reused (password validation, uniqueness, token issuance).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

logger = logging.getLogger(__name__)


class AccountError(Exception):
    """Raised when a user-facing account operation fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class IssuedTokens:
    access: str
    refresh: str


# ── Register ─────────────────────────────────────────────────────
def register_user(
    *, first_name: str, last_name: str, email: str, password: str
) -> User:
    normalized_email = email.strip().lower()

    # Run Django's password validators (min length, common, numeric, etc.)
    try:
        validate_password(password)
    except ValidationError as exc:
        raise AccountError("WEAK_PASSWORD", "; ".join(exc.messages)) from exc

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=normalized_email,
                password=password,
                first_name=first_name.strip(),
                last_name=last_name.strip(),
            )
    except IntegrityError as exc:
        raise AccountError("EMAIL_TAKEN", "A user with this email already exists.") from exc

    return user


def authenticate_user(*, email: str, password: str) -> Optional[User]:
    """Return the user on success, None on invalid credentials."""
    user = authenticate(username=email.strip().lower(), password=password)
    if user is None or not user.is_active:
        return None
    return user


def issue_tokens(user: User) -> IssuedTokens:
    refresh = RefreshToken.for_user(user)
    return IssuedTokens(access=str(refresh.access_token), refresh=str(refresh))


def blacklist_refresh(token_str: str) -> None:
    """Best-effort blacklist. Swallows invalid-token errors so logout is idempotent."""
    try:
        RefreshToken(token_str).blacklist()
    except Exception:  # noqa: BLE001 — logout should never fail loudly
        pass


# ── Profile update ───────────────────────────────────────────────
def update_profile(
    user: User,
    *,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> User:
    """Update first_name / last_name on the current user.

    PATCH-style: only provided fields are written. first_name must be
    non-empty after stripping when supplied; last_name may be cleared.
    """
    update_fields: list[str] = []

    if first_name is not None:
        trimmed = first_name.strip()
        if not trimmed:
            raise AccountError("VALIDATION_ERROR", "First name cannot be empty.")
        if len(trimmed) > 75:
            raise AccountError("VALIDATION_ERROR", "First name is too long.")
        user.first_name = trimmed
        update_fields.append("first_name")

    if last_name is not None:
        trimmed = last_name.strip()
        if len(trimmed) > 75:
            raise AccountError("VALIDATION_ERROR", "Last name is too long.")
        user.last_name = trimmed
        update_fields.append("last_name")

    if update_fields:
        user.save(update_fields=update_fields)
    return user


# ── Password change ──────────────────────────────────────────────
def _blacklist_all_outstanding(user: User) -> int:
    """Blacklist every un-blacklisted outstanding refresh token for this user.

    Used after a password change and before account deletion. Returns the
    number of tokens newly blacklisted (for logging/telemetry).
    """
    qs = OutstandingToken.objects.filter(
        user=user, blacklistedtoken__isnull=True
    )
    # Materialize once; the ORM can't bulk_create on a queryset that still
    # references the iteration cursor mid-insert.
    tokens = list(qs)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=t) for t in tokens],
        ignore_conflicts=True,
    )
    return len(tokens)


def change_password(
    user: User, *, old_password: str, new_password: str
) -> IssuedTokens:
    """Verify old password, validate new, rotate hash, blacklist all refresh tokens,
    and issue fresh tokens the caller can hand back to the client.

    Returning new tokens lets the client stay logged in on the same request
    instead of forcing a hard logout/redirect, while the blacklist step
    guarantees that tokens from any OTHER session (phone, other browser)
    stop working.
    """
    if not user.check_password(old_password):
        raise AccountError("INVALID_OLD_PASSWORD", "Current password is incorrect.")

    if old_password == new_password:
        raise AccountError(
            "SAME_PASSWORD", "New password must be different from the current password."
        )

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        raise AccountError("WEAK_PASSWORD", "; ".join(exc.messages)) from exc

    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password"])
        count = _blacklist_all_outstanding(user)

    logger.info(
        "password_changed user_id=%s blacklisted_tokens=%s", user.id, count
    )
    return issue_tokens(user)


# ── Account deletion ─────────────────────────────────────────────
def delete_account(user: User, *, password: str) -> None:
    """Verify password, collect B2 keys, blacklist tokens, delete the user.

    Execution order (the comments here are the interview-worthy part):

      1. Verify password — account deletion is destructive, so we re-auth
         even though the caller is already JWT-authenticated. Protects
         against stolen access tokens / unattended browsers.
      2. Snapshot storage keys for every file the user owns. We do this
         INSIDE the transaction so the set can't shift underneath us.
      3. Blacklist every outstanding refresh token so no other session can
         come back after we're gone (OutstandingToken.user is SET_NULL, so
         the user cascade would orphan them instead of killing them).
      4. Delete the User row. File rows cascade via File.owner=CASCADE;
         AuditLog rows survive with user=None (on_delete=SET_NULL) — they're
         intentionally retained for compliance.
      5. Schedule the B2 object purge on commit. Do this AFTER commit so the
         worker can't race the transaction and hit rows that haven't been
         deleted yet — and so we never delete B2 objects for a DB rollback.

    Returns nothing; the caller handles cookie cleanup and response shaping.
    """
    if not user.check_password(password):
        raise AccountError("INVALID_PASSWORD", "Password is incorrect.")

    # Import deferred to avoid celery init at settings-load time.
    from . import tasks
    from apps.files.models import File

    user_id = user.id
    email = user.email

    with transaction.atomic():
        # Snapshot keys BEFORE the cascade nukes the rows.
        storage_keys: list[str] = list(
            File.objects.filter(owner=user)
            .exclude(storage_key="")
            .values_list("storage_key", flat=True)
        )
        _blacklist_all_outstanding(user)
        user.delete()

        # Enqueue after commit — never before. A rollback must not leave
        # B2 objects in-flight for deletion.
        if storage_keys:
            transaction.on_commit(
                lambda: tasks.purge_b2_objects.delay(storage_keys, email)
            )

    logger.info(
        "account_deleted user_id=%s email=%s b2_objects_scheduled=%s",
        user_id, email, len(storage_keys),
    )


def iter_user_b2_keys(user: User) -> Iterable[str]:
    """Small convenience, mostly for tests and admin tooling."""
    from apps.files.models import File
    return (
        File.objects.filter(owner=user)
        .exclude(storage_key="")
        .values_list("storage_key", flat=True)
    )
