from django.apps import AppConfig


class StorageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.storage"
    label = "app_storage"  # avoid clash with django.contrib's 'storage' concept
