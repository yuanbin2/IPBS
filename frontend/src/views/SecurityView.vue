<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Lock, Refresh, User } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";

interface SecurityStatus {
  context: {
    actor: string;
    role: string;
    workspace_key: string;
    authenticated: boolean;
    security_enforced: boolean;
  };
  checks: Record<string, boolean | string | string[]>;
  guidance: string[];
}

interface AuditEvent {
  id: number;
  event_type: string;
  actor: string;
  role: string;
  workspace_key: string;
  path: string;
  detail: string;
  created_at: string;
}

const status = ref<SecurityStatus | null>(null);
const events = ref<AuditEvent[]>([]);
const loading = ref(false);
onMounted(loadSecurity);

async function loadSecurity() {
  loading.value = true;
  try {
    status.value = await requestJson("/api/agent/security/status/");
    events.value = await requestJson("/api/agent/security/audit-events/");
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : "安全信息加载失败");
  } finally {
    loading.value = false;
  }
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
  <section class="security-workspace">
    <section class="security-layout">
      <section class="security-panel">
        <header class="section-heading">
          <h2><el-icon><User /></el-icon> 当前身份</h2>
          <el-button :icon="Refresh" :loading="loading" @click="loadSecurity">刷新</el-button>
        </header>
        <dl v-if="status" class="security-context">
          <div>
            <dt>Actor</dt>
            <dd>{{ status.context.actor }}</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>{{ status.context.role }}</dd>
          </div>
          <div>
            <dt>Workspace</dt>
            <dd>{{ status.context.workspace_key }}</dd>
          </div>
          <div>
            <dt>Enforced</dt>
            <dd>{{ status.context.security_enforced ? "开启" : "开发兼容" }}</dd>
          </div>
        </dl>
      </section>

      <section class="security-panel">
        <header class="section-heading">
          <h2><el-icon><Lock /></el-icon> 安全检查</h2>
        </header>
        <article v-for="(value, key) in status?.checks" :key="key" class="security-check">
          <span>{{ key }}</span>
          <strong>{{ Array.isArray(value) ? value.join(", ") : value }}</strong>
        </article>
        <ul v-if="status" class="security-guidance">
          <li v-for="item in status.guidance" :key="item">{{ item }}</li>
        </ul>
      </section>
    </section>

    <section class="security-panel">
      <header class="section-heading">
        <h2>安全审计</h2>
      </header>
      <article v-for="event in events" :key="event.id" class="audit-row">
        <strong>{{ event.event_type }}</strong>
        <span>{{ event.actor }} / {{ event.role }} / {{ event.workspace_key }}</span>
        <p>{{ event.detail || event.path }}</p>
        <small>{{ new Date(event.created_at).toLocaleString() }}</small>
      </article>
    </section>
  </section>
</template>
