from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Folder(models.Model):
    """User-owned folder — a virtual hierarchy node.

    Folders are pure DB metadata. B2 has no folder primitive; hierarchy is
    expressed by encoding `path` into each child file's storage_key prefix.
    The app is the source of truth for structure.

    `path` is a materialized path that INCLUDES this folder's own name —
    e.g. a root folder "work" has path="work"; its child "projects" has
    path="work/projects". Never contains leading or trailing slashes.
    Used for prefix queries against descendants during folder delete and
    zip. There is no "root folder" row — top-level folders have
    parent=NULL and path=<name>; files/folders not inside any folder
    simply have folder_id=NULL.

    Two partial unique constraints handle the NULL != NULL quirk in
    Postgres: siblings cannot share a name, at root OR under any parent.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="folders",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    name = models.CharField(max_length=255)
    # Materialized path WITHOUT leading/trailing slash; empty string at root.
    # Index it — every folder-scoped query either looks up by exact path or
    # does a `startswith` subtree sweep.
    path = models.CharField(max_length=1024, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "files_folder"
        indexes = [
            models.Index(fields=["owner", "parent"], name="folders_owner_parent_idx"),
            models.Index(fields=["owner", "path"], name="folders_owner_path_idx"),
        ]
        constraints = [
            # Root: parent is NULL. Postgres treats NULLs as distinct, so we
            # need a dedicated partial index to forbid duplicate root names.
            models.UniqueConstraint(
                fields=["owner", "name"],
                condition=Q(parent__isnull=True),
                name="unique_root_folder_per_owner_name",
            ),
            # Non-root: parent is present, so (owner, parent, name) is safe.
            models.UniqueConstraint(
                fields=["owner", "parent", "name"],
                condition=Q(parent__isnull=False),
                name="unique_sub_folder_per_owner_parent_name",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.path or '(root)'} ({self.owner_id})"


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
    # NULL = root. Files cascade-delete with their folder; the service layer
    # still performs a B2 version purge first so bytes don't outlive the row.
    folder = models.ForeignKey(
        Folder,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="files",
    )

    # Display name — user-supplied. Never used as a path or object key.
    name = models.CharField(max_length=255)

    # Object-store key: users/{user_id}/[{folder_path}/]{uuid}.{ext}
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
            models.Index(fields=["owner", "folder"], name="files_owner_folder_idx"),
            models.Index(fields=["status"], name="files_status_idx"),
        ]
        constraints = [
            # Last-write-wins, split by folder presence for the same NULL
            # reason as the Folder model. Without these two partial
            # constraints, two root-level "notes.txt" rows would both pass.
            models.UniqueConstraint(
                fields=["owner", "name"],
                condition=Q(status="ready") & Q(folder__isnull=True),
                name="unique_ready_root_file_per_owner_name",
            ),
            models.UniqueConstraint(
                fields=["owner", "folder", "name"],
                condition=Q(status="ready") & Q(folder__isnull=False),
                name="unique_ready_sub_file_per_owner_folder_name",
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
        FOLDER_CREATE = "folder_create", "Folder create"
        FOLDER_DELETE = "folder_delete", "Folder delete"
        FOLDER_DOWNLOAD = "folder_download", "Folder download"

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
