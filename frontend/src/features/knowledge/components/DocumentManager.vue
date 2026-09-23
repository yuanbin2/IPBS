<script setup lang="ts">
import { Delete, Document, Refresh, UploadFilled } from "@element-plus/icons-vue";
import type { KnowledgeDocument } from "../types";

defineProps<{
  documents: KnowledgeDocument[];
  uploadTitle: string;
  hasFile: boolean;
  uploading: boolean;
  uploadProgress: number;
  uploadStage: "idle" | "uploading" | "processing";
  reindexingId: number | null;
  deletingId: number | null;
}>();

defineEmits<{
  "update:uploadTitle": [value: string];
  fileChange: [event: Event];
  upload: [];
  refresh: [];
  reindex: [document: KnowledgeDocument];
  remove: [document: KnowledgeDocument];
}>();

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
</script>

<template>
  <section class="upload-zone">
    <div>
      <h2><el-icon><UploadFilled /></el-icon> 上传文档</h2>
      <p>支持 Markdown、txt、PDF。上传后会自动抽取文本、切分片段并写入 embedding 记录。</p>
    </div>
    <div class="upload-controls">
      <input type="file" accept=".md,.markdown,.txt,.pdf" @change="$emit('fileChange', $event)" />
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
  </section>
</template>