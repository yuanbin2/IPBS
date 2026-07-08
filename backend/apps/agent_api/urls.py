from django.urls import path

from .views import (
    AgentChatView,
    ConversationDetailView,
    ConversationListView,
    DocumentListUploadView,
    DocumentReindexView,
    KnowledgeBaseListView,
    KnowledgeSearchView,
)

urlpatterns = [
    path("chat/", AgentChatView.as_view(), name="agent-chat"),
    path("conversations/", ConversationListView.as_view(), name="conversation-list"),
    path("conversations/<int:pk>/", ConversationDetailView.as_view(), name="conversation-detail"),
    path("knowledge-bases/", KnowledgeBaseListView.as_view(), name="knowledge-base-list"),
    path("documents/", DocumentListUploadView.as_view(), name="document-list-upload"),
    path("documents/<int:pk>/reindex/", DocumentReindexView.as_view(), name="document-reindex"),
    path("knowledge-search/", KnowledgeSearchView.as_view(), name="knowledge-search"),
]
