from django.urls import path

from ..views.chat import AgentChatStreamView, AgentChatView
from ..views.conversations import ConversationDetailView, ConversationListView
from ..views.observability import (
    EvaluationBatchCompareView,
    EvaluationBatchCreateView,
    EvaluationBatchDetailView,
    EvaluationBatchListView,
    EvaluationBatchRetryView,
    EvaluationCaseListView,
    EvaluationDatasetFreezeView,
    EvaluationDatasetView,
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
    path("evaluation-datasets/", EvaluationDatasetView.as_view(), name="evaluation-dataset-list-create"),
    path(
        "evaluation-datasets/<int:pk>/freeze/", EvaluationDatasetFreezeView.as_view(), name="evaluation-dataset-freeze"
    ),
    path("evaluation-batches/", EvaluationBatchListView.as_view(), name="evaluation-batch-list"),
    path("evaluation-batches/create/", EvaluationBatchCreateView.as_view(), name="evaluation-batch-create"),
    path("evaluation-batches/compare/", EvaluationBatchCompareView.as_view(), name="evaluation-batch-compare"),
    path("evaluation-batches/<int:pk>/", EvaluationBatchDetailView.as_view(), name="evaluation-batch-detail"),
    path("evaluation-batches/<int:pk>/retry/", EvaluationBatchRetryView.as_view(), name="evaluation-batch-retry"),
    path("evaluation-runs/", EvaluationRunView.as_view(), name="evaluation-run"),
]
