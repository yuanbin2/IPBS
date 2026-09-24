from django.urls import path

from ..views.projects import (
    ConversationMoveView,
    ConversationProjectDetailView,
    ConversationProjectListCreateView,
)

urlpatterns = [
    path("projects/", ConversationProjectListCreateView.as_view(), name="project-list-create"),
    path("projects/<int:pk>/", ConversationProjectDetailView.as_view(), name="project-detail"),
    path("conversations/<int:pk>/move/", ConversationMoveView.as_view(), name="conversation-move"),
]
