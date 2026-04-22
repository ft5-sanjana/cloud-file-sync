from django.contrib import admin

from .models import AuditLog, File


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "size", "extension", "status", "created_at")
    list_filter = ("status", "extension")
    search_fields = ("name", "owner__email", "storage_key")
    readonly_fields = ("id", "storage_key", "checksum_sha256", "created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "file_name", "user", "created_at")
    list_filter = ("action",)
    search_fields = ("file_name", "user__email")
    readonly_fields = ("user", "action", "file_id", "file_name", "metadata", "created_at")
    ordering = ("-created_at",)
