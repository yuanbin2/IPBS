<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Back, Cpu, Refresh, SwitchButton, Tools } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { RouterLink, useRouter } from "vue-router";
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
  last_used_at: string | null;
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
const router = useRouter();
const loading = ref(false);
const executingId = ref<number | null>(null);
const reviewingApproval = ref(false);
const query = ref("MCP 工具接入");
const executionOutput = ref("");
const pendingApproval = ref<ApprovalRequest | null>(null);
const approvalDialogOpen = ref(false);
const reviewer = ref("admin");
const reviewNote = ref("");

onMounted(loadTools);

async function loadTools() {
  loading.value = true;
  try {
    tools.value = await requestJson("/api/agent/mcp-tools/");
  } finally {
    loading.value = false;
  }
}

async function toggleTool(tool: MCPTool) {
  const payload = await requestJson(`/api/agent/mcp-tools/${tool.id}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_enabled: tool.is_enabled })
  });
  Object.assign(tool, payload);
  ElMessage.success(tool.is_enabled ? "工具已启用" : "工具已禁用");
}

async function toggleApproval(tool: MCPTool) {
  const payload = await requestJson(`/api/agent/mcp-tools/${tool.id}/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ requires_approval: tool.requires_approval })
  });
  Object.assign(tool, payload);
  ElMessage.success(tool.requires_approval ? "已要求审批，测试调用时会弹出审批窗口" : "已取消审批要求，测试调用将直接执行");
}

async function executeTool(tool: MCPTool) {
  executingId.value = tool.id;
  executionOutput.value = "";
  pendingApproval.value = null;
  try {
    const payload = await requestJson(`/api/agent/mcp-tools/${tool.id}/execute/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query.value })
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
        note: reviewNote.value
      })
    });
    pendingApproval.value = payload;
    executionOutput.value = payload.result || (decision === "approve" ? "审批已通过" : "审批已拒绝");
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
      <header class="topbar">
        <div>
          <h1>MCP 工具</h1>
        </div>
        <RouterLink to="/">
          <el-button :icon="Back">返回概览</el-button>
        </RouterLink>
      </header>

      <section class="mcp-toolbar">
        <el-input v-model="query" placeholder="工具测试输入" />
        <el-button :icon="Refresh" :loading="loading" @click="loadTools">刷新</el-button>
      </section>

      <section class="mcp-grid">
        <article v-for="tool in tools" :key="tool.id" class="mcp-card">
          <header>
            <el-icon><Tools /></el-icon>
            <div>
              <h2>{{ tool.display_name }}</h2>
              <span>{{ tool.name }} / {{ tool.category }}</span>
            </div>
          </header>
          <p>{{ tool.description }}</p>
          <div class="mcp-scope">{{ tool.permission_scope }}</div>
          <div class="mcp-switches">
            <el-switch v-model="tool.is_enabled" active-text="启用" inactive-text="禁用" @change="toggleTool(tool)" />
            <el-switch
              v-model="tool.requires_approval"
              active-text="需审批"
              inactive-text="直接执行"
              @change="toggleApproval(tool)"
            />
          </div>
          <footer>
            <small>{{ tool.last_used_at ? new Date(tool.last_used_at).toLocaleString() : "尚未调用" }}</small>
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
      </section>

      <section v-if="executionOutput" class="mcp-output">
        <h2><el-icon><Cpu /></el-icon> 调用结果</h2>
        <div v-if="pendingApproval && auth.session.role === 'admin'" class="mcp-approval-alert">
          <strong>审批单 #{{ pendingApproval.id }} 已创建</strong>
          <span>{{ pendingApproval.title }}</span>
          <el-button type="primary" @click="goApproval">去审批页处理</el-button>
        </div>
        <pre>{{ executionOutput }}</pre>
      </section>

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
          <el-button :loading="reviewingApproval" @click="reviewCurrentApproval('reject')">拒绝</el-button>
          <el-button type="primary" :loading="reviewingApproval" @click="reviewCurrentApproval('approve')">
            批准并执行
          </el-button>
        </template>
      </el-dialog>
    </section>
</template>
