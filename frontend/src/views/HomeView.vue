<script setup lang="ts">
import { ChatDotRound, Connection, Cpu, DataAnalysis, Files, UploadFilled } from "@element-plus/icons-vue";
import { usePlatformStore } from "../stores/platform";

const platform = usePlatformStore();

const modules = [
  { title: "个人博客", detail: "论文、项目、技术文章与学习笔记沉淀。", icon: Files },
  { title: "企业知识库", detail: "上传 PDF、Word、Markdown 与网页资料。", icon: UploadFilled },
  { title: "Agentic RAG", detail: "检索、重排、引用来源与多步推理。", icon: DataAnalysis },
  { title: "智能体协作", detail: "LangGraph 状态图、条件边、HITL 审批。", icon: Cpu },
  { title: "对话入口", detail: "面向博客与企业资料的统一问答界面。", icon: ChatDotRound }
];
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Knowledge Agent</div>
      <nav class="nav">
        <a class="active">概览</a>
        <a>博客</a>
        <a>知识库</a>
        <a>对话</a>
        <a>评估</a>
      </nav>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">Day 1 Bootstrap</p>
          <h1>{{ platform.projectName }}</h1>
        </div>
        <el-button type="primary" :icon="Connection">新建对话</el-button>
      </header>

      <section class="status-grid">
        <article>
          <span>后端</span>
          <strong>Django + DRF</strong>
          <small>/api/health/ ready</small>
        </article>
        <article>
          <span>前端</span>
          <strong>Vue 3 + Vite</strong>
          <small>Pinia + Router + Element Plus</small>
        </article>
        <article>
          <span>数据层</span>
          <strong>PostgreSQL + Redis</strong>
          <small>pgvector-ready compose</small>
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
