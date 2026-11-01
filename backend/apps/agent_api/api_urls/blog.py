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
from ..views.blog_collections import (
    BlogCollectionAutoRuleDetailView,
    BlogCollectionAutoRuleView,
    BlogCollectionContextView,
    BlogCollectionBulkExportView,
    BlogCollectionDraftView,
    BlogCollectionEntryDetailView,
    BlogCollectionEntryView,
    BlogCollectionExportView,
    BlogCollectionImportView,
    BlogCollectionMineView,
    BlogCollectionNodeCreateView,
    BlogCollectionNodeDetailView,
    BlogCollectionPublicDetailView,
    BlogCollectionPublicListView,
    BlogCollectionReorderView,
    BlogCollectionSubmitView,
)
from ..views.blog_imports import (
    BlogHtmlImportImageFetchView,
    BlogHtmlImportPreviewView,
)
from ..views.blog_note_images import (
    PrivateNoteImageBindView,
    PrivateNoteImageFetchView,
    PrivateNoteImageReadView,
    PrivateNoteImageUploadView,
)
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
    BlogSettingsView,
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
    path(
        "blog/imports/html/images/fetch/", BlogHtmlImportImageFetchView.as_view(), name="blog-html-import-image-fetch"
    ),
    path("blog/settings/", BlogSettingsView.as_view(), name="blog-settings"),
    path("blog/notes/", PrivateNoteListCreateView.as_view(), name="blog-note-list-create"),
    path("blog/collections/", BlogCollectionPublicListView.as_view(), name="blog-collection-public-list"),
    path("blog/collections/mine/", BlogCollectionMineView.as_view(), name="blog-collection-mine"),
    # 归档导出/导入（B-067）：批量导出与导入是单段路径，必须排在 <uuid> 通配之前注册。
    path("blog/collections/export/", BlogCollectionBulkExportView.as_view(), name="blog-collection-bulk-export"),
    path("blog/collections/import/", BlogCollectionImportView.as_view(), name="blog-collection-import"),
    path(
        "blog/collections/<uuid:public_id>/export/",
        BlogCollectionExportView.as_view(),
        name="blog-collection-export",
    ),
    path("blog/collections/<uuid:public_id>/draft/", BlogCollectionDraftView.as_view(), name="blog-collection-draft"),
    path(
        "blog/collections/<uuid:public_id>/nodes/",
        BlogCollectionNodeCreateView.as_view(),
        name="blog-collection-node-create",
    ),
    path(
        "blog/collections/<uuid:public_id>/nodes/<int:node_id>/",
        BlogCollectionNodeDetailView.as_view(),
        name="blog-collection-node-detail",
    ),
    path(
        "blog/collections/<uuid:public_id>/entries/",
        BlogCollectionEntryView.as_view(),
        name="blog-collection-entry-create",
    ),
    path(
        "blog/collections/<uuid:public_id>/entries/<int:entry_id>/",
        BlogCollectionEntryDetailView.as_view(),
        name="blog-collection-entry-detail",
    ),
    path(
        "blog/collections/<uuid:public_id>/reorder/",
        BlogCollectionReorderView.as_view(),
        name="blog-collection-reorder",
    ),
    path(
        "blog/collections/<uuid:public_id>/auto-rules/",
        BlogCollectionAutoRuleView.as_view(),
        name="blog-collection-auto-rule-list",
    ),
    path(
        "blog/collections/<uuid:public_id>/auto-rules/<int:rule_id>/",
        BlogCollectionAutoRuleDetailView.as_view(),
        name="blog-collection-auto-rule-detail",
    ),
    path(
        "blog/collections/<uuid:public_id>/submit/", BlogCollectionSubmitView.as_view(), name="blog-collection-submit"
    ),
    path("blog/collections/context/", BlogCollectionContextView.as_view(), name="blog-collection-context"),
    path(
        "blog/collections/<uuid:public_id>/",
        BlogCollectionPublicDetailView.as_view(),
        name="blog-collection-public-detail",
    ),
    path("blog/notes/<int:note_id>/", PrivateNoteDetailView.as_view(), name="blog-note-detail"),
    path("blog/notes/<int:note_id>/restore/", PrivateNoteRestoreView.as_view(), name="blog-note-restore"),
    path("blog/notes/images/", PrivateNoteImageUploadView.as_view(), name="blog-note-image-upload"),
    path("blog/notes/images/fetch/", PrivateNoteImageFetchView.as_view(), name="blog-note-image-fetch"),
    path("blog/notes/images/<int:image_id>/", PrivateNoteImageReadView.as_view(), name="blog-note-image-read"),
    path(
        "blog/notes/<int:note_id>/images/bind/",
        PrivateNoteImageBindView.as_view(),
        name="blog-note-image-bind",
    ),
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
