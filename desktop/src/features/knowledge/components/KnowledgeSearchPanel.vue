<script setup lang="ts">
import { Search } from "@element-plus/icons-vue";
import type { SearchResult } from "../types";

defineProps<{ query: string; results: SearchResult[]; searching: boolean }>();
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
      @update:model-value="$emit('update:query', String($event))"
      @keyup.enter="$emit('search')"
    />
    <article v-for="result in results" :key="result.chunk_id" class="search-result">
      <header>
        <strong>{{ result.document_title }}</strong>
        <span>score {{ result.score.toFixed(3) }}</span>
      </header>
      <p>{{ result.content }}</p>
    </article>
  </section>
</template>
