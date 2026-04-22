"""File validation: extension, MIME sniffing, SVG sanitization, size.

Security principles:
- Never trust the client's Content-Type.
- Sniff actual bytes with libmagic.
- Accept an extension only if its sniffed MIME is in a per-extension allowlist.
  The allowlist is intentionally tolerant of libmagic quirks (DOCX/XLSX often
  sniff as application/zip; TXT as text/plain; SVG sometimes as text/xml).
- SVG is sanitized via bleach before storage — rendering raw user SVGs via a
  signed URL would otherwise be a stored-XSS vector.
"""
from __future__ import annotations

import os
from typing import IO

import bleach
import magic
from django.conf import settings

from .exceptions import (
    FileTooLargeError,
    MimeMismatchError,
    UnsupportedFileTypeError,
)

# ── Extension allowlist ──────────────────────────────────────────
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {"doc", "docx", "pdf", "xls", "xlsx", "ppt", "pptx", "png", "jpeg", "jpg", "svg", "txt"}
)

# Per-extension allowed sniffed MIMEs. Entries are deliberately permissive
# because libmagic's labeling is inconsistent across versions and file variants.
EXT_MIME_MAP: dict[str, set[str]] = {
    "doc": {"application/msword", "application/x-ole-storage", "application/octet-stream"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
    "pdf": {"application/pdf"},
    "xls": {
        "application/vnd.ms-excel",
        "application/x-ole-storage",
        "application/octet-stream",
    },
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/octet-stream",
    },
    "ppt": {
        "application/vnd.ms-powerpoint",
        "application/x-ole-storage",
        "application/octet-stream",
    },
    "pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/zip",
        "application/octet-stream",
    },
    "png": {"image/png"},
    "jpeg": {"image/jpeg"},
    "jpg": {"image/jpeg"},
    "svg": {
        "image/svg+xml",
        "text/xml",
        "application/xml",
        "text/plain",
        "text/html",  # libmagic sometimes labels SVG as HTML
    },
    "txt": {"text/plain", "application/octet-stream"},
}

# Canonical MIME we STORE for each extension (what we return in responses and
# what B2 sees as Content-Type). Avoids leaking libmagic's inconsistencies.
CANONICAL_MIME: dict[str, str] = {
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "svg": "image/svg+xml",
    "txt": "text/plain",
}


def extract_extension(filename: str) -> str:
    """Return lowercase extension without the leading dot. Empty string if none."""
    _, ext = os.path.splitext(filename)
    return ext.lower().lstrip(".")


def validate_size(size: int) -> None:
    if size <= 0:
        # Accept zero-byte files — matches common OS behavior for placeholders.
        if size < 0:
            raise FileTooLargeError(settings.MAX_FILE_SIZE_BYTES)
    if size > settings.MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(settings.MAX_FILE_SIZE_BYTES)


def validate_extension(filename: str) -> str:
    ext = extract_extension(filename)
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(ext or "(none)")
    return ext


def sniff_mime(head: bytes) -> str:
    """Return MIME detected from magic bytes. Uses libmagic via python-magic."""
    return magic.from_buffer(head, mime=True)


def validate_mime_matches_extension(extension: str, sniffed_mime: str) -> None:
    allowed = EXT_MIME_MAP.get(extension)
    if not allowed or sniffed_mime not in allowed:
        raise MimeMismatchError(extension, sniffed_mime)


def canonical_mime_for(extension: str) -> str:
    return CANONICAL_MIME.get(extension, "application/octet-stream")


def read_head(fileobj: IO[bytes], n: int = 8192) -> bytes:
    """Read first `n` bytes and rewind. `fileobj` must be seekable."""
    fileobj.seek(0)
    head = fileobj.read(n)
    fileobj.seek(0)
    return head


# ── SVG sanitization ─────────────────────────────────────────────
_SVG_ALLOWED_TAGS = [
    "svg", "g", "path", "circle", "ellipse", "line", "polyline", "polygon",
    "rect", "text", "tspan", "defs", "linearGradient", "radialGradient",
    "stop", "title", "desc", "use", "symbol", "clipPath", "pattern",
    "marker", "filter", "feGaussianBlur", "feOffset", "feBlend",
    "feColorMatrix", "feFlood", "feComposite", "feMerge", "feMergeNode",
    "feMorphology", "feDropShadow",
]

_SVG_ALLOWED_ATTRS = {
    "*": [
        "id", "class", "fill", "stroke", "stroke-width", "stroke-linecap",
        "stroke-linejoin", "stroke-dasharray", "stroke-opacity", "fill-opacity",
        "opacity", "transform", "d", "points", "viewBox", "width", "height",
        "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
        "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
        "patternUnits", "markerWidth", "markerHeight", "refX", "refY", "orient",
        "clipPathUnits", "clip-path", "mask", "filter", "style",
        "preserveAspectRatio", "stdDeviation", "dx", "dy", "in", "in2",
        "result", "mode", "values", "type", "flood-color", "flood-opacity",
        "operator", "k1", "k2", "k3", "k4", "radius",
    ],
    "svg": ["xmlns", "xmlns:xlink", "version", "viewBox", "width", "height"],
    "use": ["href", "xlink:href"],
}


def sanitize_svg(content: bytes) -> bytes:
    """Strip scripts, event handlers, and dangerous URIs from SVG content."""
    text = content.decode("utf-8", errors="replace")
    cleaned = bleach.clean(
        text,
        tags=_SVG_ALLOWED_TAGS,
        attributes=_SVG_ALLOWED_ATTRS,
        protocols=["http", "https"],
        strip=True,
        strip_comments=True,
    )
    return cleaned.encode("utf-8")
