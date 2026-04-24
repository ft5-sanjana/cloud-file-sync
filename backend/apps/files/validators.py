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
    FolderNameInvalidError,
    MimeMismatchError,
    UnsupportedFileTypeError,
)

# ── Extension allowlist ──────────────────────────────────────────
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        "doc", "docx", "pdf", "xls", "xlsx", "ppt", "pptx",
        "png", "jpeg", "jpg", "svg", "txt",
        # ODT (OpenDocument Text) and generic ZIP archives.
        "odt", "zip",
    }
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
    # ODT files are ZIP containers — libmagic typically reports the
    # OpenDocument MIME when the archive's `mimetype` entry is first,
    # but falls back to plain `application/zip` when it isn't (same
    # quirk as docx/xlsx/pptx above).
    "odt": {
        "application/vnd.oasis.opendocument.text",
        "application/zip",
        "application/octet-stream",
    },
    # Generic ZIP. `application/x-zip-compressed` is the legacy
    # Windows/IIS label — accept it so clients don't get rejected based
    # on which toolchain produced the archive.
    "zip": {
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    },
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
    "odt": "application/vnd.oasis.opendocument.text",
    "zip": "application/zip",
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


# ── Folder name / relative path validation ──────────────────────
# A folder name is displayed in the UI and becomes a segment of the
# materialized path AND a segment of every child file's storage_key. A
# bad name (slashes, control bytes, dots-only) would forge a prefix or
# escape the user's object-store namespace, so we're strict here.

# Reserved on Windows; we forbid them defensively even though our
# primary targets are Linux/macOS. Case-insensitive.
_WINDOWS_RESERVED_NAMES: frozenset[str] = frozenset({
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
})

# Hard cap on folder depth — stops pathological uploads with a
# thousand nested directories and keeps materialized paths within the
# 1024-char column budget.
MAX_FOLDER_DEPTH = 32

# Single-segment length cap. Leaves comfortable headroom for the
# 1024-char `path` column and the 512-char `storage_key` column.
MAX_FOLDER_NAME_LENGTH = 255


def validate_folder_name(name: str) -> str:
    """Validate and canonicalize a single folder-name segment.

    Rejects empty, whitespace-only, names containing path separators,
    null bytes, control characters, trailing dots/spaces (Windows
    pitfall), or reserved device names. Returns the stripped name —
    callers should use the return value, not the original input.
    """
    if not isinstance(name, str):
        raise FolderNameInvalidError("Folder name must be a string.")

    stripped = name.strip()
    if not stripped:
        raise FolderNameInvalidError("Folder name cannot be empty.")
    if len(stripped) > MAX_FOLDER_NAME_LENGTH:
        raise FolderNameInvalidError(
            f"Folder name cannot exceed {MAX_FOLDER_NAME_LENGTH} characters."
        )

    # Any separator-looking byte is a hierarchy-forging attempt — the
    # caller is responsible for splitting `a/b/c` into segments before
    # calling this function.
    for bad in ("/", "\\", "\x00"):
        if bad in stripped:
            raise FolderNameInvalidError(
                "Folder name cannot contain path separators or null bytes."
            )

    # Control characters (tabs, newlines, DEL, etc). Quietly reject — no
    # legitimate folder name needs them and they break our audit logging.
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in stripped):
        raise FolderNameInvalidError(
            "Folder name cannot contain control characters."
        )

    # `.` and `..` resolve to parent/current-dir when composed into
    # paths — always reject, regardless of where they appear.
    if stripped in {".", ".."}:
        raise FolderNameInvalidError("Folder name cannot be '.' or '..'.")

    # Windows strips trailing spaces and dots silently. Ban both
    # outright so a name that lists fine from an API doesn't become a
    # different name when extracted on Windows.
    if stripped.endswith(".") or stripped.endswith(" "):
        raise FolderNameInvalidError(
            "Folder name cannot end with a dot or space."
        )

    if stripped.lower() in _WINDOWS_RESERVED_NAMES:
        raise FolderNameInvalidError(
            f"'{stripped}' is a reserved name and cannot be used."
        )

    return stripped


def validate_relative_folder_path(relative_path: str) -> list[str]:
    """Validate a relative path (a/b/c) and return the segment list.

    Accepts forward slash separators only — the browser gives us
    `webkitRelativePath` which uses `/` even on Windows. Leading and
    trailing slashes are stripped. Each segment is validated as a
    folder name. An empty path after stripping means "root" (empty
    list), which callers may accept or reject depending on context.
    """
    if not isinstance(relative_path, str):
        raise FolderNameInvalidError("Folder path must be a string.")

    # Normalize: collapse backslashes to forward slashes so Windows-born
    # paths work, then strip leading/trailing separators.
    normalized = relative_path.replace("\\", "/").strip().strip("/")
    if not normalized:
        return []

    segments = normalized.split("/")
    if len(segments) > MAX_FOLDER_DEPTH:
        raise FolderNameInvalidError(
            f"Folder path exceeds maximum depth of {MAX_FOLDER_DEPTH}."
        )

    return [validate_folder_name(s) for s in segments]


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
