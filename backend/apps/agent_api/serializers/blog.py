from rest_framework import serializers

from ..models import (
    ArticleCategory, ArticleTag, BlogAgentMessage, BlogArticle, BlogComment,
)


class ArticleCategorySerializer(serializers.ModelSerializer):
    article_count = serializers.SerializerMethodField()

    class Meta:
        model = ArticleCategory
        fields = ["id", "name", "slug", "description", "article_count"]

    def get_article_count(self, instance):
        return instance.articles.filter(status=BlogArticle.Status.PUBLISHED).count()


class ArticleTagSerializer(serializers.ModelSerializer):
    article_count = serializers.SerializerMethodField()

    class Meta:
        model = ArticleTag
        fields = ["id", "name", "slug", "article_count"]

    def get_article_count(self, instance):
        return instance.articles.filter(status=BlogArticle.Status.PUBLISHED).count()


class BlogCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogComment
        fields = ["id", "author_name", "content", "created_at"]


class BlogArticleSerializer(serializers.ModelSerializer):
    category = ArticleCategorySerializer(read_only=True)
    tags = ArticleTagSerializer(many=True, read_only=True)
    knowledge_document_id = serializers.IntegerField(read_only=True, allow_null=True)
    comment_count = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()

    class Meta:
        model = BlogArticle
        fields = [
            "id", "title", "slug", "author_name", "summary", "status", "view_count", "category",
            "tags", "published_at", "created_at", "updated_at",
            "knowledge_document_id", "comment_count", "content", "comments",
        ]

    def get_comment_count(self, instance):
        return instance.comments.filter(is_approved=True).count()

    def get_comments(self, instance):
        return BlogCommentSerializer(
            instance.comments.filter(is_approved=True), many=True
        ).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("include_content"):
            data.pop("content", None)
            data.pop("comments", None)
        return data


class BlogAgentMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogAgentMessage
        fields = ["id", "role", "content", "sources", "trace", "token_usage", "created_at"]


def serialize_category(instance):
    return ArticleCategorySerializer(instance).data


def serialize_tag(instance):
    return ArticleTagSerializer(instance).data


def serialize_article(instance, include_content=False):
    return BlogArticleSerializer(instance, context={"include_content": include_content}).data


def serialize_blog_agent_message(instance):
    return BlogAgentMessageSerializer(instance).data
