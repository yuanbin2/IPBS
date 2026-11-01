<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { Collection, Plus } from "@element-plus/icons-vue";
import type { CollectionPublicSummary } from "../features/blog/types";
import { useAuthStore } from "../stores/auth";
import PageFeedback from "../components/PageFeedback.vue";

const router = useRouter();
const auth = useAuthStore();
const collections = ref<CollectionPublicSummary[]>([]);
const total = ref(0);
const page = ref(1);
const pages = ref(1);
const query = ref("");
const loading = ref(false);
const error = ref("");

async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, options);
  const text = await response.text();
  let payload: any = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { detail: "服务返回了无法解析的响应。" };
  }
  if (!response.ok) throw new Error(payload?.detail ?? `请求失败：HTTP ${response.status}`);
  return payload as T;
}

async function load(targetPage = page.value) {
  loading.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({ page: String(targetPage), page_size: "12" });
    if (query.value.trim()) params.set("q", query.value.trim());
    const result = await requestJson<{ items: CollectionPublicSummary[]; total: number; pages: number }>(
      `/api/agent/blog/collections/?${params.toString()}`,
    );
    collections.value = result.items;
    total.value = result.total;
    pages.value = Math.max(result.pages, 1);
    page.value = targetPage;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "领域列表加载失败";
  } finally {
    loading.value = false;
  }
}

function search() {
  void load(1);
}

function recoverEmpty() {
  if (query.value.trim()) query.value = "";
  void load(1);
}

onMounted(() => {
  void load(1);
});
</script>

<template>
  <section class="collections-page">
    <header class="collections-head">
      <div>
        <h2><el-icon><Collection /></el-icon> 领域目录</h2>
        <p>按“领域 → 课程 → 章节 → 知识点”组织已发布的博客文章。</p>
      </div>
      <el-button v-if="auth.isAuthenticated" type="primary" :icon="Plus" @click="router.push('/blog/collections/mine')">
        我的领域
      </el-button>
    </header>

    <div class="collections-search">
      <el-input
        v-model="query"
        placeholder="按标题查找领域"
        clearable
        aria-label="搜索领域"
        @keyup.enter="search"
        @clear="search"
      />
      <el-button @click="search">搜索</el-button>
    </div>

    <PageFeedback v-if="loading" tone="loading" title="正在加载领域目录" next-step="请稍候，加载完成后可选择领域。" />
    <PageFeedback v-else-if="error" tone="error" title="领域目录暂时无法加载" :next-step="`${error}。请检查连接后重试。`" action-label="重试加载" @action="load(page)" />
    <PageFeedback v-else-if="!collections.length" tone="empty" :title="query.trim() ? '没有找到匹配的领域' : '还没有已公开的领域目录'" :next-step="query.trim() ? '换个关键词再搜索。' : '可以稍后刷新，或前往我的领域创建内容。'" :action-label="query.trim() ? '清除搜索' : '刷新目录'" @action="recoverEmpty" />

    <div v-else class="collections-grid">
      <article v-for="item in collections" :key="item.public_id" class="collection-card">
        <h3>
          <router-link :to="`/blog/collections/${item.public_id}`">{{ item.title }}</router-link>
        </h3>
        <p class="collection-desc">{{ item.description || "暂无简介" }}</p>
        <p class="collection-meta">
          <span>{{ item.node_count }} 个节点</span>
          <span>{{ item.visible_article_count }} 篇文章</span>
          <span>更新于 {{ new Date(item.updated_at).toLocaleDateString("zh-CN") }}</span>
        </p>
        <el-button text type="primary" @click="router.push(`/blog/collections/${item.public_id}`)">进入目录</el-button>
      </article>
    </div>

    <div v-if="!loading && !error && pages > 1" class="collections-pager">
      <el-button :disabled="page <= 1" @click="load(page - 1)">上一页</el-button>
      <span>第 {{ page }} / {{ pages }} 页 · 共 {{ total }} 个领域</span>
      <el-button :disabled="page >= pages" @click="load(page + 1)">下一页</el-button>
    </div>
  </section>
</template>

<style scoped>
.collections-page {
  max-width: 980px;
  margin: calc(-1 * var(--page-bleed-block)) auto;
  padding: var(--space-6) 0;
  box-sizing: border-box;
  /* 高度锁定：标题与搜索固定，卡片区自带滚动条，整页不再无限变长。 */
  height: var(--page-available-height);
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  overflow: hidden;
}
/* 卡片区之外的元素都不参与收缩，避免被压扁（只有 .collections-grid 承担滚动）。 */
.collections-page > *:not(.collections-grid) { flex: none; }
.collections-head { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--space-3); flex: none; }
.collections-head h2 { margin: 0; display: flex; align-items: center; gap: var(--space-2); }
.collections-head p { margin: var(--space-1) 0 0; color: var(--color-text-secondary); font-size: var(--font-size-base); }
.collections-search { display: flex; gap: var(--space-3); flex: none; }
.collections-search .el-input { max-width: 420px; }
.collections-grid {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
  align-content: start;
  padding-right: 4px;
  scrollbar-gutter: stable;
}
.collection-card { min-width: 0; border: 1px solid var(--color-border); border-radius: var(--radius-xl); padding: var(--space-4); display: grid; gap: var(--space-2); align-content: start; background: var(--color-bg-surface); }
.collection-card h3 { margin: 0; font-size: var(--font-size-xl); overflow-wrap: anywhere; }
.collection-card h3 a { color: inherit; text-decoration: none; }
.collection-card h3 a:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.collection-desc { margin: 0; color: var(--color-text-secondary); font-size: var(--font-size-sm); min-height: 36px; overflow-wrap: anywhere; }
.collection-meta { margin: 0; display: flex; flex-wrap: wrap; gap: var(--space-3); color: var(--color-text-muted); font-size: var(--font-size-xs); }
.collections-pager { flex: none; display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: var(--space-4); color: var(--color-text-secondary); }
@media (max-width: 720px) {
  .collections-page { height: auto; min-height: var(--page-available-height); margin: 0; padding: 0; overflow: visible; }
  .collections-grid { overflow-y: visible; padding-right: 0; }
  .collections-head { flex-direction: column; }
  .collections-search { flex-direction: column; }
  .collections-search .el-input { max-width: none; }
}
</style>
