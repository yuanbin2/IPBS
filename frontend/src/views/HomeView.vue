<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ChatDotRound, DataAnalysis, Files, Right, UploadFilled } from "@element-plus/icons-vue";
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

const quickLinks = computed(() => [
  { title: "博客", detail: "撰写和管理技术文章", icon: Files, path: "/blog" },
  { title: "知识库", detail: "上传文档，构建检索索引", icon: UploadFilled, path: "/knowledge" },
  { title: "智能对话", detail: "与多智能体助手交互", icon: ChatDotRound, path: "/chat" },
  ...(auth.canViewObservability
    ? [{ title: "观测评估", detail: "查看 Agent 运行指标与评估", icon: DataAnalysis, path: "/observability" }]
    : [])
]);

const greeting = computed(() => {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 12) return "早上好";
  if (hour < 18) return "下午好";
  return "晚上好";
});

const today = computed(() => {
  return new Date().toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long"
  });
});

onMounted(async () => {
  try {
    const [articles, knowledgeBases, observability] = await Promise.allSettled([
      requestJson("/api/agent/blog/articles/"),
      requestJson("/api/agent/knowledge-bases/"),
      auth.canViewObservability ? requestJson("/api/agent/observability/") : Promise.resolve(null)
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
        <p class="dashboard-eyebrow">{{ today }}</p>
        <h1>{{ greeting }}，{{ auth.session.actor }}</h1>
        <p class="dashboard-subtitle">智能个人博客系统 · 运行概览</p>
      </div>
      <RouterLink to="/chat">
        <el-button type="primary">
          新建对话
          <el-icon class="el-icon--right"><Right /></el-icon>
        </el-button>
      </RouterLink>
    </header>

    <section class="dashboard-metrics">
      <div class="metric">
        <span class="metric-value">{{ statsLoading ? "—" : stats.articleCount }}</span>
        <span class="metric-label">博客文章</span>
        <span class="metric-hint">已发布总数</span>
      </div>
      <div class="metric">
        <span class="metric-value">{{ statsLoading ? "—" : stats.knowledgeBaseCount }}</span>
        <span class="metric-label">知识库</span>
        <span class="metric-hint">已创建数</span>
      </div>
      <div v-if="auth.canViewObservability" class="metric">
        <span class="metric-value">{{ statsLoading ? "—" : stats.totalAgentRuns }}</span>
        <span class="metric-label">Agent 调用</span>
        <span class="metric-hint">累计运行次数</span>
      </div>
      <div v-if="auth.canViewObservability" class="metric">
        <span class="metric-value">
          {{ statsLoading ? "—" : Math.round(stats.averageLatencyMs) }}<small>ms</small>
        </span>
        <span class="metric-label">平均延迟</span>
        <span class="metric-hint">最近 Agent 响应</span>
      </div>
    </section>

    <section class="dashboard-section">
      <header class="dashboard-section-head">
        <h2>快捷入口</h2>
        <span class="dashboard-section-sub">从这里开始你的工作流</span>
      </header>
      <div class="dashboard-links">
        <RouterLink v-for="item in quickLinks" :key="item.path" class="link-card" :to="item.path">
          <div class="link-icon">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>
          <div class="link-copy">
            <h2>{{ item.title }}</h2>
            <p>{{ item.detail }}</p>
          </div>
          <el-icon class="link-arrow"><Right /></el-icon>
        </RouterLink>
      </div>
    </section>
  </section>
</template>

<style scoped>
.dashboard {
  max-width: 1100px;
}

.dashboard-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-6);
  margin-bottom: var(--space-8);
}

.dashboard-eyebrow {
  margin: 0 0 8px;
  color: var(--color-accent);
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.dashboard-header h1 {
  font-size: var(--font-size-3xl);
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: var(--space-2);
}

.dashboard-subtitle {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-md);
}

/* --- Metrics (borderless data strip) --- */
.dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  margin-bottom: var(--space-10);
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-6) var(--space-5);
  border-left: 1px solid var(--color-divider);
}

.metric:first-child {
  border-left: 0;
  padding-left: 0;
}

.metric-value {
  color: var(--color-text-primary);
  font-family: var(--font-mono);
  font-size: 34px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.metric-value small {
  font-size: var(--font-size-base);
  font-weight: 500;
  color: var(--color-text-muted);
  margin-left: 2px;
}

.metric-label {
  color: var(--color-text-primary);
  font-size: var(--font-size-base);
  font-weight: 600;
}

.metric-hint {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

/* --- Section --- */
.dashboard-section-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.dashboard-section-head h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
}

.dashboard-section-sub {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

.dashboard-links {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
}

.link-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-surface);
  padding: var(--space-5);
  text-decoration: none;
  color: inherit;
  transition: border-color var(--transition-base), box-shadow var(--transition-base),
    transform var(--transition-base);
}

.link-card:hover {
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.link-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-lg);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 22px;
  flex-shrink: 0;
}

.link-copy {
  flex: 1;
  min-width: 0;
}

.link-copy h2 {
  margin: 0 0 4px;
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--color-text-primary);
}

.link-copy p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.link-arrow {
  color: var(--color-text-muted);
  font-size: 16px;
  transition: transform var(--transition-base), color var(--transition-base);
  flex-shrink: 0;
}

.link-card:hover .link-arrow {
  transform: translateX(3px);
  color: var(--color-primary);
}

@media (max-width: 768px) {
  .dashboard-metrics {
    grid-template-columns: repeat(2, 1fr);
  }

  .metric {
    border-left: 0;
    padding: var(--space-5) var(--space-4);
  }

  .metric:nth-child(even) {
    border-left: 1px solid var(--color-divider);
  }

  .dashboard-links {
    grid-template-columns: 1fr;
  }
}
</style>
