<script setup lang="ts">
import { CollectionTag, Files, Promotion } from "@element-plus/icons-vue";
import type { ArchiveGroup, BlogCategory, BlogTag } from "../types";

defineProps<{
  tags: BlogTag[];
  categories: BlogCategory[];
  archive: ArchiveGroup[];
  about: { title: string; content: string; highlights: string[] } | null;
  activeCategory: string;
}>();

defineEmits<{ filter: [params: Record<string, string>] }>();
</script>

<template>
  <aside class="blog-panel">
    <section class="side-box">
      <h2><el-icon><CollectionTag /></el-icon> 标签</h2>
      <div class="tag-cloud">
        <button v-for="tag in tags" :key="tag.id" type="button" @click="$emit('filter', { tag: tag.slug })">
          {{ tag.name }} {{ tag.article_count }}
        </button>
      </div>
    </section>

    <section class="side-box">
      <h2>分类</h2>
      <div class="category-list">
        <button
          type="button"
          :class="['category-item', { active: !activeCategory }]"
          @click="$emit('filter', { category: '' })"
        >
          <span class="category-name">全部分类</span>
        </button>
        <button
          v-for="category in categories"
          :key="category.id"
          type="button"
          :class="['category-item', { active: activeCategory === category.slug }]"
          @click="$emit('filter', { category: category.slug })"
        >
          <span class="category-name">{{ category.name }}</span>
          <span class="category-count">{{ category.article_count }}</span>
        </button>
      </div>
    </section>

    <section class="side-box">
      <h2><el-icon><Files /></el-icon> 归档</h2>
      <button v-for="group in archive" :key="group.month" type="button" class="archive-item">
        {{ group.month }} / {{ group.articles.length }} 篇
      </button>
    </section>

    <section v-if="about" class="side-box about-box">
      <h2><el-icon><Promotion /></el-icon> 关于我</h2>
      <p>{{ about.content }}</p>
      <span v-for="item in about.highlights" :key="item">{{ item }}</span>
    </section>
  </aside>
</template>