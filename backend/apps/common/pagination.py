"""Reusable pagination utilities for Ninja endpoints.

Deliberately minimal — a thin helper over QuerySet slicing, no framework.
Swap for keyset pagination if/when row counts make COUNT(*) too expensive.
"""
from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from ninja import Schema
from pydantic import Field

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class PageParams(Schema):
    page: int = Field(1, ge=1)
    page_size: int = Field(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


def paginate_queryset(qs: QuerySet, *, page: int, page_size: int) -> dict[str, Any]:
    """Return a dict with items slice + pagination metadata."""
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    total = qs.count()
    start = (page - 1) * page_size
    items = list(qs[start : start + page_size])
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
