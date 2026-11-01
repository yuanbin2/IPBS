<script setup lang="ts">
import { computed, ref } from "vue";
import { Files, Promotion } from "@element-plus/icons-vue";
import type { ArchiveGroup } from "../types";

const props = defineProps<{
  archive: ArchiveGroup[];
  about: { title: string; content: string; highlights: string[]; author_name?: string } | null;
}>();

/** 归档默认只展示最近 6 个月，长列表默认截断防侧栏无限拉长。
 * 文章分类与专题标签不在此渲染（B-053）：主栏已有 ArticleList 的分类筛选条
 * 与工具栏「按标签筛选」下拉，重复渲染只会让右侧辅助栏变长。 */
const ARCHIVE_PREVIEW_COUNT = 6;

const showAllArchive = ref(false);

const visibleArchive = computed(() =>
  showAllArchive.value ? props.archive : props.archive.slice(0, ARCHIVE_PREVIEW_COUNT),
);
const hiddenArchiveCount = computed(() => Math.max(0, props.archive.length - ARCHIVE_PREVIEW_COUNT));
</script>

<template>
  <aside class="blog-panel">
    <section class="side-box navigation-box archive-box">
      <header class="side-box-heading">
        <h2><el-icon><Files /></el-icon> 时间归档</h2>
        <small>{{ archive.length }} 期</small>
      </header>
      <div class="archive-list">
        <div v-for="group in visibleArchive" :key="group.month" class="archive-item">
          <span>{{ group.month }}</span><strong>{{ group.articles.length }} 篇</strong>
        </div>
      </div>
      <button v-if="hiddenArchiveCount > 0" type="button" class="side-more-toggle" @click="showAllArchive = !showAllArchive">
        {{ showAllArchive ? "收起归档" : `展开更早的 ${hiddenArchiveCount} 期` }}
      </button>
    </section>

    <section v-if="about" class="side-box about-box">
      <h2><el-icon><Promotion /></el-icon> {{ about.author_name ? `${about.author_name} · 简介` : "作者简介" }}</h2>
      <p>{{ about.content }}</p>
      <div class="about-highlights">
        <span v-for="item in about.highlights" :key="item">{{ item }}</span>
      </div>
    </section>
  </aside>
</template>

<style scoped>
.side-more-toggle {
  margin-top: 8px;
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--el-color-primary, #4a7a63);
  font-size: 12px;
  line-height: 1.6;
  padding: 4px 0;
  text-align: center;
  cursor: pointer;
}

.side-more-toggle:hover {
  text-decoration: underline;
}
</style>
