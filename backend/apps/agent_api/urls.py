from django.urls import path

from .views import AgentChatView, ConversationDetailView, ConversationListView

urlpatterns = [
    path("chat/", AgentChatView.as_view(), name="agent-chat"),
    path("conversations/", ConversationListView.as_view(), name="conversation-list"),
    path("conversations/<int:pk>/", ConversationDetailView.as_view(), name="conversation-detail"),
]
