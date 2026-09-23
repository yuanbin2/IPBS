from django.urls import path

from ..views.governance import (
    ApprovalRequestDetailView,
    ApprovalRequestListView,
    MCPToolBulkHealthCheckView,
    MCPToolDetailView,
    MCPToolExecuteView,
    MCPToolHealthCheckView,
    MCPToolListView,
)

urlpatterns = [
    path("approvals/", ApprovalRequestListView.as_view(), name="approval-list"),
    path("approvals/<int:pk>/", ApprovalRequestDetailView.as_view(), name="approval-detail"),
    path("mcp-tools/", MCPToolListView.as_view(), name="mcp-tool-list"),
    path("mcp-tools/<int:pk>/", MCPToolDetailView.as_view(), name="mcp-tool-detail"),
    path("mcp-tools/<int:pk>/execute/", MCPToolExecuteView.as_view(), name="mcp-tool-execute"),
    path("mcp-tools/<int:pk>/health-check/", MCPToolHealthCheckView.as_view(), name="mcp-tool-health-check"),
    path("mcp-tools/bulk-health-check/", MCPToolBulkHealthCheckView.as_view(), name="mcp-tool-bulk-health-check"),
]
