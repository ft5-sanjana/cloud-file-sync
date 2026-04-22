from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from apps.accounts.api import router as auth_router
from apps.common.health import router as health_router
from apps.files.api import router as files_router

api = NinjaAPI(title="Cloud File Sync API", version="0.1.0")
api.add_router("/health", health_router)
api.add_router("/auth", auth_router)
api.add_router("/files", files_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
