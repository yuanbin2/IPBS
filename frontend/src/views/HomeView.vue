<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ChatDotRound, DataAnalysis, Files, UploadFilled } from "@element-plus/icons-vue";
import { RouterLink } from "vue-router";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();

const stats = ref({
  articleCount: 0,
  knowledgeBaseCount: 0,
  totalAgentRuns: 0,
  averageLatencyMs: 0
});
const statsLoading = ref(true);

const quickLinks = [
  { title: "博客", detail: "撰写和管理技术文章", icon: Files, path: "/blog" },
  { title: "知识库", detail: "上传文档，构建检索索引", icon: UploadFilled, path: "/knowledge" },
  { title: "智能对话", detail: "与多智能体助手交互", icon: ChatDotRound, path: "/chat" },
  { title: "观测评估", detail: "查看 Agent 运行指标与评估", icon: DataAnalysis, path: "/observability" }
];

onMounted(async () => {
  try {
    const [articles, knowledgeBases, observability] = await Promise.allSettled([
      requestJson("/api/agent/blog/articles/"),
      requestJson("/api/agent/knowledge-bases/"),
      requestJson("/api/agent/observability/")
    ]);

    if (articles.status === "fulfilled") {
      stats.value.articleCount = Array.isArray(articles.value) ? articles.value.length : 0;
    }
    if (knowledgeBases.status === "fulfilled") {
      stats.value.knowledgeBaseCount = Array.isArray(knowledgeBases.value) ? knowledgeBases.value.length : 0;
    }
    if (observability.status === "fulfilled" && observability.value?.summary) {
      stats.value.totalAgentRuns = observability.value.summary.total_runs ?? 0;
      stats.value.averageLatencyMs = observability.value.summary.average_latency_ms ?? 0;
    }
  } finally {
    statsLoading.value = false;
  }
});

async function requestJson(url: string, options: RequestInit = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") ?? "";
  const text = await response.text();
  let payload: any = null;
  if (contentType.includes("application/json") && text) {
    payload = JSON.parse(text);
  }
  if (!response.ok) {
    throw new Error(payload?.detail ?? `HTTP ${response.status}`);
  }
  return payload;
}
</script>

<template>
  <section class="dashboard">
    <header class="dashboard-header">
      <div>
        <h1>欢迎回来，{{ auth.session.actor }}</h1>
        <p class="dashboard-subtitle">企业知识智能体平台 · 运行概览</p>
      </div>
      <RouterLink to="/chat">
        <el-button type="primary">新建对话</el-button>
      </RouterLink>
    </header>

    <section class="dashboard-stats">
      <article class="stat-card">
        <span>博客文章</span>
        <strong>{{ statsLoading ? "—" : stats.articleCount }}</strong>
        <small>已发布文章总数</small>
      </article>
      <article class="stat-card">
        <span>知识库</span>
        <strong>{{ statsLoading ? "—" : stats.knowledgeBaseCount }}</strong>
        <small>已创建知识库数</small>
      </article>
      <article class="stat-card">
        <span>Agent 调用</span>
        <strong>{{ statsLoading ? "—" : stats.totalAgentRuns }}</strong>
        <small>累计运行次数</small>
      </article>
      <article class="stat-card">
        <span>平均延迟</span>
        <strong>{{ statsLoading ? "—" : Math.round(stats.averageLatencyMs) }}<small>ms</small></strong>
        <small>最近 Agent 响应</small>
      </article>
    </section>

    <section class="dashboard-links">
      <RouterLink
        v-for="item in quickLinks"
        :key="item.path"
        class="link-card"
        :to="item.path"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <div>
          <h2>{{ item.title }}</h2>
          <p>{{ item.detail }}</p>
        </div>
      </RouterLink>
    </section>
  </section>
</template>
