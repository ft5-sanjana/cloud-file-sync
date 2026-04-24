from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from ninja import Schema


class FileOut(Schema):
    id: UUID
    name: str
    size: int
    mime_type: str
    extension: str
    status: str
    folder_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_model(instance) -> "FileOut":
        return FileOut(
            id=instance.id,
            name=instance.name,
            size=instance.size,
            mime_type=instance.mime_type,
            extension=instance.extension,
            status=instance.status,
            folder_id=instance.folder_id,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )


class FileListOut(Schema):
    items: List[FileOut]
    total: int
    page: int
    page_size: int


SignedUrlMode = Literal["preview", "download"]


class SignedUrlOut(Schema):
    url: str
    expires_at: datetime
    mode: SignedUrlMode


class StorageUsageOut(Schema):
    used: int
    quota: int
    file_count: int


class ErrorOut(Schema):
    code: str
    message: str


# ── Folders ──────────────────────────────────────────────────────

class FolderOut(Schema):
    """Single folder row. `path` is the materialized path without
    leading/trailing slashes; empty string means the folder sits at
    root. `file_count` / `subfolder_count` are direct (one-level)
    counts — the UI uses them to decide whether to show an empty-state
    hint and are cheap because each folder-scoped query hits one
    index."""

    id: UUID
    name: str
    path: str
    parent_id: Optional[UUID]
    file_count: int
    subfolder_count: int
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_model(
        instance,
        *,
        file_count: int = 0,
        subfolder_count: int = 0,
    ) -> "FolderOut":
        return FolderOut(
            id=instance.id,
            name=instance.name,
            path=instance.path,
            parent_id=instance.parent_id,
            file_count=file_count,
            subfolder_count=subfolder_count,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )


class FolderCreateIn(Schema):
    name: str
    parent_id: Optional[UUID] = None


class FolderListOut(Schema):
    items: List[FolderOut]


class FolderDeleteResultOut(Schema):
    """Reported after a synchronous folder delete. `folders_deleted`
    counts every Folder row removed (including descendants), and
    `files_deleted` counts File rows whose B2 versions were purged."""

    folders_deleted: int
    files_deleted: int
    versions_purged: int


class FolderDownloadUrlOut(Schema):
    """Returned by `GET /folders/{id}/download-url`. The URL is a
    signed-token endpoint the browser can navigate to directly (it
    carries the token in the query string, so no Authorization header
    is required)."""

    url: str
    expires_at: datetime
    filename: str
