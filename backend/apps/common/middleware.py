"""Common middleware: request IDs and security headers.

Kept intentionally dependency-free (no django-csp, no structlog). Everything
here is stdlib + Django so the project stays auditable at a glance.

Scope note on CSP: Django serves the API, admin, and `/api/docs` (Swagger).
User-facing pages — including the file preview dialog that loads B2 signed
URLs — are served by Next.js on a separate origin, so Django's CSP does NOT
gate the preview. If you later want CSP on the SPA, set it via
`next.config.ts` headers or a Next middleware. The CSP below targets only
Django-served surfaces (admin + Swagger).
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Thread-local populated by RequestIDMiddleware and read by RequestIDLogFilter.
# Falls back to "-" for code paths outside a request (management commands,
# Celery tasks) so log formatters with %(request_id)s never KeyError.
_request_state = threading.local()


def _set_request_id(rid: str) -> None:
    _request_state.request_id = rid


def _clear_request_id() -> None:
    if hasattr(_request_state, "request_id"):
        del _request_state.request_id


def _current_request_id() -> str:
    return getattr(_request_state, "request_id", "-")


class RequestIDMiddleware:
    """Attach a request ID to every request and echo it on the response.

    - If the client sent `X-Request-ID`, reuse it (after length/charset guard).
    - Otherwise generate a UUID4 hex.
    - `request.request_id` is set for views; the value is also published on a
      thread-local so `RequestIDLogFilter` can stamp log records.
    """

    MAX_INCOMING_LEN = 64
    _SAFE_CHARS = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    )

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        rid = incoming if self._is_safe(incoming) else uuid.uuid4().hex

        request.request_id = rid  # type: ignore[attr-defined]
        _set_request_id(rid)
        try:
            response = self.get_response(request)
        finally:
            _clear_request_id()
        response[REQUEST_ID_HEADER] = rid
        return response

    @classmethod
    def _is_safe(cls, value: str) -> bool:
        if not value or len(value) > cls.MAX_INCOMING_LEN:
            return False
        return all(c in cls._SAFE_CHARS for c in value)


class SecurityHeadersMiddleware:
    """Apply security headers Django's SecurityMiddleware doesn't cover.

    Django's built-in middleware handles HSTS, nosniff, referrer policy, and
    SSL redirect. This adds:
      - Content-Security-Policy (restrictive; scoped to Django-served surfaces
        only — see module docstring).
      - Cross-Origin-Opener-Policy: same-origin
      - Cross-Origin-Resource-Policy: same-origin
      - Permissions-Policy: deny powerful APIs we don't use.

    `script-src`/`style-src` permit 'unsafe-inline' and the jsdelivr CDN so
    Django Ninja's Swagger UI at /api/docs keeps working. Production deploys
    that don't expose Swagger can tighten these via a settings override.
    """

    # Static — no env-driven pieces. Built once at import-time equivalent.
    _CSP = "; ".join(
        [
            "default-src 'self'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
            "img-src 'self' data: blob:",
            "media-src 'self' blob:",
            "frame-src 'self'",
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
            "font-src 'self' data:",
            "connect-src 'self'",
        ]
    )
    _PERMISSIONS = (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    )

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        # Don't clobber anything a view set deliberately.
        response.setdefault("Content-Security-Policy", self._CSP)
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.setdefault("Permissions-Policy", self._PERMISSIONS)
        return response


class RequestIDLogFilter(logging.Filter):
    """Stamp every log record with the current request ID.

    Reads from the thread-local populated by RequestIDMiddleware. Outside a
    request (management commands, Celery tasks) the value is "-" so formatters
    using %(request_id)s never raise.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _current_request_id()
        return True
