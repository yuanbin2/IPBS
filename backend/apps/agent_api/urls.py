"""Root URL configuration for the agent API.

Routes are grouped by domain so each module stays small and discoverable.
"""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.agent_api.api_urls.auth")),
    path("", include("apps.agent_api.api_urls.agent")),
    path("", include("apps.agent_api.api_urls.knowledge")),
    path("", include("apps.agent_api.api_urls.governance")),
    path("", include("apps.agent_api.api_urls.blog")),
]
