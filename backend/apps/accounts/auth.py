"""Ninja auth class that validates simplejwt access tokens."""
from __future__ import annotations

from typing import Optional

from django.contrib.auth import get_user_model
from ninja.security import HttpBearer
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken, TokenError

User = get_user_model()


class JWTAuth(HttpBearer):
    """Validates a Bearer access token and attaches `request.auth = user`.

    Usage in a Ninja router: `@router.get("/path", auth=JWTAuth())`.

    Any auth-related exception from simplejwt (bad signature, expired,
    missing claim, *user no longer exists*) must degrade to a 401 — the
    UI's refresh-then-redirect flow expects 401, not 500. `get_user`
    raises `AuthenticationFailed` for a vanished user (e.g. after a DB
    reset where an old access token still lives in localStorage), so we
    catch that too.
    """

    def authenticate(self, request, token: str) -> Optional["User"]:  # type: ignore[override]
        validator = JWTAuthentication()
        try:
            validated = validator.get_validated_token(token)
            user = validator.get_user(validated)
        except (InvalidToken, TokenError, AuthenticationFailed):
            return None
        if not user or not user.is_active:
            return None
        # Attach to request.user so services can pull it uniformly.
        request.user = user
        return user


jwt_auth = JWTAuth()
