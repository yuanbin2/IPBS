"""Celery 后台任务：把耗时的文档解析和向量化移出 HTTP 请求。"""

from celery import shared_task

from .models import Document
from .services.rag import ingest_document


@shared_task(
    bind=True,
    autoretry_for=(OSError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def ingest_document_task(self, document_id: int) -> dict:
    """Parse, chunk and embed a document outside the HTTP request process."""
    # 任务只传主键，不传 Django 模型或文件对象，确保消息可序列化，
    # Worker 也总能读取数据库中的最新状态。
    document = Document.objects.get(pk=document_id)
    document = ingest_document(document)
    if document.status == Document.Status.FAILED:
        raise RuntimeError(document.error_message or "document ingestion failed")
    return {
        "document_id": document.id,
        "status": document.status,
        "chunk_count": document.chunk_count,
    }
