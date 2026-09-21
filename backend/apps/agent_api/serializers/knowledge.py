from rest_framework import serializers

from ..models import Document, KnowledgeBase


class KnowledgeBaseSerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(source="documents.count", read_only=True)
    chunk_count = serializers.IntegerField(source="chunks.count", read_only=True)

    class Meta:
        model = KnowledgeBase
        fields = [
            "id", "name", "description", "document_count", "chunk_count",
            "created_at", "updated_at",
        ]


class DocumentSerializer(serializers.ModelSerializer):
    knowledge_base_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Document
        fields = [
            "id", "knowledge_base_id", "title", "content_type", "status",
            "error_message", "chunk_count", "created_at", "updated_at",
        ]


def serialize_knowledge_base(instance):
    return KnowledgeBaseSerializer(instance).data


def serialize_document(instance):
    return DocumentSerializer(instance).data
