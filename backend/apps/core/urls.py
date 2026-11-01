from django.urls import path

from .views import HealthCheckView, ReadyCheckView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("ready/", ReadyCheckView.as_view(), name="ready-check"),
]
