<script setup lang="ts">
import { ChatDotRound, Delete } from "@element-plus/icons-vue";
import { MdPreview } from "md-editor-v3";
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
</script>

<template>
  <section class="article-detail">
    <button class="text-link" type="button" @click="$emit('back')">返回文章列表</button>
    <h2>{{ article.title }}</h2>
    <div class="article-meta">
      <span>{{ article.category?.name || "未分类" }}</span>
      <span>{{ article.view_count }} 次浏览</span>
      <span v-if="article.knowledge_document_id">已进入知识库</span>
    </div>
    <p class="summary">{{ article.summary }}</p>
    <MdPreview
      :model-value="article.content || ''"
      language="zh-CN"
      preview-theme="github"
      code-theme="github"
      :show-code-row-number="true"
      class="article-content blog-md-preview"
    />
    <div class="tag-row"><span v-for="tag in article.tags" :key="tag.id">{{ tag.name }}</span></div>
    <div class="article-actions">
      <el-button type="primary" :icon="ChatDotRound" @click="$emit('askAgent', article)">让 Agent 总结这篇文章</el-button>
      <el-button v-if="!article.knowledge_document_id" :loading="publishing" @click="$emit('sync', article)">
        同步到知识库
      </el-button>
      <el-button
        type="danger"
        plain
        :icon="Delete"
        :loading="deletingSlug === article.slug"
        @click="$emit('remove', article)"
      >
        删除文章
      </el-button>
    </div>
    <section class="comment-section">
      <h3>评论</h3>
      <article v-for="comment in article.comments" :key="comment.id" class="comment-item">
        <strong>{{ comment.author_name }}</strong><p>{{ comment.content }}</p>
      </article>
      <form class="comment-form" @submit.prevent="$emit('submitComment', article)">
        <el-input v-model="commentDraft.author_name" placeholder="昵称" />
        <el-input v-model="commentDraft.content" type="textarea" :rows="3" placeholder="写下你的想法" />
        <el-button type="primary" native-type="submit" :loading="submittingComment">发表评论</el-button>
      </form>
    </section>
  </section>
</template>
