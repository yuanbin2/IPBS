<script setup lang="ts">
import { computed } from "vue";
import { Delete, Document, Refresh, UploadFilled } from "@element-plus/icons-vue";
import type { KnowledgeDocument, RagAgentDocument } from "../types";

const props = defineProps<{
  documents: KnowledgeDocument[];
  ragAgentDocuments: RagAgentDocument[];
  ragAgentAvailable: boolean;
  ragAgentError: string;
  activeListSource: "local" | "ragagent";
  uploadTitle: string;
  uploadTarget: "local" | "ragagent";
  hasFile: boolean;
  uploading: boolean;
  uploadProgress: number;
  uploadStage: "idle" | "uploading" | "processing";
  reindexingId: number | null;
  deletingId: number | null;
}>();

const emit = defineEmits<{
  "update:uploadTitle": [value: string];
  "update:uploadTarget": [value: "local" | "ragagent"];
  "update:activeListSource": [value: "local" | "ragagent"];
  fileChange: [event: Event];
  upload: [];
  refresh: [];
  reindex: [document: KnowledgeDocument];
  remove: [document: KnowledgeDocument];
}>();

const uploadTargetProxy = computed({
  get: () => props.uploadTarget,
  set: (value: "local" | "ragagent") => emit("update:uploadTarget", value),
});

const activeListSourceProxy = computed({
  get: () => props.activeListSource,
  set: (value: "local" | "ragagent") => emit("update:activeListSource", value),
});

function getStatusIcon(status: string) {
  switch (status) {
    case "ready":
      return "✓";
    case "processing":
      return "⏳";
    case "failed":
      return "✗";
    default:
      return "○";
  }
}

function ragStatusText(status: string) {
  return status || "unknown";
}
</script>

<template>
  <section class="upload-zone">
    <div>
      <h2><el-icon><UploadFilled /></el-icon> 上传文档</h2>
      <p>支持 Markdown、txt、PDF。上传后会自动抽取文本、切分片段并写入 embedding 记录。</p>
      <div class="upload-target-toggle">
        <label><input type="radio" value="local" v-model="uploadTargetProxy" /> 博客知识库（站内）</label>
        <label><input type="radio" value="ragagent" v-model="uploadTargetProxy" /> RAG-Agent（隔离知识库）</label>
      </div>
    </div>
    <div class="upload-controls">
      <label class="upload-dropzone">
        <input type="file" accept=".md,.markdown,.txt,.pdf" @change="$emit('fileChange', $event)" />
        <span>点击选择 Markdown / txt / PDF 文件</span>
      </label>
      <el-input
        :model-value="uploadTitle"
        placeholder="文档标题"
        @update:model-value="$emit('update:uploadTitle', String($event))"
      />
      <el-button type="primary" :loading="uploading" :disabled="!hasFile" @click="$emit('upload')">
        上传并处理
      </el-button>
      <div v-if="uploading || uploadProgress > 0" class="upload-progress">
        <el-progress
          :percentage="uploadProgress"
          :status="uploadProgress >= 100 ? 'success' : undefined"
          :stroke-width="8"
        />
        <span>{{ uploadStage === "processing" ? "文件已上传，正在写入知识库" : "正在上传文件" }}</span>
      </div>
    </div>
  </section>

  <section class="document-grid-section">
    <div class="section-heading">
      <h2><el-icon><Document /></el-icon> 文档列表</h2>
      <el-button :icon="Refresh" @click="$emit('refresh')">刷新</el-button>
    </div>

    <div class="list-source-toggle" role="tablist" aria-label="文档列表来源">
      <button
        type="button"
        class="list-source-tab"
        :class="{ active: activeListSourceProxy === 'local' }"
        role="tab"
        :aria-selected="activeListSourceProxy === 'local'"
        @click="activeListSourceProxy = 'local'"
      >
        博客知识库
      </button>
      <button
        type="button"
        class="list-source-tab"
        :class="{ active: activeListSourceProxy === 'ragagent' }"
        role="tab"
        :aria-selected="activeListSourceProxy === 'ragagent'"
        @click="activeListSourceProxy = 'ragagent'"
      >
        RAG-Agent
      </button>
    </div>

    <template v-if="activeListSourceProxy === 'local'">
    <div class="document-grid">
      <article v-for="doc in documents" :key="doc.id" class="document-card">
        <div class="doc-status-icon" :class="doc.status">
          {{ getStatusIcon(doc.status) }}
        </div>
        <div class="doc-info">
          <h3>{{ doc.title }}</h3>
          <div class="doc-meta">
            <span class="doc-type">{{ doc.content_type || "未知类型" }}</span>
            <span class="doc-chunks">{{ doc.chunk_count }} 片段</span>
          </div>
          <p v-if="doc.ingestion_error_code" class="doc-error" role="status">
            处理未完成（{{ doc.ingestion_error_code }}），可重新处理。
          </p>
        </div>
        <div class="doc-actions">
          <el-button
            size="small"
            :loading="reindexingId === doc.id"
            @click="$emit('reindex', doc)"
          >
            重新处理
          </el-button>
          <el-button
            size="small"
            type="danger"
            plain
            :icon="Delete"
            :loading="deletingId === doc.id"
            @click="$emit('remove', doc)"
          >
            删除
          </el-button>
        </div>
      </article>

      <div v-if="documents.length === 0" class="doc-empty">
        <el-icon><Document /></el-icon>
        <span>还没有上传文档</span>
      </div>
    </div>
    </template>

    <template v-else>
      <div class="document-grid ragagent-grid">
        <article v-for="doc in ragAgentDocuments" :key="doc.document_id" class="document-card ragagent-card">
          <div class="doc-status-icon processing">{{ getStatusIcon(ragStatusText(doc.status)) }}</div>
          <div class="doc-info">
            <h3>{{ doc.filename }}</h3>
            <div class="doc-meta">
              <span class="doc-type">状态：{{ ragStatusText(doc.status) }}</span>
              <span class="doc-chunks">来源：{{ doc.source || "rag-agent" }}</span>
            </div>
            <p class="doc-meta">文档 ID：{{ doc.document_id }}</p>
          </div>
        </article>

        <div v-if="ragAgentDocuments.length === 0" class="doc-empty">
          <el-icon><Document /></el-icon>
          <span>{{ ragAgentAvailable ? "RAG-Agent 知识库暂无文档" : "RAG-Agent 服务不可达（未启动或异常）" }}</span>
        </div>
      </div>
      <p v-if="!ragAgentAvailable && ragAgentError" class="ragagent-error" role="status">{{ ragAgentError }}</p>
    </template>
  </section>
</template>

<style scoped>
.list-source-toggle {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.list-source-tab {
  padding: 6px 16px;
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-radius: 6px;
  background: transparent;
  color: var(--el-text-color-regular, #606266);
  cursor: pointer;
  font-size: 13px;
}

.list-source-tab.active {
  background: var(--el-color-primary, #409eff);
  border-color: var(--el-color-primary, #409eff);
  color: #fff;
}

.ragagent-error {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--el-color-danger, #f56c6c);
}
</style>
