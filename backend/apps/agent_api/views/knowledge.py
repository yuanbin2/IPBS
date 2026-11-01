from pathlib import Path

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from ..exceptions import ErrorCode
from ..models import ApprovalRequest, Document, DocumentIngestionJob, KnowledgeBase, UserProfile
from ..serializers import serialize_document, serialize_knowledge_base
from ..services.ingestion_jobs import schedule_document_ingestion, uploaded_file_digest
from ..services.rag import EmbeddingSpaceError, get_default_knowledge_base, search_knowledge_base
from .common import approval_required_response, error_response, get_workspace_key, require_roles


def dispatch_ingestion_task(document: Document, *, force: bool = False):
    return schedule_document_ingestion(document, force=force)


def ingestion_response_payload(document: Document, job: DocumentIngestionJob) -> dict:
    """Expose durable outbox state; do not depend on ephemeral Celery results."""
    document.refresh_from_db()
    job.refresh_from_db()
    payload = {
        **serialize_document(document),
        "task_id": str(job.pk),
        "request_id": job.request_id,
        "ingestion_job": {
            "id": str(job.pk),
            "generation": job.generation,
            "status": job.status,
            "failure_code": job.failure_code or None,
            "attempts": job.attempts,
            "timings": job.timings,
        },
    }
    if job.status == DocumentIngestionJob.Status.COMPLETED:
        payload["task_state"] = "SUCCESS"
        payload["task_result"] = {
            "document_id": document.pk,
            "status": document.status,
            "chunk_count": document.chunk_count,
        }
    elif job.status == DocumentIngestionJob.Status.FAILED:
        payload["task_state"] = "FAILURE"
        payload["task_error"] = job.failure_code
    else:
        payload["task_url"] = f"/api/agent/tasks/{job.pk}/"
    return payload


class KnowledgeBaseListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        get_default_knowledge_base(get_workspace_key(request))
        knowledge_bases = KnowledgeBase.objects.filter(workspace_key=get_workspace_key(request))

        # 按分类筛选
        category = request.query_params.get("category")
        if category and category != "all":
            knowledge_bases = knowledge_bases.filter(category=category)

        # 按标签筛选
        tag = request.query_params.get("tag")
        if tag:
            knowledge_bases = knowledge_bases.filter(tags__contains=[tag])

        # 搜索
        search = request.query_params.get("search")
        if search:
            knowledge_bases = knowledge_bases.filter(Q(name__icontains=search) | Q(description__icontains=search))

        # 是否包含归档
        include_archived = request.query_params.get("include_archived", "false").lower() == "true"
        if not include_archived:
            knowledge_bases = knowledge_bases.filter(is_archived=False)

        return Response([serialize_knowledge_base(item) for item in knowledge_bases])

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        name = str(request.data.get("name", "")).strip()
        if not name:
            return error_response("name is required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)

        knowledge_base, created = KnowledgeBase.objects.get_or_create(
            name=name,
            workspace_key=get_workspace_key(request),
            defaults={
                "description": str(request.data.get("description", "")).strip(),
                "category": str(request.data.get("category", "other")).strip(),
                "tags": request.data.get("tags", []),
            },
        )
        if not created:
            knowledge_base.description = str(request.data.get("description", knowledge_base.description)).strip()
            if "category" in request.data:
                knowledge_base.category = str(request.data["category"]).strip()
            if "tags" in request.data:
                knowledge_base.tags = request.data["tags"]
            knowledge_base.save(update_fields=["description", "category", "tags", "updated_at"])
        return Response(
            serialize_knowledge_base(knowledge_base), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class KnowledgeBaseDetailView(APIView):
    authentication_classes = []
    permission_classes = []

    def patch(self, request, pk: int):
        """更新知识库信息（分类、标签、排序等）"""
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        knowledge_base = get_object_or_404(KnowledgeBase, pk=pk, workspace_key=get_workspace_key(request))

        if "name" in request.data:
            knowledge_base.name = str(request.data["name"]).strip()
        if "description" in request.data:
            knowledge_base.description = str(request.data["description"]).strip()
        if "category" in request.data:
            knowledge_base.category = str(request.data["category"]).strip()
        if "tags" in request.data:
            knowledge_base.tags = request.data["tags"]
        if "sort_order" in request.data:
            knowledge_base.sort_order = int(request.data["sort_order"])
        knowledge_base.save()
        return Response(serialize_knowledge_base(knowledge_base))

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
            requester=(
                str(request.data.get("requester", "operator")).strip() if hasattr(request, "data") else "operator"
            ),
        )
        return approval_required_response(approval)


class KnowledgeBaseArchiveView(APIView):
    """归档/取消归档知识库"""

    authentication_classes = []
    permission_classes = []

    def post(self, request, pk: int):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        knowledge_base = get_object_or_404(KnowledgeBase, pk=pk, workspace_key=get_workspace_key(request))
        action = str(request.data.get("action", "archive")).strip().lower()

        if action == "archive":
            knowledge_base.is_archived = True
            message = f"知识库 '{knowledge_base.name}' 已归档"
        elif action == "unarchive":
            knowledge_base.is_archived = False
            message = f"知识库 '{knowledge_base.name}' 已取消归档"
        else:
            return error_response(
                "action must be 'archive' or 'unarchive'", ErrorCode.VALIDATION_ERROR, status.HTTP_400_BAD_REQUEST
            )

        knowledge_base.save(update_fields=["is_archived", "updated_at"])
        return Response({"message": message, "knowledge_base": serialize_knowledge_base(knowledge_base)})


class DocumentListUploadView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
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
            return error_response("file is required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)

        suffix = Path(upload.name).suffix.lower()
        if suffix not in {".md", ".markdown", ".txt", ".pdf"}:
            return error_response(
                "only Markdown, txt and PDF files are supported",
                ErrorCode.VALIDATION_ERROR,
                status.HTTP_400_BAD_REQUEST,
            )

        # B052：target=ragagent 时转发到 rag-agent（blog 租户隔离知识库），
        # 不落本地 Document/摄入任务；失败返回 502 并带原因
        if str(request.data.get("target", "local")).strip().lower() == "ragagent":
            from ..services.rag_agent_client import RagAgentError, upload_document_to_rag_agent

            content_type = getattr(upload, "content_type", "") or suffix.lstrip(".")
            try:
                remote = upload_document_to_rag_agent(upload.name, upload.read(), content_type=content_type)
            except RagAgentError as exc:
                return error_response(
                    f"RAG-Agent 上传失败：{exc}",
                    ErrorCode.VALIDATION_ERROR,
                    status.HTTP_502_BAD_GATEWAY,
                )
            return Response(
                {
                    "target": "ragagent",
                    "document_id": remote.get("document_id"),
                    "filename": remote.get("filename"),
                    "status": remote.get("status"),
                    "task_state": "SUCCESS",
                    "task_url": "",
                },
                status=status.HTTP_202_ACCEPTED,
            )

        knowledge_base_id = request.data.get("knowledge_base_id")
        if knowledge_base_id:
            knowledge_base = get_object_or_404(
                KnowledgeBase, pk=knowledge_base_id, workspace_key=get_workspace_key(request)
            )
        else:
            knowledge_base = get_default_knowledge_base(get_workspace_key(request))

        title = str(request.data.get("title") or Path(upload.name).stem).strip()
        source_digest = uploaded_file_digest(upload)
        with transaction.atomic():
            document = Document.objects.create(
                knowledge_base=knowledge_base,
                workspace_key=get_workspace_key(request),
                title=title,
                source_file=upload,
                content_type=getattr(upload, "content_type", "") or suffix.lstrip("."),
            )
            job = schedule_document_ingestion(document, source_digest=source_digest)
        return Response(
            ingestion_response_payload(document, job),
            status=status.HTTP_202_ACCEPTED,
        )


class RagAgentDocumentListView(APIView):
    """RAG-Agent 外部知识库文档列表（只读展示）。

    fail-open 契约：rag-agent 不可达时返回 200 + available=false，
    前端据此展示"服务不可达"占位而不是报错炸页。
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        from ..services.rag_agent_client import RagAgentError, list_documents_from_rag_agent

        try:
            remote_documents = list_documents_from_rag_agent()
        except RagAgentError:
            return Response({"available": False, "error": "RAG-Agent 服务不可达（未启动或异常）", "documents": []})
        documents = [
            {
                "document_id": str(item.get("id") or item.get("document_id") or ""),
                "filename": str(item.get("filename") or ""),
                "status": str(item.get("status") or ""),
                "source": str(item.get("source") or ""),
            }
            for item in remote_documents
            if isinstance(item, dict)
        ]
        return Response({"available": True, "error": "", "documents": documents})


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
            requester=(
                str(request.data.get("requester", "operator")).strip() if hasattr(request, "data") else "operator"
            ),
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
        source_digest = None
        if document.source_file and not document.content_text.strip():
            from ..services.ingestion_jobs import document_file_digest

            source_digest = document_file_digest(document)
        with transaction.atomic():
            document.error_message = ""
            document.save(update_fields=["error_message", "updated_at"])
            job = schedule_document_ingestion(document, force=True, source_digest=source_digest)
        return Response(
            ingestion_response_payload(document, job),
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
        job = DocumentIngestionJob.objects.filter(
            pk=task_id, document__workspace_key=get_workspace_key(request)
        ).first()
        if job:
            payload = {
                "id": str(job.pk),
                "state": job.status,
                "ready": job.status
                in {
                    DocumentIngestionJob.Status.COMPLETED,
                    DocumentIngestionJob.Status.FAILED,
                    DocumentIngestionJob.Status.SUPERSEDED,
                },
                "failure_code": job.failure_code or None,
                "generation": job.generation,
                "request_id": job.request_id,
                "attempts": job.attempts,
                "timings": job.timings,
            }
            return Response(payload)
        # The durable job is authoritative. A deleted or foreign job must not fall
        # back to an unscoped Celery result that may still mention old content.
        raise Http404


class KnowledgeSearchView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        denied = require_roles(request, [UserProfile.Role.OPERATOR])
        if denied:
            return denied
        query = str(request.data.get("query", "")).strip()
        if not query:
            return error_response("query is required", ErrorCode.MISSING_FIELD, status.HTTP_400_BAD_REQUEST)

        knowledge_base_id = request.data.get("knowledge_base_id")
        if knowledge_base_id:
            get_object_or_404(KnowledgeBase, pk=knowledge_base_id, workspace_key=get_workspace_key(request))
        limit = request.data.get("limit", 5)
        try:
            limit = max(1, min(int(limit), 10))
        except (TypeError, ValueError):
            limit = 5

        try:
            results = search_knowledge_base(
                query,
                knowledge_base_id=int(knowledge_base_id) if knowledge_base_id else None,
                limit=limit,
                workspace_key=get_workspace_key(request),
            )
        except EmbeddingSpaceError:
            return Response(
                {"detail": "The configured embedding space is unavailable; retrieval did not switch models."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
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
