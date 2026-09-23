<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  Cpu,
  DataLine,
  Folder,
  Connection,
  Monitor,
  Refresh,
  Search,
  SwitchButton,
  Tools,
  VideoPlay,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();

interface MCPTool {
  id: number;
  name: string;
  display_name: string;
  description: string;
  category: string;
  permission_scope: string;
  is_enabled: boolean;
  requires_approval: boolean;
  call_count: number;
  success_count: number;
  health_status: "healthy" | "warning" | "error" | "unknown";
  health_status_label: string;
  last_health_check: string | null;
  health_message: string;
  last_used_at: string | null;
}

interface ToolSummary {
  total_count: number;
  enabled_count: number;
  total_calls: number;
  avg_success_rate: number;
}

interface ApprovalRequest {
  id: number;
  title: string;
  description: string;
  payload: Record<string, unknown>;
  status: "pending" | "executed" | "rejected" | "failed";
  result: string;
}

const tools = ref<MCPTool[]>([]);
const summary = ref<ToolSummary>({
  total_count: 0,
  enabled_count: 0,
  total_calls: 0,
  avg_success_rate: 100,
});
const router = useRouter();
const loading = ref(false);
const executingId = ref<number | null>(null);
const healthCheckingId = ref<number | null>(null);
const bulkHealthChecking = ref(false);
const reviewingApproval = ref(false);
const query = ref("MCP 工具接入");
const searchQuery = ref("");
const selectedCategory = ref("all");
const executionOutput = ref("");
const pendingApproval = ref<ApprovalRequest | null>(null);
const approvalDialogOpen = ref(false);
const reviewer = ref("admin");
const reviewNote = ref("");

const categoryOptions = [
  { label: "全部", value: "all" },
  { label: "系统", value: "system" },
  { label: "文件系统", value: "filesystem" },
  { label: "Git", value: "git" },
  { label: "数据库", value: "database" },
  { label: "Web", value: "web" },
];

const categoryIcons: Record<string, typeof Monitor> = {
  system: Monitor,
  filesystem: Folder,
  git: Connection,
  database: DataLine,
  web: VideoPlay,
};

// 过滤后的工具列表
const filteredTools = computed(() => {
  let result = tools.value;

  // 按分类筛选
  if (selectedCategory.value !== "all") {
    result = result.filter((t) => t.category === selectedCategory.value);
  }

  // 按搜索关键词筛选
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase().trim();
    result = result.filter(
      (t) =>
        t.display_name.toLowerCase().includes(query) ||
        t.name.toLowerCase().includes(query) ||
        t.description.toLowerCase().includes(query)
    );
  }

  return result;
});

onMounted(loadTools);

async function loadTools() {
  loading.value = true;
  try {
    const payload = await requestJson("/api/agent/mcp-tools/");
    tools.value = payload.tools;
    summary.value = payload.summary;
  } finally {
    loading.value = false;
  }
}

async function toggleTool(tool: MCPTool) {
  const payload = await requestJson(`/api/agent/mcp-tools/${tool.id}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_enabled: tool.is_enabled }),
  });
  Object.assign(tool, payload);
  ElMessage.success(tool.is_enabled ? "工具已启用" : "工具已禁用");
}

async function toggleApproval(tool: MCPTool) {
  const payload = await requestJson(`/api/agent/mcp-tools/${tool.id}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ requires_approval: tool.requires_approval }),
  });
  Object.assign(tool, payload);
  ElMessage.success(
    tool.requires_approval
      ? "已要求审批，测试调用时会弹出审批窗口"
      : "已取消审批要求，测试调用将直接执行"
  );
}

async function executeTool(tool: MCPTool) {
  executingId.value = tool.id;
  executionOutput.value = "";
  pendingApproval.value = null;
  try {
    const payload = await requestJson(`/api/agent/mcp-tools/${tool.id}/execute/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query.value }),
    });
    if (payload.approval_required) {
      ElMessage.warning(`工具执行审批 #${payload.approval.id} 已创建`);
      if (auth.session.role === "admin") {
        pendingApproval.value = payload.approval;
        approvalDialogOpen.value = true;
      }
      executionOutput.value = payload.detail;
    } else {
      executionOutput.value = payload.output;
      Object.assign(tool, payload.tool);
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "工具执行失败");
  } finally {
    executingId.value = null;
  }
}

