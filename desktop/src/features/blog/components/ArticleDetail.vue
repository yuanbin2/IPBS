<script setup lang="ts">
import { ref } from "vue";
import { ChatDotRound, Delete, ArrowLeft } from "@element-plus/icons-vue";
import { MdPreview, type HeadList } from "md-editor-v3";
import type { BlogArticle } from "../types";

defineProps<{
  article: BlogArticle;
  commentDraft: { author_name: string; content: string };
  publishing: boolean;
  submittingComment: boolean;
  deletingSlug: string;
}>();

defineEmits<{
  back: [];
  askAgent: [article: BlogArticle];
  sync: [article: BlogArticle];
  remove: [article: BlogArticle];
  submitComment: [article: BlogArticle];
}>();

const headings = ref<HeadList[]>([]);
const activeHeadingIndex = ref(0);

// 自定义标题 ID 生成函数
function generateHeadingId(options: { text: string; level: number; index: number }) {
  return `heading-${options.index}`;
}

// 获取目录
function handleGetCatalog(list: HeadList[]) {
  headings.value = list;
}

// 跳转到标题
function scrollToHeading(item: HeadList, index: number) {
  activeHeadingIndex.value = index;

  // 使用 MdPreview 生成的标题 ID
  const headingId = `heading-${index}`;
  const element = document.getElementById(headingId);
  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
</script>

<template>
  <section class="article-detail-fullscreen">
    <!-- 顶部导航栏 -->
    <header class="article-header">
      <button class="back-button" type="button" @click="$emit('back')">
        <el-icon><ArrowLeft /></el-icon>
        返回文章列表
      </button>
      <div class="article-actions-bar">
        <el-button type="primary" :icon="ChatDotRound" @click="$emit('askAgent', article)">让 Agent 总结</el-button>
        <el-button
          v-if="!article.knowledge_document_id"
          :loading="publishing"
          @click="$emit('sync', article)"
        >
          同步到知识库
        </el-button>
        <el-button
          type="danger"
          plain
          :icon="Delete"
          :loading="deletingSlug === article.slug"
          @click="$emit('remove', article)"
        >
          删除
        </el-button>
      </div>
    </header>

    <!-- 主内容区域 -->
    <div class="article-content-wrapper">
      <!-- 左侧大纲 -->
      <aside class="article-outline" v-if="headings.length">
        <div class="outline-header">目录</div>
        <nav class="outline-nav">
          <a
            v-for="(item, index) in headings"
            :key="index"
            :class="['outline-item', `level-${item.level}`, { active: activeHeadingIndex === index }]"
            @click="scrollToHeading(item, index)"
          >
            {{ item.text }}
          </a>
        </nav>
      </aside>

      <!-- 右侧文章内容 -->
      <main class="article-main">
        <h1 class="article-title">{{ article.title }}</h1>
        <div class="article-meta">
          <span>{{ article.category?.name || "未分类" }}</span>
          <span>{{ article.view_count }} 次浏览</span>
          <span v-if="article.knowledge_document_id">已进入知识库</span>
        </div>
        <p class="article-summary" v-if="article.summary">{{ article.summary }}</p>

        <MdPreview
          :model-value="article.content || ''"
          language="zh-CN"
          preview-theme="github"
          code-theme="github"
          :show-code-row-number="true"
          :md-heading-id="generateHeadingId"
          @onGetCatalog="handleGetCatalog"
          class="article-content blog-md-preview"
        />

        <div class="tag-row">
          <span v-for="tag in article.tags" :key="tag.id">{{ tag.name }}</span>
        </div>

        <!-- 评论区 -->
        <section class="comment-section">
          <h3>评论</h3>
          <article v-for="comment in article.comments" :key="comment.id" class="comment-item">
            <strong>{{ comment.author_name }}</strong>
            <p>{{ comment.content }}</p>
          </article>
          <form class="comment-form" @submit.prevent="$emit('submitComment', article)">
            <el-input v-model="commentDraft.author_name" placeholder="昵称" />
            <el-input v-model="commentDraft.content" type="textarea" :rows="3" placeholder="写下你的想法" />
            <el-button type="primary" native-type="submit" :loading="submittingComment">发表评论</el-button>
          </form>
        </section>
      </main>
    </div>
  </section>
</template>