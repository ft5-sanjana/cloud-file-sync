"""Business logic for account creation and authentication.

Thin service layer keeps view handlers focused on HTTP concerns (parsing,
response shaping, cookie management) and isolates rules that need to be
tested/reused (password validation, uniqueness, token issuance).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


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


def register_user(*, name: str, email: str, password: str) -> User:
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
                name=name.strip(),
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
