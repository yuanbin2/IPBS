<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ArrowDown, ArrowRight, DataAnalysis, Monitor, Refresh, VideoPlay } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

interface AgentObservation {
  id: number;
  input_message: string;
  answer: string;
  route: string;
  selected_agent: string;
  trace: string[];
  tool_calls: Array<Record<string, unknown>>;
  sources: Array<Record<string, unknown>>;
  latency_ms: number;
  tool_success_rate: number;
  status: "success" | "failed";
  failure_reason: string;
  created_at: string;
}

interface EvaluationCase {
  id: number;
  question: string;
  category: "blog" | "knowledge" | "complex" | "jailbreak";
  expected_agent: string;
  reference_keywords: string[];
  latest_run: EvaluationRun | null;
}

interface EvaluationRun {
  id: number;
  case_id: number;
  answer: string;
  metrics: Record<string, number | string>;
  passed: boolean;
  created_at: string;
}

const PAGE_SIZE = 10;

const summary = ref({
  total_runs: 0,
  success_rate: 1,
  average_latency_ms: 0,
  average_tool_success_rate: 1,
  failed_runs: 0,
  langsmith_enabled: false,
  langsmith_project: ""
});
const observations = ref<AgentObservation[]>([]);
const cases = ref<EvaluationCase[]>([]);
const latestRuns = ref<EvaluationRun[]>([]);
const category = ref("all");
const loading = ref(false);
const running = ref(false);
const loadingMore = ref(false);
const hasMore = ref(true);
const expandedObservations = ref<Set<number>>(new Set());

onMounted(async () => {
  await Promise.all([loadObservability(), loadCases()]);
});

async function loadObservability() {
  loading.value = true;
  try {
    const payload = await requestJson(`/api/agent/observability/?limit=${PAGE_SIZE}&offset=0`);
    summary.value = payload.summary;
    observations.value = payload.observations;
    hasMore.value = payload.has_more;
  } finally {
    loading.value = false;
  }
}

async function loadMoreObservations() {
  if (loadingMore.value || !hasMore.value) return;
  loadingMore.value = true;
  try {
    const payload = await requestJson(`/api/agent/observability/?limit=${PAGE_SIZE}&offset=${observations.value.length}`);
    observations.value.push(...payload.observations);
    hasMore.value = payload.has_more;
  } finally {
    loadingMore.value = false;
  }
}

function handleObservationScroll(event: Event) {
  const el = event.target as HTMLElement;
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 50) {
    loadMoreObservations();
  }
}

async function loadCases() {
  cases.value = await requestJson(`/api/agent/evaluation-cases/?category=${encodeURIComponent(category.value)}`);
}

async function runEvaluation(caseId?: number) {
  running.value = true;
  try {
    const payload = await requestJson("/api/agent/evaluation-runs/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(caseId ? { case_id: caseId } : { limit: 5 })
    });
    latestRuns.value = payload.runs;
    ElMessage.success(`评估完成：${payload.passed}/${payload.total} 通过`);
    await Promise.all([loadObservability(), loadCases()]);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "评估执行失败");
  } finally {
    running.value = false;
  }
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function toggleObservation(id: number) {
  if (expandedObservations.value.has(id)) {
    expandedObservations.value.delete(id);
  } else {
    expandedObservations.value.add(id);
  }
}

function isObservationExpanded(id: number) {
  return expandedObservations.value.has(id);
}

async function requestJson(url: string, options: RequestInit = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(payload?.detail ?? `HTTP ${response.status}`);
  }
  return payload;
}
</script>

