from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from apps.common.health import router as health_router

api = NinjaAPI(title="Cloud File Sync API", version="0.1.0")
api.add_router("/health", health_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
