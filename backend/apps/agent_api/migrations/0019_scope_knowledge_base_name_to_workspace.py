from django.db import migrations, models


DEFAULT_KNOWLEDGE_BASE_NAME = "默认知识库"
DEFAULT_DESCRIPTION = "Day4 本地知识库，用于上传文档、切分、向量检索和 Agent RAG。"


def repair_document_workspace_knowledge_bases(apps, schema_editor):
    KnowledgeBase = apps.get_model("agent_api", "KnowledgeBase")
    Document = apps.get_model("agent_api", "Document")
    DocumentChunk = apps.get_model("agent_api", "DocumentChunk")

    mismatched_documents = Document.objects.select_related("knowledge_base").exclude(
        workspace_key=models.F("knowledge_base__workspace_key")
    )
    for document in mismatched_documents:
        target_base, _ = KnowledgeBase.objects.get_or_create(
            name=DEFAULT_KNOWLEDGE_BASE_NAME,
            workspace_key=document.workspace_key,
            defaults={"description": DEFAULT_DESCRIPTION},
        )
        document.knowledge_base_id = target_base.id
        document.save(update_fields=["knowledge_base"])
        DocumentChunk.objects.filter(document_id=document.id).update(knowledge_base_id=target_base.id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("agent_api", "0018_correct_system_tech_stack")]

    operations = [
        migrations.AlterField(
            model_name="knowledgebase",
            name="name",
            field=models.CharField(max_length=120),
        ),
        migrations.RunPython(repair_document_workspace_knowledge_bases, noop_reverse),
        migrations.AddConstraint(
            model_name="knowledgebase",
            constraint=models.UniqueConstraint(
                fields=("workspace_key", "name"),
                name="unique_knowledge_base_per_workspace",
            ),
        ),
    ]
