<script setup lang="ts">
import { Delete } from "@element-plus/icons-vue";
import type { BlogArticle } from "../types";

defineProps<{ articles: BlogArticle[]; deletingSlug: string }>();
defineEmits<{ open: [article: BlogArticle]; remove: [article: BlogArticle] }>();
</script>

<template>
  <section class="article-list">
    <article v-for="article in articles" :key="article.id" class="article-card" @click="$emit('open', article)">
      <div><h2>{{ article.title }}</h2><p>{{ article.summary }}</p></div>
      <footer>
        <span>{{ article.category?.name || "未分类" }}</span>
        <span>{{ article.view_count }} views</span>
        <strong v-if="article.knowledge_document_id">Knowledge Ready</strong>
        <el-button
          size="small"
          type="danger"
          plain
          :icon="Delete"
          :loading="deletingSlug === article.slug"
          @click.stop="$emit('remove', article)"
        >
          删除
        </el-button>
      </footer>
    </article>
  </section>
</template>
