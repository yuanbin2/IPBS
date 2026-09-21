import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { KnowledgeBase, KnowledgeDocument, SearchResult } from "../types";

async function readPayload(response: Response) {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  if ((response.headers.get("content-type") ?? "").includes("application/json")) {
    return JSON.parse(text);
  }
  return null;
}

async function errorMessage(response: Response, fallback: string) {
  const text = await response.text();
  if ((response.headers.get("content-type") ?? "").includes("application/json") && text) {
    try {
      return JSON.parse(text).detail ?? fallback;
    } catch {
      return fallback;
    }
  }
  return text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 220) || fallback;
}

export function useKnowledgeBase() {
  const knowledgeBases = ref<KnowledgeBase[]>([]);
  const documents = ref<KnowledgeDocument[]>([]);
  const selectedKnowledgeBaseId = ref<number | null>(null);
  const uploadFile = ref<File | null>(null);
  const uploadTitle = ref("");
  const searchQuery = ref("RAG 如何结合 LangGraph");
  const searchResults = ref<SearchResult[]>([]);
  const loading = ref(false);
  const uploading = ref(false);
  const uploadProgress = ref(0);
  const uploadStage = ref<"idle" | "uploading" | "processing">("idle");
  const searching = ref(false);
  const reindexingDocumentId = ref<number | null>(null);
  const deletingKnowledgeBaseId = ref<number | null>(null);
  const deletingDocumentId = ref<number | null>(null);
  const activeTaskUrls = new Set<string>();

  async function loadKnowledgeBases() {
    loading.value = true;
    try {
      const response = await fetch("/api/agent/knowledge-bases/");
      knowledgeBases.value = await response.json();
      if (!selectedKnowledgeBaseId.value && knowledgeBases.value.length) {
        selectedKnowledgeBaseId.value = knowledgeBases.value[0].id;
      }
    } finally {
      loading.value = false;
    }
  }

  async function loadDocuments() {
    const params = new URLSearchParams();
    if (selectedKnowledgeBaseId.value) {
      params.set("knowledge_base_id", String(selectedKnowledgeBaseId.value));
    }
    const query = params.toString();
    const response = await fetch(`/api/agent/documents/${query ? `?${query}` : ""}`);
    documents.value = await response.json();
  }

  async function selectKnowledgeBase(id: number) {
    selectedKnowledgeBaseId.value = id;
    await loadDocuments();
  }

  function handleFileChange(event: Event) {
    const input = event.target as HTMLInputElement;
    uploadFile.value = input.files?.[0] ?? null;
    if (uploadFile.value && !uploadTitle.value) {
      uploadTitle.value = uploadFile.value.name.replace(/\.[^.]+$/, "");
    }
  }

  async function waitForTask(taskUrl: string) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const response = await fetch(taskUrl);
      const task = await response.json();
      if (!response.ok) throw new Error(task.detail ?? "无法读取后台任务状态");
      if (task.state === "SUCCESS") return task.result;
      if (task.state === "FAILURE") throw new Error(task.error ?? "后台任务执行失败");
      if (attempt > 0 && attempt % 5 === 0) {
        await loadDocuments();
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
    throw new Error("后台任务仍在运行，请稍后刷新文档列表");
  }

  function trackTask(taskUrl: string, successMessage: string, failureFallback: string) {
    if (activeTaskUrls.has(taskUrl)) return;
    activeTaskUrls.add(taskUrl);
    void (async () => {
      try {
        await waitForTask(taskUrl);
        await Promise.all([loadKnowledgeBases(), loadDocuments()]);
        ElMessage.success(successMessage);
      } catch (error) {
        await loadDocuments();
        ElMessage.error(error instanceof Error ? error.message : failureFallback);
      } finally {
        activeTaskUrls.delete(taskUrl);
      }
    })();
  }

  function uploadFormData(url: string, form: FormData): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", url);
      const token = localStorage.getItem("agent_auth_token");
      if (token) {
        request.setRequestHeader("Authorization", `Bearer ${token}`);
      }
      request.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        uploadProgress.value = Math.min(95, Math.round((event.loaded / event.total) * 100));
      };
      request.onload = () => {
        const contentType = request.getResponseHeader("content-type") ?? "";
        const text = request.responseText;
        const payload = contentType.includes("application/json") && text ? JSON.parse(text) : text;
        if (request.status >= 200 && request.status < 300) {
          resolve(payload);
          return;
        }
        const detail = typeof payload === "object" && payload && "detail" in payload
          ? String((payload as { detail: unknown }).detail)
          : text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 220);
        reject(new Error(detail || "上传失败"));
      };
      request.onerror = () => reject(new Error("上传失败，请检查网络或后端服务"));
      request.onabort = () => reject(new Error("上传已取消"));
      request.send(form);
    });
  }

  async function uploadDocument() {
    if (!uploadFile.value) return;
    uploading.value = true;
    uploadProgress.value = 0;
    uploadStage.value = "uploading";
    try {
      const form = new FormData();
      form.append("file", uploadFile.value);
      form.append("title", uploadTitle.value || uploadFile.value.name);
      if (selectedKnowledgeBaseId.value) {
        form.append("knowledge_base_id", String(selectedKnowledgeBaseId.value));
      }
      const payload = await uploadFormData("/api/agent/documents/", form) as {
        task_state?: string;
        task_error?: string;
        task_url?: string;
      };
      uploadProgress.value = Math.max(uploadProgress.value, 95);
      uploadStage.value = "processing";
      if (payload.task_state === "FAILURE") {
        throw new Error(payload.task_error ?? "文档处理失败");
      }
      uploadFile.value = null;
      uploadTitle.value = "";
      await Promise.all([loadKnowledgeBases(), loadDocuments()]);
      if (payload.task_url) {
        trackTask(payload.task_url, "文档处理完成", "文档处理失败");
        ElMessage.success("文件已上传，正在后台处理");
      } else {
        uploadProgress.value = 100;
        ElMessage.success("文档处理完成");
      }
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "上传失败");
    } finally {
      uploading.value = false;
      window.setTimeout(() => {
        uploadProgress.value = 0;
        uploadStage.value = "idle";
      }, 900);
    }
  }

  async function searchKnowledge() {
    if (!searchQuery.value.trim()) return;
    searching.value = true;
    try {
      const response = await fetch("/api/agent/knowledge-search/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: searchQuery.value,
          knowledge_base_id: selectedKnowledgeBaseId.value,
          limit: 5
        })
      });
      searchResults.value = await response.json();
    } finally {
      searching.value = false;
    }
  }

  async function reindexDocument(document: KnowledgeDocument) {
    reindexingDocumentId.value = document.id;
    try {
      const response = await fetch(`/api/agent/documents/${document.id}/reindex/`, { method: "POST" });
      if (!response.ok) throw new Error(await errorMessage(response, "重新处理失败"));
      const payload = await response.json();
      if (payload.task_state === "FAILURE") {
        throw new Error(payload.task_error ?? "文档重新处理失败");
      }
      await Promise.all([loadKnowledgeBases(), loadDocuments()]);
      if (payload.task_url) {
        trackTask(payload.task_url, "文档重新处理完成", "文档重新处理失败");
        ElMessage.success("重新处理已提交，正在后台执行");
      } else {
        ElMessage.success("文档重新处理完成");
      }
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "重新处理失败");
    } finally {
      reindexingDocumentId.value = null;
    }
  }

  async function deleteKnowledgeBase(base: KnowledgeBase) {
    try {
      await ElMessageBox.confirm(
        `确定删除知识库“${base.name}”吗？里面的文档、切片和向量索引也会一起删除。`,
        "删除知识库",
        { confirmButtonText: "删除", cancelButtonText: "取消", type: "warning" }
      );
    } catch {
      return;
    }
    deletingKnowledgeBaseId.value = base.id;
    try {
      const response = await fetch(`/api/agent/knowledge-bases/${base.id}/`, { method: "DELETE" });
      if (!response.ok) throw new Error(await errorMessage(response, "删除知识库失败"));
      const payload = await readPayload(response);
      if (payload?.approval_required) {
        ElMessage.warning(`已提交审批 #${payload.approval.id}，批准后才会删除知识库`);
      } else {
        if (selectedKnowledgeBaseId.value === base.id) selectedKnowledgeBaseId.value = null;
        ElMessage.success("知识库已删除");
      }
      await loadKnowledgeBases();
      await loadDocuments();
      searchResults.value = [];
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "删除知识库失败");
    } finally {
      deletingKnowledgeBaseId.value = null;
    }
  }

  async function deleteDocument(document: KnowledgeDocument) {
    try {
      await ElMessageBox.confirm(
        `确定删除文档“${document.title}”吗？它的切片和向量索引也会删除。`,
        "删除文档",
        { confirmButtonText: "删除", cancelButtonText: "取消", type: "warning" }
      );
    } catch {
      return;
    }
    deletingDocumentId.value = document.id;
    try {
      const response = await fetch(`/api/agent/documents/${document.id}/`, { method: "DELETE" });
      if (!response.ok) throw new Error(await errorMessage(response, "删除文档失败"));
      const payload = await readPayload(response);
      await Promise.all([loadKnowledgeBases(), loadDocuments()]);
      if (payload?.approval_required) {
        ElMessage.warning(`已提交审批 #${payload.approval.id}，批准后才会删除文档`);
      } else {
        searchResults.value = searchResults.value.filter((item) => item.document_id !== document.id);
        ElMessage.success("文档已删除");
      }
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "删除文档失败");
    } finally {
      deletingDocumentId.value = null;
    }
  }

  onMounted(async () => {
    await loadKnowledgeBases();
    await loadDocuments();
  });

  return {
    knowledgeBases, documents, selectedKnowledgeBaseId, uploadFile, uploadTitle,
    searchQuery, searchResults, loading, uploading, uploadProgress, uploadStage, searching,
    reindexingDocumentId, deletingKnowledgeBaseId, deletingDocumentId,
    loadKnowledgeBases, loadDocuments, selectKnowledgeBase, handleFileChange,
    uploadDocument, searchKnowledge, reindexDocument, deleteKnowledgeBase, deleteDocument
  };
}

