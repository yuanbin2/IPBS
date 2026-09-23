from django.urls import path

from ..views.knowledge import (
    DocumentDetailView,
    DocumentListUploadView,
    DocumentReindexView,
    KnowledgeBaseArchiveView,
    KnowledgeBaseDetailView,
    KnowledgeBaseListView,
    KnowledgeSearchView,
    TaskStatusView,
)

urlpatterns = [
    path("knowledge-bases/", KnowledgeBaseListView.as_view(), name="knowledge-base-list"),
    path("knowledge-bases/<int:pk>/", KnowledgeBaseDetailView.as_view(), name="knowledge-base-detail"),
    path("knowledge-bases/<int:pk>/archive/", KnowledgeBaseArchiveView.as_view(), name="knowledge-base-archive"),
    path("documents/", DocumentListUploadView.as_view(), name="document-list-upload"),
    path("documents/<int:pk>/", DocumentDetailView.as_view(), name="document-detail"),
    path("documents/<int:pk>/reindex/", DocumentReindexView.as_view(), name="document-reindex"),
    path("knowledge-search/", KnowledgeSearchView.as_view(), name="knowledge-search"),
    path("tasks/<str:task_id>/", TaskStatusView.as_view(), name="task-status"),
]
