"""Folders + folder-aware file constraints.

Schema deltas:
    * New ``files_folder`` table for the virtual hierarchy.
    * ``files_file.folder_id`` nullable FK (NULL = root).
    * The original single ``unique_ready_file_per_owner_name`` constraint is
      replaced by two partial uniques — one for root files, one for
      sub-folder files — because Postgres treats NULLs as distinct and a
      single ``(owner, folder, name)`` unique would silently let two
      root-level ``notes.txt`` rows coexist.
    * ``AuditLog.action`` gets three folder-scoped choices.
"""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("files", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Folder",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("path", models.CharField(db_index=True, max_length=1024)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="folders",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="files.folder",
                    ),
                ),
            ],
            options={
                "db_table": "files_folder",
                "indexes": [
                    models.Index(fields=["owner", "parent"], name="folders_owner_parent_idx"),
                    models.Index(fields=["owner", "path"], name="folders_owner_path_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("parent__isnull", True)),
                        fields=("owner", "name"),
                        name="unique_root_folder_per_owner_name",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("parent__isnull", False)),
                        fields=("owner", "parent", "name"),
                        name="unique_sub_folder_per_owner_parent_name",
                    ),
                ],
            },
        ),
        # The original constraint covered only (owner, name). With folders in
        # play we need per-scope uniqueness, so drop it before the new pair
        # goes in — keeping it would fight the root-scoped constraint.
        migrations.RemoveConstraint(
            model_name="file",
            name="unique_ready_file_per_owner_name",
        ),
        migrations.AddField(
            model_name="file",
            name="folder",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="files",
                to="files.folder",
            ),
        ),
        migrations.AddIndex(
            model_name="file",
            index=models.Index(fields=["owner", "folder"], name="files_owner_folder_idx"),
        ),
        migrations.AddConstraint(
            model_name="file",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "ready"), ("folder__isnull", True)),
                fields=("owner", "name"),
                name="unique_ready_root_file_per_owner_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="file",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "ready"), ("folder__isnull", False)),
                fields=("owner", "folder", "name"),
                name="unique_ready_sub_file_per_owner_folder_name",
            ),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("upload", "Upload"),
                    ("overwrite", "Overwrite"),
                    ("delete", "Delete"),
                    ("download", "Download"),
                    ("preview", "Preview"),
                    ("folder_create", "Folder create"),
                    ("folder_delete", "Folder delete"),
                    ("folder_download", "Folder download"),
                ],
                max_length=32,
            ),
        ),
    ]
