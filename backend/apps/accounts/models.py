from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user: email is the login identifier."""

    email = models.EmailField(unique=True, db_index=True)
    name = models.CharField(max_length=150)

    # Per-user storage quota in bytes (configurable per user; default from settings).
    storage_quota = models.BigIntegerField(default=0)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        db_table = "accounts_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:  # pragma: no cover
        return self.email

    def save(self, *args, **kwargs) -> None:
        # Seed default quota from settings on first save.
        if self._state.adding and not self.storage_quota:
            self.storage_quota = settings.USER_STORAGE_QUOTA_BYTES
        super().save(*args, **kwargs)

    @property
    def storage_used(self) -> int:
        """Sum of bytes of this user's 'ready' files. Lazy until files app exists."""
        try:
            from apps.files.models import File  # noqa: WPS433 — deferred import

            return (
                File.objects.filter(owner=self, status=File.Status.READY)
                .aggregate(total=models.Sum("size"))
                .get("total")
                or 0
            )
        except (ImportError, LookupError):
            return 0
