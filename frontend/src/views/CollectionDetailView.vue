<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowLeft, Search } from "@element-plus/icons-vue";
import type { CollectionArticleCard, CollectionPublicDetail, CollectionPublicNode } from "../features/blog/types";
import { isHiddenByAncestors } from "../features/blog/utils/collectionTree";
import {
  NODE_ARTICLE_PAGE_SIZE,
  TREE_ARTICLE_PREVIEW_SIZE,
  collectSearchHits,
  countMatchingNodes,
  nodeCards,
  pageWindow,
  paginate,
  subtreeArticleCount,
  treeArticlePreview,
  type ChildCard,
} from "../features/blog/utils/collectionReader";

const route = useRoute();
const router = useRouter();
const detail = ref<CollectionPublicDetail | null>(null);
const loading = ref(false);
const error = ref("");
const collapsed = ref<Set<number>>(new Set());
/** 右侧主内容容器，换节点时滚回顶部（它自己是滚动容器，不再滚整页）。 */
const mainRef = ref<HTMLElement | null>(null);
const activeNodeId = ref<number | null>(null);
const searchQuery = ref("");
const treeOpen = ref(false);
/** 当前选中的标签筛选（空串 = 不筛选）。 */
const activeTag = ref("");

interface TreeRow {
  node: CollectionPublicNode;
  path: CollectionPublicNode[];
  depth: number;
  inCollapsedBranch: boolean;
  matches: boolean;
  /** 当前筛选下该节点直接命中的文章数。 */
  articleCount: number;
}

const query = computed(() => searchQuery.value.trim().toLowerCase());

// 搜索时忽略折叠状态，否则命中内容可能被折叠分支藏起来、看起来像"搜不到"。
const effectiveCollapsed = computed<ReadonlySet<number>>(() =>
  query.value ? new Set<number>() : collapsed.value,
);

function nodeMatches(node: CollectionPublicNode, raw: string): boolean {
  return (
    node.title.toLowerCase().includes(raw) ||
    node.description.toLowerCase().includes(raw) ||
    node.articles.some((article) => article.title.toLowerCase().includes(raw))
  );
}

function subtreeMatches(node: CollectionPublicNode, raw: string): boolean {
  return nodeMatches(node, raw) || node.children.some((child) => subtreeMatches(child, raw));
}

/* ---------------- 标签筛选 ---------------- */

function articleMatchesTag(article: CollectionArticleCard): boolean {
  if (!activeTag.value) return true;
  return (article.tags ?? []).includes(activeTag.value);
}

/** 本节点下真正要展示的文章（已按标签筛选）。 */
function nodeArticles(node: CollectionPublicNode): CollectionArticleCard[] {
  if (!activeTag.value) return node.articles;
  return node.articles.filter(articleMatchesTag);
}

/** 节点自身或子孙中是否有命中标签的文章。 */
function subtreeMatchesTag(node: CollectionPublicNode): boolean {
  if (node.articles.some(articleMatchesTag)) return true;
  return node.children.some(subtreeMatchesTag);
}

const filteredRootArticles = computed(() => (detail.value?.root_articles ?? []).filter(articleMatchesTag));

