<script setup lang="ts">
import { computed } from "vue";
import { ChatLineRound, Delete, View } from "@element-plus/icons-vue";
import type { BlogArticle, BlogCategory } from "../types";

const props = defineProps<{
  articles: BlogArticle[];
  deletingSlug: string;
  activeCategory: string;
  categories: BlogCategory[];
}>();

const activeCategoryName = computed(() => {
  if (!props.activeCategory) return "全部文章";
  return props.categories.find((item) => item.slug === props.activeCategory)?.name ?? "分类文章";
});

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

function excerpt(text: string, maxLen = 150): string {
  if (!text) return "";
  return text.length > maxLen ? text.slice(0, maxLen) + "..." : text;
}
</script>

<template>
  <section class="article-browser">
    <header class="article-browser-heading">
      <div>
        <span class="section-eyebrow">KNOWLEDGE INDEX</span>
        <h1>{{ activeCategoryName }}</h1>
      </div>
      <span class="article-result-count">{{ articles.length }} 篇结果</span>
    </header>

    <nav class="category-filter-bar" aria-label="文章分类">
      <button
        type="button"
        :class="['category-chip', { active: !activeCategory }]"
        :aria-current="!activeCategory ? 'page' : undefined"
        @click="$emit('clearFilter')"
      >
        全部
      </button>
      <button
        v-for="cat in categories"
        :key="cat.id"
        type="button"
        :class="['category-chip', { active: activeCategory === cat.slug }]"
        :aria-current="activeCategory === cat.slug ? 'page' : undefined"
        @click="$emit('filterCategory', cat.slug)"
      >
        {{ cat.name }}
        <span class="chip-count">{{ cat.article_count }}</span>
      </button>
    </nav>
  </section>

  <section class="article-list">
    <article
      v-for="(article, index) in articles"
      :key="article.id"
      class="article-card"
      @click="$emit('open', article)"
    >
      <div class="article-index" aria-hidden="true">
        {{ String(index + 1).padStart(2, "0") }}
      </div>

      <div class="card-body">
        <div class="card-kicker">
          <span class="card-category">{{ article.category?.name || "未分类" }}</span>
          <span v-if="article.knowledge_document_id" class="meta-kb">已收录知识库</span>
        </div>
        <h2 class="card-title">{{ article.title }}</h2>
        <p v-if="article.summary" class="card-excerpt">{{ excerpt(article.summary) }}</p>

        <div class="card-tags" v-if="article.tags?.length">
          <span v-for="tag in article.tags.slice(0, 4)" :key="tag.id" class="card-tag">
            # {{ tag.name }}
          </span>
        </div>

        <footer class="card-meta">
          <span class="meta-author">By {{ article.author_name || "匿名" }}</span>
          <span class="meta-date">{{ formatDate(article.published_at || article.created_at) }}</span>
          <span class="meta-views"><el-icon><View /></el-icon> {{ article.view_count }}</span>
          <span class="meta-comments"><el-icon><ChatLineRound /></el-icon> {{ article.comment_count }}</span>
          <span class="card-read-link">阅读全文 <b>→</b></span>
          <el-button
            class="card-admin-action"
            size="small"
            type="danger"
            text
            :icon="Delete"
            :loading="deletingSlug === article.slug"
            @click.stop="$emit('remove', article)"
          >
            删除
          </el-button>
        </footer>
      </div>

      <div v-if="article.cover_image" class="card-cover">
        <img :src="article.cover_image" :alt="article.title" loading="lazy" />
      </div>
    </article>

    <div v-if="!articles.length" class="empty-state">
      <strong>这个分类还没有文章</strong>
      <p>可以切换其他分类，或创建一篇新的技术笔记。</p>
    </div>
  </section>
</template>