<template>
  <section class="observability-workspace">
      <section class="observability-metrics">
        <article>
          <span>运行次数</span>
          <strong>{{ summary.total_runs }}</strong>
        </article>
        <article>
          <span>成功率</span>
          <strong>{{ formatPercent(summary.success_rate) }}</strong>
        </article>
        <article>
          <span>平均耗时</span>
          <strong>{{ summary.average_latency_ms }}ms</strong>
        </article>
        <article>
          <span>工具成功率</span>
          <strong>{{ formatPercent(summary.average_tool_success_rate) }}</strong>
        </article>
      </section>

      <section class="observability-layout">
        <section class="observation-panel">
          <header class="section-heading">
            <h2><el-icon><Monitor /></el-icon> 运行记录</h2>
            <el-button :icon="Refresh" :loading="loading" @click="loadObservability">刷新</el-button>
          </header>
          <div class="observation-scroll" @scroll="handleObservationScroll">
          <article v-for="item in observations" :key="item.id" class="observation-card">
            <header class="observation-header" @click="toggleObservation(item.id)">
              <div class="observation-header-left">
                <el-icon class="observation-toggle">
                  <ArrowDown v-if="isObservationExpanded(item.id)" />
                  <ArrowRight v-else />
                </el-icon>
                <strong>{{ item.selected_agent || item.route || "unknown" }}</strong>
                <span class="status-pill" :class="item.status">{{ item.status }}</span>
              </div>
              <div class="observation-header-right">
                <span class="observation-latency">{{ item.latency_ms }}ms</span>
                <small class="observation-time">{{ item.created_at }}</small>
              </div>
            </header>
            <div v-if="isObservationExpanded(item.id)" class="observation-body">
              <p>{{ item.input_message }}</p>
              <dl>
                <div>
                  <dt>耗时</dt>
                  <dd>{{ item.latency_ms }}ms</dd>
                </div>
                <div>
                  <dt>工具</dt>
                  <dd>{{ item.tool_calls.length }}</dd>
                </div>
                <div>
                  <dt>来源</dt>
                  <dd>{{ item.sources.length }}</dd>
                </div>
              </dl>
              <div v-if="item.failure_reason" class="failure-text">{{ item.failure_reason }}</div>
              <div class="trace-list">
                <span v-for="trace in item.trace" :key="trace">{{ trace }}</span>
              </div>
            </div>
          </article>
          <div v-if="loadingMore" class="observation-loading-more">加载中...</div>
          <div v-else-if="!hasMore && observations.length > 0" class="observation-loading-more">没有更多记录了</div>
          </div>
        </section>

        <section class="evaluation-panel">
          <header class="section-heading">
            <h2><el-icon><DataAnalysis /></el-icon> 评估集</h2>
            <el-button type="primary" :icon="VideoPlay" :loading="running" @click="runEvaluation()">跑前 5 题</el-button>
          </header>
          <section class="evaluation-toolbar">
            <el-radio-group v-model="category" @change="loadCases">
              <el-radio-button label="all">全部</el-radio-button>
              <el-radio-button label="blog">博客</el-radio-button>
              <el-radio-button label="knowledge">知识库</el-radio-button>
              <el-radio-button label="complex">复杂</el-radio-button>
              <el-radio-button label="jailbreak">越权</el-radio-button>
            </el-radio-group>
          </section>
          <article v-for="item in cases" :key="item.id" class="evaluation-card">
            <header>
              <div>
                <span>{{ item.category }} / {{ item.expected_agent || "-" }}</span>
                <h3>{{ item.question }}</h3>
              </div>
              <el-button size="small" :loading="running" @click="runEvaluation(item.id)">评估</el-button>
            </header>
            <div class="keyword-row">
              <span v-for="keyword in item.reference_keywords" :key="keyword">{{ keyword }}</span>
            </div>
            <footer v-if="item.latest_run">
              <span class="status-pill" :class="item.latest_run.passed ? 'ready' : 'failed'">
                {{ item.latest_run.passed ? "通过" : "未通过" }}
              </span>
              <small>
                correctness {{ item.latest_run.metrics.answer_correctness }}
                / latency {{ item.latest_run.metrics.latency_ms }}ms
              </small>
            </footer>
          </article>
        </section>
      </section>
    </section>
</template>