/** 本领域出现过的全部标签及篇数，按篇数降序（便于先看到热门标签）。 */
const tagOptions = computed(() => {
  const counts = new Map<string, number>();
  const collect = (nodes: CollectionPublicNode[]) => {
    for (const node of nodes) {
      for (const article of node.articles) {
        for (const name of article.tags ?? []) counts.set(name, (counts.get(name) ?? 0) + 1);
      }
      collect(node.children);
    }
  };
  if (detail.value) {
    collect(detail.value.nodes);
    for (const article of detail.value.root_articles) {
      for (const name of article.tags ?? []) counts.set(name, (counts.get(name) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh"))
    .map(([name, count]) => ({ name, count }));
});

function toggleTag(name: string) {
  activeTag.value = activeTag.value === name ? "" : name;
}

const treeRows = computed<TreeRow[]>(() => {
  const rows: TreeRow[] = [];
  const raw = query.value;
  const tagActive = Boolean(activeTag.value);
  const active = effectiveCollapsed.value;
  const walk = (nodes: CollectionPublicNode[], parentPath: CollectionPublicNode[], ancestorIds: number[]) => {
    for (const node of nodes) {
      const path = [...parentPath, node];
      const textOk = !raw || subtreeMatches(node, raw);
      // 标签筛选生效时，整棵子树都没有命中文章的节点不进树，避免出现空分支。
      const tagOk = !tagActive || subtreeMatchesTag(node);
      rows.push({
        node,
        path,
        depth: path.length,
        // 只由「祖先」决定是否隐藏；节点自身被折叠时它仍然可见，才能再次展开。
        inCollapsedBranch: isHiddenByAncestors(ancestorIds, active),
        matches: textOk && tagOk,
        articleCount: tagActive ? nodeArticles(node).length : node.article_count,
      });
      walk(node.children, path, [...ancestorIds, node.id]);
    }
  };
  if (detail.value) walk(detail.value.nodes, [], []);
  return rows;
});

const visibleTreeRows = computed(() => treeRows.value.filter((row) => !row.inCollapsedBranch && row.matches));

/**
 * 搜索生效时右侧切到「跨节点命中列表」：此时再按节点组织反而找不到东西。
 * 仅标签筛选不算搜索，仍然停留在当前节点内筛选。
 */
const searchMode = computed(() => Boolean(query.value));

/** 当前选中的节点（null = 领域根）。 */
const activeNode = computed<CollectionPublicNode | null>(() => {
  if (!detail.value || activeNodeId.value === null) return null;
  return treeRows.value.find((row) => row.node.id === activeNodeId.value)?.node ?? null;
});

const activePath = computed<CollectionPublicNode[]>(
  () => treeRows.value.find((row) => row.node.id === activeNodeId.value)?.path ?? [],
);

/** 当前节点直属文章；根节点用领域根文章。 */
const currentArticles = computed<CollectionArticleCard[]>(() =>
  activeNode.value ? nodeArticles(activeNode.value) : filteredRootArticles.value,
);

const articlePage = ref(1);
const pageSlice = computed(() =>
  paginate(currentArticles.value, articlePage.value, NODE_ARTICLE_PAGE_SIZE),
);
const pageButtons = computed(() => pageWindow(pageSlice.value.page, pageSlice.value.totalPages));

/** 搜索模式下的扁平命中列表（同样分页）。 */
const searchHits = computed(() =>
  detail.value ? collectSearchHits(detail.value.nodes, query.value, articleMatchesTag) : [],
);
const hitSlice = computed(() => paginate(searchHits.value, articlePage.value, NODE_ARTICLE_PAGE_SIZE));
const hitPageButtons = computed(() => pageWindow(hitSlice.value.page, hitSlice.value.totalPages));
const matchedNodeCount = computed(() =>
  detail.value ? countMatchingNodes(detail.value.nodes, query.value, articleMatchesTag) : 0,
);

/** 子节点（或根节点下的顶层节点）导航卡片。 */
const childCardList = computed<ChildCard[]>(() => {
  if (!detail.value) return [];
  const list = activeNode.value ? activeNode.value.children : detail.value.nodes;
  return nodeCards(list, articleMatchesTag);
});

const statsLine = computed(() => {
  const total = pageSlice.value.total;
  if (searchMode.value) {
    return `${hitSlice.value.total} 篇匹配文章 · 分布在 ${matchedNodeCount.value} 个节点`;
  }
  if (activeNode.value) {
    const subtree = subtreeArticleCount(activeNode.value, articleMatchesTag);
    return `本节点 ${total} 篇 · 含子结构 ${subtree} 篇 · 子节点 ${activeNode.value.children.length} 个`;
  }
  return `领域根 ${total} 篇 · 顶层节点 ${detail.value?.nodes.length ?? 0} 个 · 公开版本 v${detail.value?.publication_version ?? 0}`;
});

/** 换节点 / 换筛选 / 换关键词都要回到第一页，否则会停在越界页码上。 */
watch([activeNodeId, activeTag, query], () => {
  articlePage.value = 1;
});

function goPage(page: number) {
  articlePage.value = page;
  scrollMainToTop();
}

function scrollMainToTop() {
  void nextTick(() => {
    mainRef.value?.scrollTo({ top: 0, behavior: "smooth" });
  });
}

/** 目录树里每个节点只列前几篇，其余收敛成「还有 N 篇」，避免单个节点撑爆侧栏。 */
function treePreview(node: CollectionPublicNode) {
  return treeArticlePreview(nodeArticles(node), TREE_ARTICLE_PREVIEW_SIZE);
}

function toggleNode(node: CollectionPublicNode) {
  const next = new Set(collapsed.value);
  if (next.has(node.id)) next.delete(node.id);
  else next.add(node.id);
  collapsed.value = next;
}

/** 只有带子节点的节点，折叠才有意义。 */
const collapsibleNodeIds = computed(() =>
  treeRows.value.filter((row) => row.node.children.length).map((row) => row.node.id),
);
const allCollapsed = computed(
  () => collapsibleNodeIds.value.length > 0 && collapsed.value.size >= collapsibleNodeIds.value.length,
);

function collapseAll() {
  collapsed.value = new Set(collapsibleNodeIds.value);
}

function expandAll() {
  collapsed.value = new Set();
}

/**
 * 选中节点 = 切换右侧内容，不再靠滚动定位。
 * 旧实现是「所有节点平铺 + scrollIntoView」，长领域里一次渲染几十个区块。
 */
function selectNode(node: CollectionPublicNode) {
  activeNodeId.value = node.id;
  treeOpen.value = false;
  router.replace({ query: { ...route.query, node: String(node.id) } });
  scrollMainToTop();
}

function selectNodeById(nodeId: number) {
  const row = treeRows.value.find((item) => item.node.id === nodeId);
  if (row) selectNode(row.node);
}

/** 回到领域根：简介 + 根文章 + 顶层节点卡片。 */
function selectRoot() {
  activeNodeId.value = null;
  const next = { ...route.query } as Record<string, string>;
  delete next.node;
  router.replace({ query: next });
  scrollMainToTop();
}

function articleTarget(article: CollectionArticleCard, node: CollectionPublicNode | null) {
  return {
    name: "blog",
    params: { slug: article.slug },
    query: {
      collection: detail.value?.public_id ?? "",
      node: node ? String(node.id) : route.query.node ?? "",
    },
  };
}

function restoreFromQuery() {
  const raw = route.query.node;
  if (typeof raw === "string" && raw) {
    const id = Number(raw);
    if (Number.isInteger(id) && treeRows.value.some(({ node }) => node.id === id)) {
      activeNodeId.value = id;
    }
  }
}

async function load() {
  const publicId = String(route.params.publicId ?? "");
  if (!publicId) return;
  loading.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/agent/blog/collections/${encodeURIComponent(publicId)}/`);
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.detail ?? `加载失败（HTTP ${response.status}）`);
    detail.value = payload as CollectionPublicDetail;
    restoreFromQuery();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "领域目录加载失败";
  } finally {
    loading.value = false;
  }
}

watch(
  () => route.params.publicId,
  () => {
    detail.value = null;
    collapsed.value = new Set();
    activeNodeId.value = null;
    activeTag.value = "";
    void load();
  },
);
onMounted(() => {
  void load();
});
</script>

<template>
  <section class="collection-read">
    <header class="collection-read-head">
      <el-button text :icon="ArrowLeft" @click="router.push('/blog/collections')">全部领域</el-button>
      <div class="tree-tools">
        <el-select
          v-model="activeTag"
          class="tag-filter"
          placeholder="按标签筛选"
          clearable
          size="small"
          aria-label="按标签筛选文章"
        >
          <el-option v-for="item in tagOptions" :key="item.name" :label="`${item.name}（${item.count}）`" :value="item.name" />
        </el-select>
        <span v-if="query" class="tree-hits">匹配 {{ visibleTreeRows.length }} 个节点</span>
        <el-button text :disabled="allCollapsed" @click="collapseAll">全部折叠</el-button>
        <el-button text :disabled="!collapsed.size" @click="expandAll">全部展开</el-button>
        <el-button class="tree-toggle" text @click="treeOpen = !treeOpen">{{ treeOpen ? "收起目录" : "展开目录" }}</el-button>
      </div>
    </header>

    <p v-if="loading" role="status">正在加载领域目录…</p>
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <el-empty v-else-if="!detail && !loading" description="领域不存在或尚未公开" />

    <div v-if="detail" class="collection-read-body" :class="{ 'tree-open': treeOpen }">
      <aside class="collection-tree" aria-label="领域目录树">
        <div class="tree-search">
          <el-input v-model="searchQuery" placeholder="在目录内搜索" clearable :prefix-icon="Search" aria-label="目录内搜索" />
        </div>
        <nav class="tree-scroll">
          <ul class="tree-root">
            <li>
              <button class="tree-item tree-root-item" :class="{ active: activeNodeId === null }" @click="selectRoot">
                {{ detail.title }}（根）
              </button>
              <ul v-if="filteredRootArticles.length" class="tree-articles">
                <li v-for="article in filteredRootArticles" :key="article.id">
                  <router-link class="tree-article" :to="articleTarget(article, null)">{{ article.title }}</router-link>
                </li>
              </ul>
            </li>
            <li v-for="row in visibleTreeRows" :key="row.node.id">
              <div class="tree-line" :style="{ paddingLeft: `${(row.depth - 1) * 16}px` }">
                <button
                  v-if="row.node.children.length"
                  class="tree-fold"
                  :aria-expanded="!effectiveCollapsed.has(row.node.id)"
                  :aria-label="`${effectiveCollapsed.has(row.node.id) ? '展开' : '折叠'} ${row.node.title}`"
                  @click="toggleNode(row.node)"
                >
                  {{ effectiveCollapsed.has(row.node.id) ? "▸" : "▾" }}
                </button>
                <span v-else class="tree-fold-placeholder" aria-hidden="true"></span>
                <button
                  class="tree-item"
                  :class="{ active: activeNodeId === row.node.id }"
                  @click="selectNode(row.node)"
                >
                  {{ row.node.title }}
                  <span class="tree-count">{{ row.articleCount }}</span>
                </button>
              </div>
              <ul v-if="nodeArticles(row.node).length && !effectiveCollapsed.has(row.node.id)" class="tree-articles" :style="{ paddingLeft: `${(row.depth - 1) * 16 + 22}px` }">
                <li v-for="article in treePreview(row.node).shown" :key="article.id">
                  <router-link class="tree-article" :to="articleTarget(article, row.node)">{{ article.title }}</router-link>
                </li>
                <li v-if="treePreview(row.node).hidden" class="tree-more">
                  <button type="button" class="crumb-link" @click="selectNode(row.node)">
                    还有 {{ treePreview(row.node).hidden }} 篇…
                  </button>
                </li>
              </ul>
            </li>
          </ul>
        </nav>
      </aside>

      <div ref="mainRef" class="collection-main">
        <header class="main-head">
          <nav class="node-breadcrumb" aria-label="面包屑">
            <button class="crumb-link" type="button" @click="selectRoot">{{ detail.title }}</button>
            <template v-for="item in activePath" :key="item.id">
              <span class="crumb-sep" aria-hidden="true">/</span>
              <button class="crumb-link" type="button" @click="selectNodeById(item.id)">{{ item.title }}</button>
            </template>
          </nav>
          <h2 class="collection-title">{{ activeNode ? activeNode.title : detail.title }}</h2>
          <p class="collection-desc">
            {{ activeNode ? activeNode.description || "该节点暂无描述" : detail.description || "暂无简介" }}
          </p>
          <p class="collection-stats">{{ statsLine }}</p>
        </header>

        <!-- 搜索：跨节点命中，直接对结果分页 -->
        <template v-if="searchMode">
          <p v-if="!hitSlice.total" class="node-empty">
            目录内没有匹配「{{ searchQuery.trim() }}」的文章。
          </p>
          <template v-else>
            <ul class="node-articles">
              <li v-for="hit in hitSlice.items" :key="`${hit.node.id}-${hit.article.id}`">
                <router-link class="node-article-link" :to="articleTarget(hit.article, hit.node)">
                  <strong>{{ hit.article.title }}</strong>
                </router-link>
                <span class="hit-path">
                  <template v-for="(item, index) in hit.path" :key="item.id">
                    <span v-if="index" class="crumb-sep" aria-hidden="true">/</span>
                    <button class="crumb-link" type="button" @click="selectNodeById(item.id)">{{ item.title }}</button>
                  </template>
                </span>
                <span class="node-article-meta">
                  <span v-if="hit.article.category" class="node-article-category">{{ hit.article.category }}</span>
                  {{ hit.article.author_name }} · {{ hit.article.summary.slice(0, 80) || "暂无摘要" }}
                </span>
              </li>
            </ul>
            <nav v-if="hitSlice.totalPages > 1" class="pager" aria-label="搜索结果分页">
              <button class="pager-btn" :disabled="hitSlice.page <= 1" @click="goPage(hitSlice.page - 1)">上一页</button>
              <template v-for="(item, index) in hitPageButtons" :key="`${item}-${index}`">
                <span v-if="item === 0" class="pager-gap">…</span>
                <button
                  v-else
                  class="pager-btn"
                  :class="{ active: item === hitSlice.page }"
                  :aria-current="item === hitSlice.page ? 'page' : undefined"
                  @click="goPage(item)"
                >{{ item }}</button>
              </template>
              <button class="pager-btn" :disabled="hitSlice.page >= hitSlice.totalPages" @click="goPage(hitSlice.page + 1)">下一页</button>
              <span class="pager-info">第 {{ hitSlice.from }}–{{ hitSlice.to }} 条 / 共 {{ hitSlice.total }} 条</span>
            </nav>
          </template>
        </template>

        <template v-else>
          <section v-if="childCardList.length" class="child-nodes">
            <h4 class="sub-heading">{{ activeNode ? "子节点" : "顶层节点" }}（{{ childCardList.length }}）</h4>
            <div class="node-cards">
              <button
                v-for="card in childCardList"
                :key="card.node.id"
                type="button"
                class="node-card"
                @click="selectNode(card.node)"
              >
                <strong class="node-card-title">{{ card.node.title }}</strong>
                <span class="node-card-desc">{{ card.node.description || "暂无描述" }}</span>
                <span class="node-card-meta">
                  <span>直属 {{ card.directCount }} 篇</span>
                  <span v-if="card.subtreeCount !== card.directCount">含子结构 {{ card.subtreeCount }} 篇</span>
                  <span v-if="card.node.children.length">下级 {{ card.node.children.length }} 个</span>
                </span>
              </button>
            </div>
          </section>

          <section class="collection-node">
            <h4 class="sub-heading">
              {{ activeNode ? "本节点文章" : "领域根文章" }}（{{ pageSlice.total }}）
            </h4>
            <p v-if="!pageSlice.items.length" class="node-empty">
              {{ activeTag ? `本节点没有含标签「${activeTag}」的文章。` : "本节点暂无可见文章，待补充。" }}
            </p>
            <ul v-else class="node-articles">
              <li v-for="article in pageSlice.items" :key="article.id">
                <router-link class="node-article-link" :to="articleTarget(article, activeNode)">
                  <strong>{{ article.title }}</strong>
                </router-link>
                <span class="node-article-meta">
                  <span v-if="article.category" class="node-article-category">{{ article.category }}</span>
                  {{ article.author_name }} · {{ article.summary.slice(0, 80) || "暂无摘要" }}
                </span>
                <span v-if="article.tags?.length" class="node-article-tags">
                  <button
                    v-for="name in article.tags"
                    :key="name"
                    type="button"
                    class="mini-tag"
                    :class="{ active: activeTag === name }"
                    :aria-pressed="activeTag === name"
                    @click="toggleTag(name)"
                  ># {{ name }}</button>
                </span>
              </li>
            </ul>
            <nav v-if="pageSlice.totalPages > 1" class="pager" aria-label="文章分页">
              <button class="pager-btn" :disabled="pageSlice.page <= 1" @click="goPage(pageSlice.page - 1)">上一页</button>
              <template v-for="(item, index) in pageButtons" :key="`${item}-${index}`">
                <span v-if="item === 0" class="pager-gap">…</span>
                <button
                  v-else
                  class="pager-btn"
                  :class="{ active: item === pageSlice.page }"
                  :aria-current="item === pageSlice.page ? 'page' : undefined"
                  @click="goPage(item)"
                >{{ item }}</button>
              </template>
              <button class="pager-btn" :disabled="pageSlice.page >= pageSlice.totalPages" @click="goPage(pageSlice.page + 1)">下一页</button>
              <span class="pager-info">第 {{ pageSlice.from }}–{{ pageSlice.to }} 篇 / 共 {{ pageSlice.total }} 篇</span>
            </nav>
          </section>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.collection-read {
  max-width: 1180px;
  margin: calc(-1 * var(--page-bleed-block)) auto;
  padding: var(--space-6) 0;
  box-sizing: border-box;
  /* 高度锁定：整页不再随内容变长，改由左右两栏各自滚动。 */
  height: var(--page-available-height);
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 12px;
}
.collection-read-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.tree-tools { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.tree-hits { color: #63716e; font-size: 13px; margin-right: 4px; }
.tag-filter { width: 170px; }
.tree-count { color: #8a9793; font-size: 12px; font-variant-numeric: tabular-nums; flex: none; }
.collection-read-body {
  min-height: 0;
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 18px;
}
/* 目录树是自己的框：标题区固定，树列表在自己的框里滚动，不随右侧移动。 */
.collection-tree {
  border: 1px solid #dce4e1;
  border-radius: 12px;
  padding: 10px;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 10px;
  min-height: 0;
  overflow: hidden;
}
.tree-scroll { overflow-y: auto; min-height: 0; padding-right: 2px; scrollbar-gutter: stable; }
.tree-root, .tree-children, .tree-articles { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.tree-line { display: flex; align-items: center; gap: 2px; }
.tree-fold { border: none; background: none; cursor: pointer; padding: 2px 4px; color: #63716e; flex: none; }
.tree-fold-placeholder { display: inline-block; width: 20px; flex: none; }
.tree-item { border: none; background: none; text-align: left; cursor: pointer; padding: 5px 8px; border-radius: 8px; flex: 1; min-width: 0; font-size: 14px; overflow-wrap: anywhere; display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.tree-item:hover { background: #eef3f1; }
.tree-item.active { background: #e2efe9; font-weight: 600; }
.tree-root-item { font-weight: 600; }
.tree-article { display: block; padding: 3px 8px; font-size: 13px; color: #4a5854; text-decoration: none; border-radius: 6px; overflow-wrap: anywhere; }
.tree-article:hover { background: #f2f6f4; }
.collection-main { min-width: 0; min-height: 0; overflow-y: auto; display: grid; gap: 12px; align-content: start; padding-right: 4px; scrollbar-gutter: stable; }
.collection-title { margin: 0; }
.collection-desc { margin: 0; color: #63716e; overflow-wrap: anywhere; }
.collection-stats { margin: 0; color: #8a9793; font-size: 13px; }
/* 右侧只围绕「当前一个节点」：头部固定、文章分页、子节点用卡片下钻 */
.main-head { display: grid; gap: 4px; }
.sub-heading { margin: 0 0 8px; font-size: 14px; color: #4a5854; font-weight: 600; }
.node-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.node-card {
  display: grid;
  gap: 4px;
  text-align: left;
  border: 1px solid #dce4e1;
  background: #f7faf8;
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
  font: inherit;
}
.node-card:hover { border-color: #1f6f54; background: #eef7f2; }
.node-card-title { color: #1f6f54; overflow-wrap: anywhere; }
.node-card-desc { color: #63716e; font-size: 13px; overflow-wrap: anywhere; }
.node-card-meta { display: flex; flex-wrap: wrap; gap: 8px; color: #8a9793; font-size: 12px; }
.hit-path { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; font-size: 12px; }
.pager { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.pager-btn {
  min-width: 32px;
  padding: 4px 8px;
  border: 1px solid #dce4e1;
  border-radius: 8px;
  background: #fff;
  color: #4a5854;
  font-size: 13px;
  cursor: pointer;
  font-variant-numeric: tabular-nums;
}
.pager-btn:hover:not(:disabled) { border-color: #1f6f54; color: #1f6f54; }
.pager-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.pager-btn.active { border-color: #1f6f54; background: #e2efe9; color: #1f6f54; font-weight: 600; }
.pager-gap { color: #b8c2bf; padding: 0 2px; }
.pager-info { color: #8a9793; font-size: 12px; margin-left: 4px; }
.tree-more { padding: 2px 8px; }
.collection-node { border: 1px solid #dce4e1; border-radius: 12px; padding: 14px; scroll-margin-top: 70px; }
.node-breadcrumb { color: #8a9793; font-size: 12px; margin-bottom: 6px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.crumb-sep { color: #b8c2bf; }
.crumb-link { border: none; background: none; padding: 0; cursor: pointer; color: #63716e; font-size: 12px; text-decoration: none; border-bottom: 1px dashed #c8d2cf; }
.crumb-link:hover { color: #1f6f54; border-bottom-color: #1f6f54; }
.collection-node h3 { margin: 0 0 6px; }
.node-desc { margin: 0 0 8px; color: #63716e; font-size: 14px; }
.node-empty { margin: 0; color: #8a9793; font-size: 13px; }
.node-articles { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.node-article-link { color: #1f6f54; font-weight: 600; text-decoration: none; }
.node-article-link:hover { text-decoration: underline; }
.node-article-meta { display: block; color: #63716e; font-size: 13px; overflow-wrap: anywhere; }
.node-article-category { display: inline-block; margin-right: 6px; padding: 1px 6px; border-radius: 999px; background: #eef3f1; color: #1f6f54; font-size: 12px; }
.node-article-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.mini-tag { border: 1px solid #dce4e1; background: #f7faf8; color: #4a5854; font-size: 12px; padding: 1px 8px; border-radius: 999px; cursor: pointer; }
.mini-tag:hover { border-color: #1f6f54; color: #1f6f54; }
.mini-tag.active { border-color: #1f6f54; background: #e2efe9; color: #1f6f54; font-weight: 600; }
.tree-toggle { display: none; }
@media (max-width: 900px) {
  .collection-read { height: auto; min-height: var(--page-available-height); margin: 0; padding: 0; }
  .collection-read-body { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); }
  .collection-tree { display: none; }
  .tree-open .collection-tree { display: grid; max-height: 45vh; }
  .collection-main { overflow-y: visible; padding-right: 0; }
  .tag-filter { width: 100%; }
  .tree-toggle { display: inline-flex; }
}
</style>
