<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { Loading, Lock, Refresh, User } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { auditFeedHint, mergeAuditEvents, shouldLoadOnScroll } from "../features/security/utils/auditFeed";

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

/** 首屏只拉一页，滚到列表底部再取下一页；100 条老写法会一次性铺满整页。 */
const AUDIT_PAGE_SIZE = 20;

interface AuditPage {
  events: AuditEvent[];
  total: number;
  has_more: boolean;
}

const status = ref<SecurityStatus | null>(null);
const events = ref<AuditEvent[]>([]);
const auditTotal = ref(0);
const auditHasMore = ref(true);
const auditLoading = ref(false);
const auditError = ref("");
const loading = ref(false);
const feedHint = computed(() =>
  auditError.value ||
  auditFeedHint({
    loaded: events.value.length,
    total: auditTotal.value,
    hasMore: auditHasMore.value,
    loading: auditLoading.value,
  }),
);
const feedSpinning = computed(() => auditLoading.value || (!events.value.length && auditHasMore.value));

const sentinelRef = ref<HTMLElement | null>(null);
/** 审计列表的独立滚动框；分页只在它内部发生，页面整体高度不变。 */
const scrollerRef = ref<HTMLElement | null>(null);
let sentinelObserver: IntersectionObserver | undefined;
/** true=哨兵已进入过视口，用于刷新后决定是否重新拉首页。 */
let feedPrimed = false;

onMounted(() => {
  void loadStatus();
  watchAuditSentinel();
});

onBeforeUnmount(() => sentinelObserver?.disconnect());

/**
 * 列表底部哨兵：只在审计滚动框内判定（root=滚动框），
 * 页面怎么滚都不影响上面两个面板，也不会提前触发分页。
 */
function watchAuditSentinel() {
  if (!sentinelRef.value || typeof IntersectionObserver === "undefined") return;
  sentinelObserver = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        feedPrimed = true;
        void loadNextAuditPage();
      }
    },
    { root: scrollerRef.value ?? null, rootMargin: "160px 0px" },
  );
  sentinelObserver.observe(sentinelRef.value);
}

/** 老浏览器没有 IntersectionObserver 时的兜底：滚到离底 60px 内就补一页。 */
function handleAuditScroll(event: Event) {
  const el = event.target as HTMLElement;
  if (shouldLoadOnScroll(el.scrollTop, el.clientHeight, el.scrollHeight, 60)) {
    feedPrimed = true;
    void loadNextAuditPage();
  }
}

async function loadStatus() {
  loading.value = true;
  try {
    status.value = await requestJson("/api/agent/security/status/");
  } catch (error) {
    ElMessage.warning(error instanceof Error ? error.message : "安全信息加载失败");
  } finally {
    loading.value = false;
  }
}

async function loadNextAuditPage() {
  if (auditLoading.value || !auditHasMore.value) return;
  auditLoading.value = true;
  try {
    const offset = events.value.length;
    const page: AuditPage = await requestJson(
      `/api/agent/security/audit-events/?limit=${AUDIT_PAGE_SIZE}&offset=${offset}`,
    );
    events.value = mergeAuditEvents(events.value, page.events ?? []);
    auditTotal.value = page.total ?? events.value.length;
    // 服务端返回空页时兜住 hasMore，防止到底了还反复请求。
    auditHasMore.value = Boolean(page.has_more) && (page.events?.length ?? 0) > 0;
    auditError.value = "";
  } catch (error) {
    auditError.value = error instanceof Error ? error.message : "安全审计加载失败";
    // 报错后停掉后续触发，否则每次滚到哨兵都会弹一次提示。
    auditHasMore.value = false;
    ElMessage.warning(auditError.value);
  } finally {
    auditLoading.value = false;
  }
}

async function refreshAll() {
  events.value = [];
  auditTotal.value = 0;
  auditHasMore.value = true;
  auditError.value = "";
  await loadStatus();
  // 已经滚动到过列表 → 直接重拉首页；否则让哨兵按需触发。
  if (feedPrimed) await loadNextAuditPage();
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
          <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
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
        <span v-if="events.length" class="audit-count">已加载 {{ events.length }} 条</span>
      </header>
      <div ref="scrollerRef" class="audit-scroll" @scroll="handleAuditScroll">
        <article v-for="event in events" :key="event.id" class="audit-row">
          <strong>{{ event.event_type }}</strong>
          <span>{{ event.actor }} / {{ event.role }} / {{ event.workspace_key }}</span>
          <p>{{ event.detail || event.path }}</p>
          <small>{{ new Date(event.created_at).toLocaleString() }}</small>
        </article>
        <footer ref="sentinelRef" class="audit-feed-footer">
          <el-icon v-if="feedSpinning" class="audit-spinner"><Loading /></el-icon>
          <span :class="{ 'is-error': Boolean(auditError) }">{{ feedHint }}</span>
        </footer>
      </div>
    </section>
  </section>
</template>
