from django.urls import path

from ..views.blog_agent import BlogAgentChatView
from ..views.blog_articles import (
    BlogArticleDetailView,
    BlogArticleDiscoverView,
    BlogArticleListCreateView,
    BlogArticlePublishView,
    BlogArticleRelatedView,
    BlogImageUploadView,
)
from ..views.blog_imports import BlogHtmlImportPreviewView
from ..views.blog_notes import PrivateNoteDetailView, PrivateNoteListCreateView, PrivateNoteRestoreView
from ..views.blog_public import (
    BlogAboutView,
    BlogArchiveView,
    BlogCategoryListView,
    BlogCommentCreateView,
    BlogCommentModerateView,
    BlogCommentModerationListView,
    BlogCommentReportCreateView,
    BlogCommentReportListView,
    BlogCommentReportReviewView,
    BlogTagListView,
)
from ..views.blog_restrictions import (
    BlogInteractionAppealView,
    BlogInteractionRestrictionActionView,
    BlogInteractionRestrictionListView,
    MyBlogInteractionRestrictionView,
)
from ..views.blog_writing import BlogWritingAgentView

urlpatterns = [
    path("blog/imports/html/preview/", BlogHtmlImportPreviewView.as_view(), name="blog-html-import-preview"),
    path("blog/notes/", PrivateNoteListCreateView.as_view(), name="blog-note-list-create"),
    path("blog/notes/<int:note_id>/", PrivateNoteDetailView.as_view(), name="blog-note-detail"),
    path("blog/notes/<int:note_id>/restore/", PrivateNoteRestoreView.as_view(), name="blog-note-restore"),
    path("blog/articles/", BlogArticleListCreateView.as_view(), name="blog-article-list-create"),
    path("blog/articles/discover/", BlogArticleDiscoverView.as_view(), name="blog-article-discover"),
    path("blog/articles/<str:slug>/related/", BlogArticleRelatedView.as_view(), name="blog-article-related"),
    path("blog/articles/<str:slug>/", BlogArticleDetailView.as_view(), name="blog-article-detail"),
    path("blog/articles/<str:slug>/publish/", BlogArticlePublishView.as_view(), name="blog-article-publish"),
    path("blog/articles/<str:slug>/comments/", BlogCommentCreateView.as_view(), name="blog-comment-create"),
    path("blog/comments/moderation/", BlogCommentModerationListView.as_view(), name="blog-comment-moderation-list"),
    path("blog/comments/<int:comment_id>/moderate/", BlogCommentModerateView.as_view(), name="blog-comment-moderate"),
    path(
        "blog/comments/<int:comment_id>/reports/",
        BlogCommentReportCreateView.as_view(),
        name="blog-comment-report-create",
    ),
    path("blog/comments/reports/", BlogCommentReportListView.as_view(), name="blog-comment-report-list"),
    path("blog/comment-restriction/me/", MyBlogInteractionRestrictionView.as_view(), name="blog-restriction-me"),
    path("blog/comment-restriction/appeal/", BlogInteractionAppealView.as_view(), name="blog-restriction-appeal"),
    path(
        "blog/comment-restrictions/",
        BlogInteractionRestrictionListView.as_view(),
        name="blog-restriction-list-create",
    ),
    path(
        "blog/comment-restrictions/<int:restriction_id>/",
        BlogInteractionRestrictionActionView.as_view(),
        name="blog-restriction-action",
    ),
    path(
        "blog/comments/reports/<int:report_id>/review/",
        BlogCommentReportReviewView.as_view(),
        name="blog-comment-report-review",
    ),
    path("blog/images/", BlogImageUploadView.as_view(), name="blog-image-upload"),
    path("blog/categories/", BlogCategoryListView.as_view(), name="blog-category-list"),
    path("blog/tags/", BlogTagListView.as_view(), name="blog-tag-list"),
    path("blog/archive/", BlogArchiveView.as_view(), name="blog-archive"),
    path("blog/about/", BlogAboutView.as_view(), name="blog-about"),
    path("blog/agent/chat/", BlogAgentChatView.as_view(), name="blog-agent-chat"),
    path("blog/writing-agent/generate/", BlogWritingAgentView.as_view(), name="blog-writing-agent-generate"),
]