async function checkToolHealth(tool: MCPTool) {
  healthCheckingId.value = tool.id;
  try {
    const payload = await requestJson(`/api/agent/mcp-tools/${tool.id}/health-check/`, {
      method: "POST",
    });
    Object.assign(tool, payload);
    ElMessage.success(`健康检查完成：${tool.health_status_label}`);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "健康检查失败");
  } finally {
    healthCheckingId.value = null;
  }
}

async function bulkHealthCheck() {
  bulkHealthChecking.value = true;
  try {
    const payload = await requestJson("/api/agent/mcp-tools/bulk-health-check/", {
      method: "POST",
    });
    tools.value = payload;
    const healthy = payload.filter((t: MCPTool) => t.health_status === "healthy").length;
    ElMessage.success(`批量健康检查完成：${healthy}/${payload.length} 正常`);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "批量健康检查失败");
  } finally {
    bulkHealthChecking.value = false;
  }
}

async function reviewCurrentApproval(decision: "approve" | "reject") {
  if (!pendingApproval.value) return;
  reviewingApproval.value = true;
  try {
    const payload = await requestJson(`/api/agent/approvals/${pendingApproval.value.id}/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        reviewer: reviewer.value,
        note: reviewNote.value,
      }),
    });
    pendingApproval.value = payload;
    executionOutput.value =
      payload.result || (decision === "approve" ? "审批已通过" : "审批已拒绝");
    approvalDialogOpen.value = false;
    ElMessage.success(decision === "approve" ? "审批已通过并执行" : "审批已拒绝");
    await loadTools();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "审批处理失败");
  } finally {
    reviewingApproval.value = false;
  }
}

function goApproval() {
  router.push({ path: "/admin-approvals", query: { status: "pending" } });
}

function getHealthStatusClass(status: string) {
  switch (status) {
    case "healthy":
      return "health-healthy";
    case "warning":
      return "health-warning";
    case "error":
      return "health-error";
    default:
      return "health-unknown";
  }
}

function formatSuccessRate(tool: MCPTool) {
  if (tool.call_count === 0) return "暂无数据";
  const rate = (tool.success_count / tool.call_count) * 100;
  return `${rate.toFixed(1)}%`;
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
  <section class="mcp-workspace">
    <!-- 统计概览 -->
    <section class="mcp-summary">
      <article class="summary-card">
        <span>工具总数</span>
        <strong>{{ summary.total_count }}</strong>
      </article>
      <article class="summary-card">
        <span>已启用</span>
        <strong>{{ summary.enabled_count }}</strong>
      </article>
      <article class="summary-card">
        <span>总调用次数</span>
        <strong>{{ summary.total_calls }}</strong>
      </article>
      <article class="summary-card">
        <span>平均成功率</span>
        <strong>{{ summary.avg_success_rate }}%</strong>
      </article>
    </section>

    <!-- 工具栏 -->
    <section class="mcp-toolbar">
      <div class="toolbar-left">
        <el-input
          v-model="searchQuery"
          placeholder="搜索工具名称、描述..."
          clearable
          :prefix-icon="Search"
        />
      </div>
      <div class="toolbar-right">
        <el-input v-model="query" placeholder="工具测试输入" class="test-input" />
        <el-button :icon="Refresh" :loading="loading" @click="loadTools">刷新</el-button>
        <el-button
          :icon="Monitor"
          :loading="bulkHealthChecking"
          @click="bulkHealthCheck"
        >
          批量健康检查
        </el-button>
      </div>
    </section>

    <!-- 分类筛选 -->
    <section class="mcp-categories">
      <el-radio-group v-model="selectedCategory">
        <el-radio-button
          v-for="cat in categoryOptions"
          :key="cat.value"
          :label="cat.value"
        >
          {{ cat.label }}
        </el-radio-button>
      </el-radio-group>
    </section>

    <!-- 工具网格 -->
    <section class="mcp-grid">
      <article v-for="tool in filteredTools" :key="tool.id" class="mcp-card">
        <header>
          <div class="tool-icon" :class="tool.category">
            <el-icon><component :is="categoryIcons[tool.category] || Tools" /></el-icon>
          </div>
          <div class="tool-info">
            <h2>{{ tool.display_name }}</h2>
            <span class="tool-meta">{{ tool.name }} / {{ tool.category }}</span>
          </div>
          <div class="health-indicator" :class="getHealthStatusClass(tool.health_status)">
            <span class="health-dot"></span>
            <span class="health-label">{{ tool.health_status_label }}</span>
          </div>
        </header>

        <p class="tool-description">{{ tool.description }}</p>

        <div class="mcp-scope">{{ tool.permission_scope }}</div>

        <!-- 使用统计 -->
        <div class="tool-stats">
          <div class="stat-item">
            <span class="stat-label">调用次数</span>
            <span class="stat-value">{{ tool.call_count }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">成功率</span>
            <span class="stat-value">{{ formatSuccessRate(tool) }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">最后调用</span>
            <span class="stat-value">
              {{ tool.last_used_at ? new Date(tool.last_used_at).toLocaleString() : "从未" }}
            </span>
          </div>
        </div>

        <div class="mcp-switches">
          <el-switch
            v-model="tool.is_enabled"
            active-text="启用"
            inactive-text="禁用"
            @change="toggleTool(tool)"
          />
          <el-switch
            v-model="tool.requires_approval"
            active-text="需审批"
            inactive-text="直接执行"
            @change="toggleApproval(tool)"
          />
        </div>

        <footer>
          <el-button
            size="small"
            :icon="Monitor"
            :loading="healthCheckingId === tool.id"
            @click="checkToolHealth(tool)"
          >
            健康检查
          </el-button>
          <el-button
            type="primary"
            :icon="SwitchButton"
            :loading="executingId === tool.id"
            :disabled="!tool.is_enabled"
            @click="executeTool(tool)"
          >
            {{ tool.requires_approval ? "申请审批调用" : "测试调用" }}
          </el-button>
        </footer>
      </article>

      <div v-if="filteredTools.length === 0" class="mcp-empty">
        <el-icon><Tools /></el-icon>
        <span>没有找到匹配的工具</span>
      </div>
    </section>

    <!-- 调用结果 -->
    <section v-if="executionOutput" class="mcp-output">
      <h2><el-icon><Cpu /></el-icon> 调用结果</h2>
      <div v-if="pendingApproval && auth.session.role === 'admin'" class="mcp-approval-alert">
        <strong>审批单 #{{ pendingApproval.id }} 已创建</strong>
        <span>{{ pendingApproval.title }}</span>
        <el-button type="primary" @click="goApproval">去审批页处理</el-button>
      </div>
      <pre>{{ executionOutput }}</pre>
    </section>

    <!-- 审批对话框 -->
    <el-dialog v-model="approvalDialogOpen" title="审批 MCP 工具调用" width="560px" align-center>
      <section v-if="pendingApproval" class="approval-dialog-body">
        <p>{{ pendingApproval.description }}</p>
        <dl>
          <div v-for="(value, key) in pendingApproval.payload" :key="key">
            <dt>{{ key }}</dt>
            <dd>{{ value }}</dd>
          </div>
        </dl>
        <el-input v-model="reviewer" placeholder="审批人" />
        <el-input v-model="reviewNote" placeholder="审批备注" type="textarea" :rows="3" />
      </section>
      <template #footer>
        <el-button @click="goApproval">打开审批后台</el-button>
        <el-button :loading="reviewingApproval" @click="reviewCurrentApproval('reject')">
          拒绝
        </el-button>
        <el-button
          type="primary"
          :loading="reviewingApproval"
          @click="reviewCurrentApproval('approve')"
        >
          批准并执行
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>