"""Owner-scoped read helpers. Every file/folder lookup goes through here —
no endpoint should ever pull a File or Folder by id without filtering on the
owner."""
from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

from django.db.models import Count, Q, QuerySet, Sum

from .models import File, Folder


def get_user_file(user, file_id: UUID, *, statuses: Optional[tuple[str, ...]] = None) -> Optional[File]:
    """
    Fetch a single File by id, requiring ownership by `user`.

    Returns None if the id doesn't exist, the row belongs to another user,
    or its status isn't in `statuses` (when provided). Callers should surface
    a uniform 404 on None to avoid leaking existence to the wrong owner.
    """
    qs = File.objects.filter(pk=file_id, owner=user)
    if statuses is not None:
        qs = qs.filter(status__in=statuses)
    return qs.first()


def list_user_files(
    user,
    *,
    q: Optional[str] = None,
    folder_id: Optional[UUID] = None,
) -> QuerySet[File]:
    """List ready files. When `folder_id` is None, returns only files at
    root (folder IS NULL). When `folder_id` is provided, returns only
    files directly inside that folder — descendants are excluded so the
    UI shows one level at a time. A search `q` ignores the folder
    filter and spans the user's entire tree; that matches how users
    expect search to behave (they want the file, not the location)."""
    qs = (
        File.objects.filter(owner=user, status=File.Status.READY)
        .only(
            "id", "name", "size", "mime_type", "extension",
            "status", "folder_id", "created_at", "updated_at",
        )
        .order_by("-created_at")
    )
    if q:
        # Search is tree-wide by design — hide the folder filter.
        return qs.filter(name__icontains=q.strip())

    if folder_id is None:
        qs = qs.filter(folder__isnull=True)
    else:
        qs = qs.filter(folder_id=folder_id)
    return qs


def compute_storage_usage(user) -> dict[str, int]:
    ready_qs = File.objects.filter(owner=user, status=File.Status.READY)
    used = ready_qs.aggregate(total=Sum("size"))["total"] or 0
    return {
        "used": used,
        "quota": user.storage_quota,
        "file_count": ready_qs.count(),
    }


# ── Folder lookups ───────────────────────────────────────────────

def get_user_folder(user, folder_id: UUID) -> Optional[Folder]:
    """Single-folder fetch with owner filter. Callers should surface a
    uniform 404 on None so we don't leak the existence of another
    user's folder id."""
    return Folder.objects.filter(pk=folder_id, owner=user).first()


def list_user_folders(
    user, *, parent_id: Optional[UUID] = None
) -> list[Folder]:
    """Folders directly under `parent_id` (or root if None), annotated
    with direct file/subfolder counts so the list UI doesn't need a
    round-trip per row. Returned as a list — it's a small fan-out
    (siblings only), not worth keeping lazy."""
    qs = Folder.objects.filter(owner=user)
    if parent_id is None:
        qs = qs.filter(parent__isnull=True)
    else:
        qs = qs.filter(parent_id=parent_id)

    qs = qs.annotate(
        file_count_=Count(
            "files",
            filter=Q(files__status=File.Status.READY),
            distinct=True,
        ),
        subfolder_count_=Count("children", distinct=True),
    ).order_by("name")

    return list(qs)


def subtree_folder_ids(folder: Folder) -> list[UUID]:
    """List every folder id in `folder`'s subtree (including `folder`
    itself), owner-scoped. Materialized-path prefix match — single
    index scan on (owner, path). No recursive CTE needed.

    Guard against the `work` vs `workshop` trap by requiring a trailing
    slash on the prefix. `folder.path` always equals `<parent_path>/<name>`
    (or `<name>` for root folders), never an empty string, so the
    prefix `f"{folder.path}/"` is always well-formed."""
    return list(
        Folder.objects.filter(owner=folder.owner)
        .filter(Q(pk=folder.pk) | Q(path__startswith=f"{folder.path}/"))
        .values_list("id", flat=True)
    )


def list_files_in_subtree(folder: Folder) -> QuerySet[File]:
    """Every READY file whose folder is in `folder`'s subtree. Used by
    folder delete and folder ZIP — both are size-capped before call
    so we don't care that this returns a full queryset."""
    subtree_ids = subtree_folder_ids(folder)
    return File.objects.filter(
        owner=folder.owner,
        status=File.Status.READY,
        folder_id__in=subtree_ids,
    )
