<script setup lang="ts">
import { computed } from "vue";
import { CollectionTag, Files, FolderOpened, Promotion } from "@element-plus/icons-vue";
import type { ArchiveGroup, BlogCategory, BlogTag } from "../types";

const props = defineProps<{
  tags: BlogTag[];
  categories: BlogCategory[];
  archive: ArchiveGroup[];
  about: { title: string; content: string; highlights: string[] } | null;
  activeCategory: string;
}>();

defineEmits<{ filter: [params: Record<string, string>] }>();

const articleCount = computed(() => props.categories.reduce((total, item) => total + item.article_count, 0));
</script>

<template>
  <aside class="blog-panel">
    <section class="side-box index-overview">
      <span class="side-eyebrow">LIBRARY OVERVIEW</span>
      <h2>知识索引</h2>
      <p>按主题浏览技术文章、项目复盘与学习记录。</p>
      <div class="index-stats">
        <div><strong>{{ articleCount }}</strong><span>文章</span></div>
        <div><strong>{{ categories.length }}</strong><span>分类</span></div>
        <div><strong>{{ tags.length }}</strong><span>标签</span></div>
      </div>
    </section>

    <section class="side-box navigation-box">
      <header class="side-box-heading">
        <h2><el-icon><FolderOpened /></el-icon> 文章分类</h2>
        <small>主题导航</small>
      </header>
      <div class="category-list">
        <button
          type="button"
          :class="['category-item', { active: !activeCategory }]"
          @click="$emit('filter', { category: '' })"
        >
          <span class="category-name">全部分类</span>
          <span class="category-count">{{ articleCount }}</span>
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

    <section class="side-box navigation-box">
      <header class="side-box-heading">
        <h2><el-icon><CollectionTag /></el-icon> 专题标签</h2>
        <small>知识点</small>
      </header>
      <div class="topic-list">
        <button v-for="tag in tags" :key="tag.id" type="button" @click="$emit('filter', { tag: tag.slug })">
          <span># {{ tag.name }}</span><strong>{{ tag.article_count }}</strong>
        </button>
      </div>
    </section>

    <section class="side-box navigation-box archive-box">
      <header class="side-box-heading">
        <h2><el-icon><Files /></el-icon> 时间归档</h2>
        <small>{{ archive.length }} 期</small>
      </header>
      <div class="archive-list">
        <div v-for="group in archive" :key="group.month" class="archive-item">
          <span>{{ group.month }}</span><strong>{{ group.articles.length }} 篇</strong>
        </div>
      </div>
    </section>

    <section v-if="about" class="side-box about-box">
      <h2><el-icon><Promotion /></el-icon> 作者简介</h2>
      <p>{{ about.content }}</p>
      <div class="about-highlights">
        <span v-for="item in about.highlights" :key="item">{{ item }}</span>
      </div>
    </section>
  </aside>
</template>
