<script setup lang="ts">
import { Search } from "@element-plus/icons-vue";
import type { SearchResult } from "../types";
import PageFeedback from "../../../components/PageFeedback.vue";

defineProps<{ query: string; results: SearchResult[]; searching: boolean; error: string; hasSearched: boolean }>();
defineEmits<{ "update:query": [value: string]; search: [] }>();
</script>

<template>
  <section class="search-lab">
    <div class="section-heading">
      <h2><el-icon><Search /></el-icon> 检索测试</h2>
      <el-button type="primary" :loading="searching" @click="$emit('search')">检索</el-button>
    </div>
    <el-input
      :model-value="query"
      placeholder="输入要检索的问题"
      aria-label="检索问题"
      @update:model-value="$emit('update:query', String($event))"
      @keyup.enter="$emit('search')"
    />
    <PageFeedback v-if="searching" tone="loading" title="正在检索资料" next-step="请稍候，结果会显示在下方。" />
    <PageFeedback v-else-if="error" :tone="results.length ? 'partial' : 'error'" :title="results.length ? '新检索未完成，以下仍是上次结果' : '检索未完成'" :next-step="`${error}。请检查连接或换个问题后重试。`" action-label="重试检索" @action="$emit('search')" />
    <PageFeedback v-else-if="hasSearched && !results.length" tone="empty" title="没有找到相关资料" next-step="试试其他关键词，或先上传相关文档。" />
    <article v-for="result in results" :key="result.chunk_id" class="search-result">
      <header>
        <strong>{{ result.document_title }}</strong>
        <span>score {{ result.score.toFixed(3) }}</span>
      </header>
      <p>{{ result.content }}</p>
    </article>
  </section>
</template>
