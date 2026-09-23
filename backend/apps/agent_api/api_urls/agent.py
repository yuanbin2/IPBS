from django.urls import path

from ..views.chat import AgentChatStreamView, AgentChatView
from ..views.conversations import ConversationDetailView, ConversationListView
from ..views.observability import (
    EvaluationCaseListView,
    EvaluationRunView,
    ObservabilityDashboardView,
)

urlpatterns = [
    path("chat/", AgentChatView.as_view(), name="agent-chat"),
    path("chat/stream/", AgentChatStreamView.as_view(), name="agent-chat-stream"),
    path("conversations/", ConversationListView.as_view(), name="conversation-list"),
    path("conversations/<int:pk>/", ConversationDetailView.as_view(), name="conversation-detail"),
    path("observability/", ObservabilityDashboardView.as_view(), name="observability-dashboard"),
    path("evaluation-cases/", EvaluationCaseListView.as_view(), name="evaluation-case-list"),
    path("evaluation-runs/", EvaluationRunView.as_view(), name="evaluation-run"),
]
