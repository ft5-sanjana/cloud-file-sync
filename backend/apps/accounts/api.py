"""Auth endpoints: register, login, refresh, logout, me.

Security notes:
- Access tokens are returned in the JSON body (stored in-memory on the client).
- Refresh tokens live ONLY in an HttpOnly, Secure, SameSite=Lax cookie scoped
  to `/api/auth`. They never transit the JSON body.
- Refresh + logout verify Origin against CORS_ALLOWED_ORIGINS to resist CSRF,
  in addition to relying on SameSite=Lax and a custom X-Requested-With header.
"""
from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django_ratelimit.core import is_ratelimited
from ninja import Router
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .auth import jwt_auth
from .schemas import (
    AccessOut,
    ErrorOut,
    LoginIn,
    RegisterIn,
    RegisterOut,
    TokenOut,
    UserOut,
)
from .services import (
    AccountError,
    authenticate_user,
    blacklist_refresh,
    issue_tokens,
    register_user,
)

router = Router(tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth"


def _set_refresh_cookie(response: HttpResponse, refresh: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        secure=not settings.DEBUG,  # allow HTTP in dev
        samesite="Lax",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: HttpResponse) -> None:
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


def _origin_ok(request: HttpRequest) -> bool:
    """Basic CSRF mitigation: Origin/Referer must be in the allowed list."""
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if not origin:
        # For same-origin XHR without Origin header, allow — SameSite=Lax already
        # blocks cross-site cookie attachment on POST.
        return True
    try:
        parsed = urlparse(origin)
        candidate = f"{parsed.scheme}://{parsed.netloc}"
    except ValueError:
        return False
    return candidate in settings.CORS_ALLOWED_ORIGINS


def _user_out(user) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        storage_quota=user.storage_quota,
        storage_used=user.storage_used,
        date_joined=user.date_joined,
    )


# ─── Register ──────────────────────────────────────────────────
@router.post(
    "/register",
    response={201: RegisterOut, 400: ErrorOut, 409: ErrorOut, 429: ErrorOut},
    auth=None,
)
def register(request, payload: RegisterIn):
    if is_ratelimited(
        request, group="auth:register", key="ip", rate="10/h",
        method="POST", increment=True,
    ):
        return 429, ErrorOut(code="RATE_LIMITED", message="Too many registration attempts.")
    try:
        user = register_user(
            name=payload.name, email=payload.email, password=payload.password
        )
    except AccountError as exc:
        status = 409 if exc.code == "EMAIL_TAKEN" else 400
        return status, ErrorOut(code=exc.code, message=exc.message)
    return 201, RegisterOut(id=user.id, email=user.email, name=user.name)


# ─── Login ─────────────────────────────────────────────────────
@router.post(
    "/login",
    response={200: TokenOut, 401: ErrorOut, 429: ErrorOut},
    auth=None,
)
def login(request, payload: LoginIn):
    if is_ratelimited(
        request, group="auth:login", key="ip", rate="5/m",
        method="POST", increment=True,
    ):
        return 429, ErrorOut(code="RATE_LIMITED", message="Too many login attempts.")
    user = authenticate_user(email=payload.email, password=payload.password)
    if user is None:
        return 401, ErrorOut(code="INVALID_CREDENTIALS", message="Invalid email or password.")

    tokens = issue_tokens(user)
    # Build response body via schema (guarantees shape), attach cookie on the HttpResponse.
    body = TokenOut(access=tokens.access, user=_user_out(user))
    response = JsonResponse(body.model_dump(mode="json"), status=200)
    _set_refresh_cookie(response, tokens.refresh)
    return response


# ─── Refresh ───────────────────────────────────────────────────
@router.post(
    "/refresh",
    response={200: AccessOut, 401: ErrorOut, 403: ErrorOut},
    auth=None,
)
def refresh(request):
    if not _origin_ok(request):
        return 403, ErrorOut(code="BAD_ORIGIN", message="Origin not allowed.")

    token_str = request.COOKIES.get(REFRESH_COOKIE_NAME)
    if not token_str:
        return 401, ErrorOut(code="NO_REFRESH", message="No refresh token present.")

    try:
        token = RefreshToken(token_str)
        access = str(token.access_token)
    except (InvalidToken, TokenError):
        return 401, ErrorOut(code="INVALID_REFRESH", message="Refresh token is invalid or expired.")

    return 200, AccessOut(access=access)


# ─── Logout ────────────────────────────────────────────────────
@router.post("/logout", response={204: None, 403: ErrorOut}, auth=jwt_auth)
def logout(request):
    if not _origin_ok(request):
        return 403, ErrorOut(code="BAD_ORIGIN", message="Origin not allowed.")

    token_str = request.COOKIES.get(REFRESH_COOKIE_NAME)
    if token_str:
        blacklist_refresh(token_str)

    response = HttpResponse(status=204)
    _clear_refresh_cookie(response)
    return response


# ─── Me ────────────────────────────────────────────────────────
@router.get("/me", response=UserOut, auth=jwt_auth)
def me(request):
    return _user_out(request.user)
