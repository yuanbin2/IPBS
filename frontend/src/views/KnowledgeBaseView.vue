<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Back, Files, Refresh, Search, UploadFilled } from "@element-plus/icons-vue";
import { RouterLink } from "vue-router";

interface KnowledgeBase {
  id: number;
  name: string;
  description: string;
  document_count: number;
  chunk_count: number;
}

interface KnowledgeDocument {
  id: number;
  knowledge_base_id: number;
  title: string;
  content_type: string;
  status: "pending" | "processing" | "ready" | "failed";
  error_message: string;
  chunk_count: number;
  created_at: string;
}

interface SearchResult {
  document_id: number;
  document_title: string;
  chunk_id: number;
  chunk_index: number;
  content: string;
  score: number;
}

const knowledgeBases = ref<KnowledgeBase[]>([]);
const documents = ref<KnowledgeDocument[]>([]);
const selectedKnowledgeBaseId = ref<number | null>(null);
const uploadFile = ref<File | null>(null);
const uploadTitle = ref("");
const searchQuery = ref("RAG 如何结合 LangGraph");
const searchResults = ref<SearchResult[]>([]);
const loading = ref(false);
const uploading = ref(false);
const searching = ref(false);
const reindexingDocumentId = ref<number | null>(null);

onMounted(async () => {
  await loadKnowledgeBases();
  await loadDocuments();
});

async function loadKnowledgeBases() {
  loading.value = true;
  try {
    const response = await fetch("/api/agent/knowledge-bases/");
    knowledgeBases.value = await response.json();
    if (!selectedKnowledgeBaseId.value && knowledgeBases.value.length > 0) {
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
  const response = await fetch(`/api/agent/documents/${params.toString() ? `?${params.toString()}` : ""}`);
  documents.value = await response.json();
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  uploadFile.value = input.files?.[0] ?? null;
  if (uploadFile.value && !uploadTitle.value) {
    uploadTitle.value = uploadFile.value.name.replace(/\.[^.]+$/, "");
  }
}

async function uploadDocument() {
  if (!uploadFile.value) return;
  uploading.value = true;
  try {
    const form = new FormData();
    form.append("file", uploadFile.value);
    form.append("title", uploadTitle.value || uploadFile.value.name);
    if (selectedKnowledgeBaseId.value) {
      form.append("knowledge_base_id", String(selectedKnowledgeBaseId.value));
    }

    const response = await fetch("/api/agent/documents/", {
      method: "POST",
      body: form
    });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail ?? "上传失败");
    }
    uploadFile.value = null;
    uploadTitle.value = "";
    await loadKnowledgeBases();
    await loadDocuments();
  } finally {
    uploading.value = false;
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
    const response = await fetch(`/api/agent/documents/${document.id}/reindex/`, {
      method: "POST"
    });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail ?? "重新处理失败");
    }
    await loadKnowledgeBases();
    await loadDocuments();
  } finally {
    reindexingDocumentId.value = null;
  }
}
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Knowledge Agent</div>
      <nav class="nav">
        <RouterLink to="/">概览</RouterLink>
        <a>博客</a>
        <RouterLink class="active" to="/knowledge">知识库</RouterLink>
        <RouterLink to="/chat">对话</RouterLink>
        <a>评估</a>
      </nav>
    </aside>

    <section class="workspace knowledge-workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">Day 4 RAG + Vector Search</p>
          <h1>知识库与文档检索</h1>
        </div>
        <RouterLink to="/chat">
          <el-button :icon="Back">回到对话</el-button>
        </RouterLink>
      </header>

      <section class="knowledge-layout">
        <aside class="knowledge-panel">
          <div class="panel-actions">
            <h2><el-icon><Files /></el-icon> 知识库</h2>
            <el-button :icon="Refresh" circle :loading="loading" @click="loadKnowledgeBases" />
          </div>

          <button
            v-for="base in knowledgeBases"
            :key="base.id"
            type="button"
            class="knowledge-base-button"
            :class="{ active: base.id === selectedKnowledgeBaseId }"
            @click="selectedKnowledgeBaseId = base.id; loadDocuments()"
          >
            <strong>{{ base.name }}</strong>
            <span>{{ base.document_count }} 个文档 / {{ base.chunk_count }} 个片段</span>
          </button>
        </aside>

        <section class="knowledge-main">
          <section class="upload-zone">
            <div>
              <h2><el-icon><UploadFilled /></el-icon> 上传文档</h2>
              <p>支持 Markdown、txt、PDF。上传后会自动抽取文本、切分片段并写入 embedding 记录。</p>
            </div>
            <div class="upload-controls">
              <input type="file" accept=".md,.markdown,.txt,.pdf" @change="handleFileChange" />
              <el-input v-model="uploadTitle" placeholder="文档标题" />
              <el-button type="primary" :loading="uploading" :disabled="!uploadFile" @click="uploadDocument">
                上传并处理
              </el-button>
            </div>
          </section>

          <section class="document-table">
            <div class="section-heading">
              <h2>文档处理状态</h2>
              <el-button :icon="Refresh" @click="loadDocuments">刷新</el-button>
            </div>
            <table>
              <thead>
                <tr>
                  <th>标题</th>
                  <th>状态</th>
                  <th>片段</th>
                  <th>类型</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="document in documents" :key="document.id">
                  <td>{{ document.title }}</td>
                  <td><span class="status-pill" :class="document.status">{{ document.status }}</span></td>
                  <td>{{ document.chunk_count }}</td>
                  <td>{{ document.content_type || "-" }}</td>
                  <td>
                    <el-button
                      size="small"
                      :loading="reindexingDocumentId === document.id"
                      @click="reindexDocument(document)"
                    >
                      重新处理
                    </el-button>
                  </td>
                </tr>
                <tr v-if="documents.length === 0">
                  <td colspan="5">还没有上传文档</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section class="search-lab">
            <div class="section-heading">
              <h2><el-icon><Search /></el-icon> 检索测试</h2>
              <el-button type="primary" :loading="searching" @click="searchKnowledge">检索</el-button>
            </div>
            <el-input v-model="searchQuery" placeholder="输入要检索的问题" @keyup.enter="searchKnowledge" />
            <article v-for="result in searchResults" :key="result.chunk_id" class="search-result">
              <header>
                <strong>{{ result.document_title }}</strong>
                <span>score {{ result.score.toFixed(3) }}</span>
              </header>
              <p>{{ result.content }}</p>
            </article>
          </section>
        </section>
      </section>
    </section>
  </main>
</template>
