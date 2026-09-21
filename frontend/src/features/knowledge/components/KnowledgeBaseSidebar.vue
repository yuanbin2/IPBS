<script setup lang="ts">
import { Delete, Files, Refresh } from "@element-plus/icons-vue";
import type { KnowledgeBase } from "../types";

defineProps<{
  items: KnowledgeBase[];
  selectedId: number | null;
  loading: boolean;
  deletingId: number | null;
}>();

defineEmits<{
  select: [id: number];
  refresh: [];
  remove: [item: KnowledgeBase];
}>();
</script>

<template>
  <aside class="knowledge-panel">
    <div class="panel-actions">
      <h2><el-icon><Files /></el-icon> 知识库</h2>
      <el-button :icon="Refresh" circle :loading="loading" @click="$emit('refresh')" />
    </div>

    <div
      v-for="item in items"
      :key="item.id"
      class="knowledge-base-row"
      :class="{ active: item.id === selectedId }"
    >
      <button type="button" class="knowledge-base-button" @click="$emit('select', item.id)">
        <strong>{{ item.name }}</strong>
        <span>{{ item.document_count }} 个文档 / {{ item.chunk_count }} 个片段</span>
      </button>
      <el-button
        :icon="Delete"
        circle
        plain
        type="danger"
        :loading="deletingId === item.id"
        @click="$emit('remove', item)"
      />
    </div>
  </aside>
</template>
