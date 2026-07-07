from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/agent/", include("apps.agent_api.urls")),
    path("api/", include("apps.core.urls")),
]
