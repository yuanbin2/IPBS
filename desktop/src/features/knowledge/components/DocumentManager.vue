<script setup lang="ts">
import { Delete, Refresh, UploadFilled } from "@element-plus/icons-vue";
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

  <section class="document-table">
    <div class="section-heading">
      <h2>文档处理状态</h2>
      <el-button :icon="Refresh" @click="$emit('refresh')">刷新</el-button>
    </div>
    <table>
      <thead>
        <tr><th>标题</th><th>状态</th><th>片段</th><th>类型</th><th>操作</th></tr>
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
              :loading="reindexingId === document.id"
              @click="$emit('reindex', document)"
            >
              重新处理
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :icon="Delete"
              :loading="deletingId === document.id"
              @click="$emit('remove', document)"
            >
              删除
            </el-button>
          </td>
        </tr>
        <tr v-if="documents.length === 0"><td colspan="5">还没有上传文档</td></tr>
      </tbody>
    </table>
  </section>
</template>
