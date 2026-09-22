<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Check, Close, Refresh, WarningFilled } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useRoute } from "vue-router";

interface ApprovalRequest {
  id: number;
  action: string;
  action_label: string;
  title: string;
  description: string;
  payload: Record<string, unknown>;
  status: "pending" | "executed" | "rejected" | "failed";
  requester: string;
  reviewer: string;
  review_note: string;
  result: string;
  created_at: string;
  reviewed_at: string | null;
  executed_at: string | null;
}

const approvals = ref<ApprovalRequest[]>([]);
const route = useRoute();
const initialStatus = typeof route.query.status === "string" ? route.query.status : "pending";
const statusFilter = ref(initialStatus);
const loading = ref(false);
const reviewingId = ref<number | null>(null);
const reviewer = ref("admin");
const note = ref("");

onMounted(loadApprovals);

async function loadApprovals() {
  loading.value = true;
  try {
    approvals.value = await requestJson(`/api/agent/approvals/?status=${encodeURIComponent(statusFilter.value)}`);
  } finally {
    loading.value = false;
  }
}

async function reviewApproval(approval: ApprovalRequest, decision: "approve" | "reject") {
  reviewingId.value = approval.id;
  try {
    const payload = await requestJson(`/api/agent/approvals/${approval.id}/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        reviewer: reviewer.value,
        note: note.value
      })
    });
    ElMessage.success(decision === "approve" ? "审批已通过并执行" : "审批已拒绝");
    approvals.value = approvals.value.filter((item) => item.id !== approval.id);
    if (statusFilter.value === "all") {
      approvals.value.unshift(payload);
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "审批操作失败");
  } finally {
    reviewingId.value = null;
  }
}

function statusLabel(status: ApprovalRequest["status"]) {
  const labels = {
    pending: "待审批",
    executed: "已执行",
    rejected: "已拒绝",
    failed: "执行失败"
  };
  return labels[status];
}

function approvalTypeLabel(approval: ApprovalRequest) {
  if (approval.action === "execute_sql" && approval.payload.tool_name) {
    return "MCP 工具审批";
  }
  return approval.action_label;
}

function payloadRows(payload: Record<string, unknown>) {
  return Object.entries(payload).map(([key, value]) => ({
    key,
    value: typeof value === "object" ? JSON.stringify(value) : String(value ?? "-")
  }));
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
  <section class="approval-workspace">
      <section class="approval-toolbar">
        <el-radio-group v-model="statusFilter" @change="loadApprovals">
          <el-radio-button label="pending">待审批</el-radio-button>
          <el-radio-button label="all">全部</el-radio-button>
          <el-radio-button label="executed">已执行</el-radio-button>
          <el-radio-button label="rejected">已拒绝</el-radio-button>
          <el-radio-button label="failed">失败</el-radio-button>
        </el-radio-group>
        <el-input v-model="reviewer" placeholder="审批人" />
        <el-input v-model="note" placeholder="审批备注" />
        <el-button :icon="Refresh" :loading="loading" @click="loadApprovals">刷新</el-button>
      </section>

      <section class="approval-list">
        <article v-for="approval in approvals" :key="approval.id" class="approval-card">
          <header>
            <div>
              <span class="approval-id">#{{ approval.id }}</span>
              <h2>{{ approval.title }}</h2>
            </div>
            <span class="status-pill" :class="approval.status">{{ statusLabel(approval.status) }}</span>
          </header>
          <p>{{ approval.description }}</p>
          <dl>
            <div>
              <dt>动作</dt>
              <dd>{{ approvalTypeLabel(approval) }}</dd>
            </div>
            <div>
              <dt>请求人</dt>
              <dd>{{ approval.requester || "-" }}</dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{{ new Date(approval.created_at).toLocaleString() }}</dd>
            </div>
          </dl>
          <section class="approval-payload">
            <div v-for="row in payloadRows(approval.payload)" :key="row.key">
              <dt>{{ row.key }}</dt>
              <dd>{{ row.value }}</dd>
            </div>
          </section>
          <p v-if="approval.result" class="approval-result">{{ approval.result }}</p>
          <footer v-if="approval.status === 'pending'">
            <el-button
              type="primary"
              :icon="Check"
              :loading="reviewingId === approval.id"
              @click="reviewApproval(approval, 'approve')"
            >
              批准并执行
            </el-button>
            <el-button
              type="danger"
              plain
              :icon="Close"
              :loading="reviewingId === approval.id"
              @click="reviewApproval(approval, 'reject')"
            >
              拒绝
            </el-button>
          </footer>
        </article>

        <section v-if="!loading && approvals.length === 0" class="approval-empty">
          <el-icon><WarningFilled /></el-icon>
          <p>当前没有符合条件的审批任务</p>
        </section>
      </section>
    </section>
</template>
