<script setup lang="ts">
import { ChatDotRound, Connection, Cpu, DataAnalysis, Files, Lock, UploadFilled, UserFilled } from "@element-plus/icons-vue";
import { RouterLink } from "vue-router";
import { usePlatformStore } from "../stores/platform";

const platform = usePlatformStore();

const modules = [
  { title: "个人博客", detail: "文章发布后自动进入知识库，成为 Agent 的个人经历来源。", icon: Files, path: "/blog" },
  { title: "企业知识库", detail: "上传 Markdown、txt、PDF，自动切分并建立检索索引。", icon: UploadFilled, path: "/knowledge" },
  { title: "Agentic RAG", detail: "检索、评分、改写问题、生成答案并给出引用来源。", icon: DataAnalysis },
  { title: "工具调用", detail: "知识库检索、用户资料、计算器工具已接入。", icon: Cpu },
  { title: "对话入口", detail: "通过 /api/agent/chat/ 与 LangGraph Agent 交互。", icon: ChatDotRound, path: "/chat" }
  ,
  { title: "人工审批", detail: "敏感操作先进入审批队列，批准后才执行。", icon: Lock, path: "/admin-approvals" },
  { title: "观测评估", detail: "记录 Agent trace、耗时、工具成功率，并用评估集验证效果。", icon: DataAnalysis, path: "/observability" },
  { title: "权限安全", detail: "登录、RBAC、workspace 隔离、审计和输出脱敏。", icon: UserFilled, path: "/security" }
];
</script>

<template>
  <main class="shell">
    <aside class="sidebar">
      <div class="brand">Knowledge Agent</div>
      <nav class="nav">
        <RouterLink class="active" to="/">概览</RouterLink>
        <RouterLink to="/blog">博客</RouterLink>
        <RouterLink to="/knowledge">知识库</RouterLink>
        <RouterLink to="/chat">对话</RouterLink>
        <RouterLink to="/observability">评估</RouterLink>
        <RouterLink to="/security">安全</RouterLink>
      </nav>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div>
          <p class="eyebrow">Day 6 Personal Blog Agent</p>
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
          <small>blog + knowledge + agent APIs ready</small>
        </article>
        <article>
          <span>Agent</span>
          <strong>Agentic RAG</strong>
          <small>analyze -> retrieve -> grade -> rewrite -> cite</small>
        </article>
        <article>
          <span>博客知识源</span>
          <strong>Article to Knowledge</strong>
          <small>publish article -> embedding -> retrieval</small>
        </article>
      </section>

      <section class="module-grid">
        <component
          :is="item.path ? RouterLink : 'article'"
          v-for="item in modules"
          :key="item.title"
          class="module-card"
          :to="item.path"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <h2>{{ item.title }}</h2>
          <p>{{ item.detail }}</p>
        </component>
      </section>

      <section class="stack">
        <span v-for="item in platform.stack" :key="item">{{ item }}</span>
      </section>
    </section>
  </main>
</template>
