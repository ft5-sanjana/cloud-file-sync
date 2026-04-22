from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ninja import Schema


class FileOut(Schema):
    id: UUID
    name: str
    size: int
    mime_type: str
    extension: str
    status: str
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
            created_at=instance.created_at,
            updated_at=instance.updated_at,
        )


class ErrorOut(Schema):
    code: str
    message: str
