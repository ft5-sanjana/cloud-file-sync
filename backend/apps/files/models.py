from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class File(models.Model):
    """User-owned file metadata. Bytes live in the object store under `storage_key`."""

    class Status(models.TextChoices):
        UPLOADING = "uploading", "Uploading"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        DELETING = "deleting", "Deleting"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="files",
    )

    # Display name — user-supplied. Never used as a path or object key.
    name = models.CharField(max_length=255)

    # Object-store key: users/{user_id}/{uuid}.{ext}
    storage_key = models.CharField(max_length=512, unique=True)

    size = models.BigIntegerField()
    mime_type = models.CharField(max_length=127)
    extension = models.CharField(max_length=10)

    checksum_sha256 = models.CharField(max_length=64, null=True, blank=True)

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.UPLOADING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "files_file"
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="files_owner_created_idx"),
            models.Index(fields=["owner", "name"], name="files_owner_name_idx"),
            models.Index(fields=["status"], name="files_status_idx"),
        ]
        constraints = [
            # Last-write-wins: at most one READY row per (owner, name). Rows in
            # other statuses are excluded so overwrite transitions don't collide.
            models.UniqueConstraint(
                fields=["owner", "name"],
                condition=Q(status="ready"),
                name="unique_ready_file_per_owner_name",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} ({self.owner_id})"


class AuditLog(models.Model):
    """Audit trail for file operations — denormalized so records survive file deletion."""

    class Action(models.TextChoices):
        UPLOAD = "upload", "Upload"
        OVERWRITE = "overwrite", "Overwrite"
        DELETE = "delete", "Delete"
        DOWNLOAD = "download", "Download"
        PREVIEW = "preview", "Preview"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="file_audit_logs",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    file_id = models.UUIDField(null=True, blank=True)
    file_name = models.CharField(max_length=255)
    metadata = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "files_audit_log"
        indexes = [
            models.Index(fields=["user", "-created_at"], name="audit_user_created_idx"),
            models.Index(fields=["action"], name="audit_action_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.action} {self.file_name} by user={self.user_id}"
