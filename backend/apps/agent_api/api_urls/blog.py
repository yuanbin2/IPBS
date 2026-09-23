from django.urls import path

from ..views.blog import (
    BlogAboutView,
    BlogAgentChatView,
    BlogArchiveView,
    BlogArticleDetailView,
    BlogArticleListCreateView,
    BlogArticlePublishView,
    BlogArticleRelatedView,
    BlogCategoryListView,
    BlogCommentCreateView,
    BlogImageUploadView,
    BlogTagListView,
    BlogWritingAgentView,
)

urlpatterns = [
    path("blog/articles/", BlogArticleListCreateView.as_view(), name="blog-article-list-create"),
    path("blog/articles/<str:slug>/related/", BlogArticleRelatedView.as_view(), name="blog-article-related"),
    path("blog/articles/<str:slug>/", BlogArticleDetailView.as_view(), name="blog-article-detail"),
    path("blog/articles/<str:slug>/publish/", BlogArticlePublishView.as_view(), name="blog-article-publish"),
    path("blog/articles/<str:slug>/comments/", BlogCommentCreateView.as_view(), name="blog-comment-create"),
    path("blog/images/", BlogImageUploadView.as_view(), name="blog-image-upload"),
    path("blog/categories/", BlogCategoryListView.as_view(), name="blog-category-list"),
    path("blog/tags/", BlogTagListView.as_view(), name="blog-tag-list"),
    path("blog/archive/", BlogArchiveView.as_view(), name="blog-archive"),
    path("blog/about/", BlogAboutView.as_view(), name="blog-about"),
    path("blog/agent/chat/", BlogAgentChatView.as_view(), name="blog-agent-chat"),
    path("blog/writing-agent/generate/", BlogWritingAgentView.as_view(), name="blog-writing-agent-generate"),
]
