from django.urls import path

from ..views.agent import (
    AgentChatView,
    ConversationDetailView,
    ConversationListView,
    EvaluationCaseListView,
    EvaluationRunView,
    ObservabilityDashboardView,
)

urlpatterns = [
    path("chat/", AgentChatView.as_view(), name="agent-chat"),
    path("conversations/", ConversationListView.as_view(), name="conversation-list"),
    path("conversations/<int:pk>/", ConversationDetailView.as_view(), name="conversation-detail"),
    path("observability/", ObservabilityDashboardView.as_view(), name="observability-dashboard"),
    path("evaluation-cases/", EvaluationCaseListView.as_view(), name="evaluation-case-list"),
    path("evaluation-runs/", EvaluationRunView.as_view(), name="evaluation-run"),
]
