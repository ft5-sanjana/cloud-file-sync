"""Owner-scoped read helpers. Every file lookup goes through here — no
endpoint should ever pull a File by id without filtering on the owner."""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from django.db.models import QuerySet, Sum

from .models import File


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


def list_user_files(user, *, q: Optional[str] = None) -> QuerySet[File]:
    qs = (
        File.objects.filter(owner=user, status=File.Status.READY)
        .only(
            "id", "name", "size", "mime_type", "extension",
            "status", "created_at", "updated_at",
        )
        .order_by("-created_at")
    )
    if q:
        qs = qs.filter(name__icontains=q.strip())
    return qs


def compute_storage_usage(user) -> dict[str, int]:
    ready_qs = File.objects.filter(owner=user, status=File.Status.READY)
    used = ready_qs.aggregate(total=Sum("size"))["total"] or 0
    return {
        "used": used,
        "quota": user.storage_quota,
        "file_count": ready_qs.count(),
    }
