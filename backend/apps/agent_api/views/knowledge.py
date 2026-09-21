from .common import *


def dispatch_ingestion_task(document: Document):
    if settings.DEBUG or settings.CELERY_TASK_ALWAYS_EAGER:
        return ingest_document_task.apply(args=(document.id,)), True

    return ingest_document_task.delay(document.id), False


def ingestion_response_payload(document: Document, task, completed_synchronously: bool = False) -> dict:
    """Return a polling URL in production and the final result in local mode."""
    payload = {**serialize_document(document), "task_id": task.id}
    if settings.CELERY_TASK_ALWAYS_EAGER or completed_synchronously:
        payload["task_state"] = task.state
        if task.successful():
            payload["task_result"] = task.result
        elif task.failed():
            payload["task_error"] = str(task.result)
    else:
        payload["task_url"] = f"/api/agent/tasks/{task.id}/"
    return payload


class KnowledgeBaseListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        get_default_knowledge_base(get_workspace_key(request))
        knowledge_bases = KnowledgeBase.objects.filter(workspace_key=get_workspace_key(request))
        return Response([serialize_knowledge_base(item) for item in knowledge_bases])

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"detail": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

        knowledge_base, created = KnowledgeBase.objects.get_or_create(
            name=name,
            workspace_key=get_workspace_key(request),
            defaults={
                "description": str(request.data.get("description", "")).strip(),
            },
        )
        if not created:
            knowledge_base.description = str(request.data.get("description", knowledge_base.description)).strip()
            knowledge_base.save(update_fields=["description", "updated_at"])
        return Response(serialize_knowledge_base(knowledge_base), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class KnowledgeBaseDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def delete(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        knowledge_base = get_object_or_404(KnowledgeBase, pk=pk, workspace_key=get_workspace_key(request))
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.DELETE_KNOWLEDGE_BASE,
            workspace_key=get_workspace_key(request),
            title=f"删除知识库：{knowledge_base.name}",
            description="删除知识库会级联删除其中的文档、切片和向量索引。",
            payload={"knowledge_base_id": knowledge_base.id, "name": knowledge_base.name},
            requester=str(request.data.get("requester", "operator")).strip() if hasattr(request, "data") else "operator",
        )
        return approval_required_response(approval)


class DocumentListUploadView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        knowledge_base_id = request.query_params.get("knowledge_base_id")
        documents = Document.objects.select_related("knowledge_base").filter(workspace_key=get_workspace_key(request))
        if knowledge_base_id:
            documents = documents.filter(knowledge_base_id=knowledge_base_id)
        return Response([serialize_document(document) for document in documents[:50]])

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "file is required"}, status=status.HTTP_400_BAD_REQUEST)

        suffix = Path(upload.name).suffix.lower()
        if suffix not in {".md", ".markdown", ".txt", ".pdf"}:
            return Response(
                {"detail": "only Markdown, txt and PDF files are supported"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        knowledge_base_id = request.data.get("knowledge_base_id")
        if knowledge_base_id:
            knowledge_base = get_object_or_404(KnowledgeBase, pk=knowledge_base_id, workspace_key=get_workspace_key(request))
        else:
            knowledge_base = get_default_knowledge_base(get_workspace_key(request))

        title = str(request.data.get("title") or Path(upload.name).stem).strip()
        document = Document.objects.create(
            knowledge_base=knowledge_base,
            workspace_key=get_workspace_key(request),
            title=title,
            source_file=upload,
            content_type=getattr(upload, "content_type", "") or suffix.lstrip("."),
        )
        task, completed_synchronously = dispatch_ingestion_task(document)
        return Response(
            ingestion_response_payload(document, task, completed_synchronously),
            status=status.HTTP_202_ACCEPTED,
        )


class DocumentDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def delete(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.ADMIN])
        if denied:
            return denied
        document = get_object_or_404(Document, pk=pk, workspace_key=get_workspace_key(request))
        approval = ApprovalRequest.objects.create(
            action=ApprovalRequest.Action.DELETE_DOCUMENT,
            workspace_key=get_workspace_key(request),
            title=f"删除文档：{document.title}",
            description="删除文档会删除对应切片、embedding 记录，并影响知识库检索结果。",
            payload={"document_id": document.id, "title": document.title},
            requester=str(request.data.get("requester", "operator")).strip() if hasattr(request, "data") else "operator",
        )
        return approval_required_response(approval)


class DocumentReindexView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        document = get_object_or_404(Document, pk=pk, workspace_key=get_workspace_key(request))
        document.status = Document.Status.PENDING
        document.error_message = ""
        document.save(update_fields=["status", "error_message", "updated_at"])
        task, completed_synchronously = dispatch_ingestion_task(document)
        return Response(
            ingestion_response_payload(document, task, completed_synchronously),
            status=status.HTTP_202_ACCEPTED,
        )


class TaskStatusView(APIView):
    """Expose a Celery task as a polling-friendly REST resource."""
    authentication_classes = []
    permission_classes = []

    def get(self, request, task_id: str):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        task = AsyncResult(task_id)
        payload = {"id": task.id, "state": task.state, "ready": task.ready()}
        if task.successful():
            payload["result"] = task.result
        elif task.failed():
            payload["error"] = str(task.result)
        return Response(payload)


class KnowledgeSearchView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        query = str(request.data.get("query", "")).strip()
        if not query:
            return Response({"detail": "query is required"}, status=status.HTTP_400_BAD_REQUEST)

        knowledge_base_id = request.data.get("knowledge_base_id")
        if knowledge_base_id:
            get_object_or_404(KnowledgeBase, pk=knowledge_base_id, workspace_key=get_workspace_key(request))
        limit = request.data.get("limit", 5)
        try:
            limit = max(1, min(int(limit), 10))
        except (TypeError, ValueError):
            limit = 5

        results = search_knowledge_base(
            query,
            knowledge_base_id=int(knowledge_base_id) if knowledge_base_id else None,
            limit=limit,
            workspace_key=get_workspace_key(request),
        )
        return Response(
            [
                {
                    "document_id": item.document_id,
                    "document_title": item.document_title,
                    "chunk_id": item.chunk_id,
                    "chunk_index": item.chunk_index,
                    "content": item.content,
                    "score": item.score,
                }
                for item in results
            ]
        )
