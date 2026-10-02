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
  annotation_status: string;
  latest_run: EvaluationRun | null;
}

interface EvaluationRun {
  id: number;
  case_id: number;
  answer: string;
  metrics: Record<string, number | string | { score: number | null; status: string; reason?: string }>;
  passed: boolean;
  created_at: string;
}

interface EvaluationBatch {
  id: number;
  dataset_id: number;
  status: "queued" | "running" | "completed" | "partial" | "failed";
  total_cases: number;
  progress_percent: number;
  metadata: Record<string, unknown>;
  summary: { total: number; passed: number; completed: number; needs_review: number; errors: number; pending: number };
  case_results: Array<{
    id: number;
    order: number;
    case_snapshot: { question: string; annotation_status: string };
    status: string;
    passed: boolean;
    metrics: Record<string, unknown>;
    error: string;
  }>;
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
const activeBatch = ref<EvaluationBatch | null>(null);
const category = ref("all");
const loading = ref(false);
const running = ref(false);
const loadingMore = ref(false);
const hasMore = ref(true);
const expandedObservations = ref<Set<number>>(new Set());

onMounted(async () => {
  await Promise.all([loadObservability(), loadCases()]);
  await loadLatestBatch();
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

async function loadLatestBatch() {
  try {
    const batches: EvaluationBatch[] = await requestJson("/api/agent/evaluation-batches/");
    if (!batches.length) return;
    activeBatch.value = batches[0];
    if (["queued", "running"].includes(batches[0].status)) {
      void pollEvaluationBatch(batches[0].id).catch((error) => {
        ElMessage.error(error instanceof Error ? error.message : "批次状态读取失败");
      });
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "评测批次读取失败");
  }
}

async function runEvaluation(caseId?: number) {
  running.value = true;
  try {
    const selectedCases = caseId
      ? cases.value.filter((item) => item.id === caseId)
      : cases.value.slice(0, 5);
    if (!selectedCases.length) throw new Error("当前筛选下没有可运行的评测题。");

    const version = `ui-${new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14)}-${crypto.randomUUID().slice(0, 8)}`;
    const dataset = await requestJson("/api/agent/evaluation-datasets/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version, case_ids: selectedCases.map((item) => item.id) })
    });
    await requestJson(`/api/agent/evaluation-datasets/${dataset.id}/freeze/`, { method: "POST" });
    const payload = await requestJson("/api/agent/evaluation-batches/create/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID()
      },
      body: JSON.stringify({ dataset_id: dataset.id, limit: selectedCases.length })
    });
    activeBatch.value = payload;
    const finalBatch = await pollEvaluationBatch(payload.id);
    if (finalBatch.metadata.dispatch_error) {
      ElMessage.error("评测任务未能提交到后台队列。可重试该批次，或检查任务队列服务。");
    } else if (finalBatch.status === "completed") {
      ElMessage.success(`评测完成：${finalBatch.summary.passed}/${finalBatch.summary.completed} 通过`);
    } else {
      ElMessage.warning(`评测批次结束：${batchStatusLabel(finalBatch.status)}，${finalBatch.summary.needs_review} 题待复核`);
    }
    await Promise.all([loadObservability(), loadCases()]);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "评估执行失败");
  } finally {
    running.value = false;
  }
}

async function pollEvaluationBatch(batchId: number) {
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
    const batch: EvaluationBatch = await requestJson(`/api/agent/evaluation-batches/${batchId}/`);
    activeBatch.value = batch;
    if (batch.metadata.dispatch_error) return batch;
    if (["completed", "partial", "failed"].includes(batch.status)) return batch;
  }
  throw new Error("评测仍在后台运行；可稍后刷新页面查看该批次。");
}

async function retryEvaluationBatch() {
  if (!activeBatch.value) return;
  running.value = true;
  try {
    const batch: EvaluationBatch = await requestJson(`/api/agent/evaluation-batches/${activeBatch.value.id}/retry/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    });
    activeBatch.value = batch;
    const finalBatch = await pollEvaluationBatch(batch.id);
    if (finalBatch.metadata.dispatch_error) {
      throw new Error("后台任务仍未提交，请检查 Worker 与消息队列后重试。");
    }
    ElMessage.success(`评测批次状态：${batchStatusLabel(finalBatch.status)}`);
    await loadCases();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "评测批次重试失败");
  } finally {
    running.value = false;
  }
}

function batchStatusLabel(status: string) {
  return ({ queued: "排队中", running: "运行中", completed: "完成", partial: "部分完成", failed: "失败" } as Record<string, string>)[status] ?? status;
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function metricScore(metrics: EvaluationRun["metrics"], name: string) {
  const value = metrics[name];
  return value && typeof value === "object" ? value.score : value;
}

function evaluationLabel(run: EvaluationRun) {
  const status = run.metrics.evaluation_status;
  if (status === "needs_review") return "待人工复核";
  if (status === "legacy") return "历史旧评分（不可比较）";
  return run.passed ? "通过" : "未通过";
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
            <el-button type="primary" :icon="VideoPlay" :loading="running" @click="runEvaluation()">冻结并运行前 5 题</el-button>
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
          <section v-if="activeBatch" class="evaluation-batch-status" aria-live="polite">
            <header>
              <strong>批次 #{{ activeBatch.id }} · {{ batchStatusLabel(activeBatch.status) }}</strong>
              <span>{{ activeBatch.progress_percent }}%</span>
            </header>
            <el-progress :percentage="activeBatch.progress_percent" :status="activeBatch.status === 'failed' ? 'exception' : undefined" />
            <small>
              scorer {{ activeBatch.metadata.scorer_version }} / 数据集 hash {{ activeBatch.metadata.dataset_hash }}
              / {{ activeBatch.summary.passed }} 通过 / {{ activeBatch.summary.needs_review }} 待复核
              / {{ activeBatch.summary.errors }} 失败
            </small>
            <el-button
              v-if="activeBatch.status === 'queued' && activeBatch.metadata.dispatch_error"
              size="small"
              :loading="running"
              @click="retryEvaluationBatch"
            >重试任务提交</el-button>
            <ul>
              <li v-for="result in activeBatch.case_results" :key="result.id">
                {{ result.order }}. {{ result.case_snapshot.question }} — {{ result.status }}
                <span v-if="result.error">：{{ result.error }}</span>
              </li>
            </ul>
          </section>
          <div class="evaluation-scroll">
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
              <small>标注状态：{{ item.annotation_status === "human_reviewed" ? "人工已审核" : "草稿 / 待审核" }}</small>
              <footer v-if="item.latest_run">
                <span class="status-pill" :class="item.latest_run.passed ? 'ready' : 'failed'">
                  {{ evaluationLabel(item.latest_run) }}
                </span>
                <small>
                  scorer {{ item.latest_run.metrics.scorer_version }} / correctness
                  {{ metricScore(item.latest_run.metrics, "answer_correctness") ?? "不可判定" }}
                  / latency {{ item.latest_run.metrics.latency_ms }}ms
                </small>
              </footer>
            </article>
          </div>
        </section>
      </section>
    </section>
</template>
