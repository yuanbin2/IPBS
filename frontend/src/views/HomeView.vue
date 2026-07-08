<script setup lang="ts">
import { ChatDotRound, Connection, Cpu, DataAnalysis, Files, UploadFilled } from "@element-plus/icons-vue";
import { RouterLink } from "vue-router";
import { usePlatformStore } from "../stores/platform";

const platform = usePlatformStore();

const modules = [
  { title: "个人博客", detail: "论文、项目、技术文章与学习笔记沉淀。", icon: Files },
  { title: "企业知识库", detail: "上传 PDF、Word、Markdown 与网页资料。", icon: UploadFilled },
  { title: "Agentic RAG", detail: "检索、重排、引用来源与多步推理。", icon: DataAnalysis },
  { title: "工具调用", detail: "博客检索、用户资料、计算器三个工具已接入。", icon: Cpu },
  { title: "对话入口", detail: "通过 /api/agent/chat/ 与 Agent 交互。", icon: ChatDotRound }
];
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Knowledge Agent</div>
      <nav class="nav">
        <RouterLink class="active" to="/">概览</RouterLink>
        <a>博客</a>
        <a>知识库</a>
        <RouterLink to="/chat">对话</RouterLink>
        <a>评估</a>
      </nav>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">Day 3 LangGraph Workflow</p>
          <h1>{{ platform.projectName }}</h1>
        </div>
        <RouterLink to="/chat">
          <el-button type="primary" :icon="Connection">新建对话</el-button>
        </RouterLink>
      </header>

      <section class="status-grid">
        <article>
          <span>后端</span>
          <strong>Django + DRF</strong>
          <small>chat + history APIs ready</small>
        </article>
        <article>
          <span>Agent</span>
          <strong>LangGraph StateGraph</strong>
          <small>classify -> route -> answer -> save</small>
        </article>
        <article>
          <span>数据库</span>
          <strong>SQLite Local</strong>
          <small>Docker-independent day-2 dev</small>
        </article>
      </section>

      <section class="module-grid">
        <article v-for="item in modules" :key="item.title" class="module-card">
          <el-icon><component :is="item.icon" /></el-icon>
          <h2>{{ item.title }}</h2>
          <p>{{ item.detail }}</p>
        </article>
      </section>

      <section class="stack">
        <span v-for="item in platform.stack" :key="item">{{ item }}</span>
      </section>
    </section>
  </main>
</template>
