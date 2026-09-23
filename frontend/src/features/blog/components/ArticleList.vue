<script setup lang="ts">
import { Delete, View } from "@element-plus/icons-vue";
import type { BlogArticle, BlogCategory } from "../types";

defineProps<{
  articles: BlogArticle[];
  deletingSlug: string;
  activeCategory: string;
  categories: BlogCategory[];
}>();

defineEmits<{
  open: [article: BlogArticle];
  remove: [article: BlogArticle];
  filterCategory: [slug: string];
  clearFilter: [];
}>();

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function excerpt(text: string, maxLen = 120): string {
  if (!text) return "";
  return text.length > maxLen ? text.slice(0, maxLen) + "..." : text;
}
</script>

<template>
  <!-- 分类筛选chips -->
  <div class="category-filter-bar">
    <button
      type="button"
      :class="['category-chip', { active: !activeCategory }]"
      @click="$emit('clearFilter')"
    >
      全部
    </button>
    <button
      v-for="cat in categories"
      :key="cat.id"
      type="button"
      :class="['category-chip', { active: activeCategory === cat.slug }]"
      @click="$emit('filterCategory', cat.slug)"
    >
      {{ cat.name }}
      <span class="chip-count">{{ cat.article_count }}</span>
    </button>
  </div>

  <!-- 文章卡片列表 -->
  <section class="article-list">
    <article
      v-for="article in articles"
      :key="article.id"
      class="article-card"
      @click="$emit('open', article)"
    >
      <!-- 封面图 -->
      <div class="card-cover" v-if="article.cover_image">
        <img :src="article.cover_image" :alt="article.title" loading="lazy" />
      </div>
      <div class="card-cover placeholder" v-else>
        <span>{{ article.title.charAt(0) }}</span>
      </div>

      <!-- 卡片内容 -->
      <div class="card-body">
        <div class="card-category" v-if="article.category">
          {{ article.category.name }}
        </div>
        <h2 class="card-title">{{ article.title }}</h2>
        <p class="card-excerpt">{{ excerpt(article.summary) }}</p>

        <!-- 标签 -->
        <div class="card-tags" v-if="article.tags?.length">
          <span v-for="tag in article.tags.slice(0, 3)" :key="tag.id" class="card-tag">
            {{ tag.name }}
          </span>
        </div>

        <!-- 底部元信息 -->
        <footer class="card-meta">
          <span class="meta-author">{{ article.author_name || "匿名" }}</span>
          <span class="meta-date">{{ formatDate(article.published_at || article.created_at) }}</span>
          <span class="meta-views"><el-icon><View /></el-icon> {{ article.view_count }}</span>
          <strong v-if="article.knowledge_document_id" class="meta-kb">知识库</strong>
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
      </div>
    </article>

    <div v-if="!articles.length" class="empty-state">
      <p>暂无文章</p>
    </div>
  </section>
</template>