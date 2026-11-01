<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Plus } from "@element-plus/icons-vue";
import type {
  BlogArticle,
  BlogCategory,
  BlogTag,
  CollectionAutoRule,
  CollectionDraft,
} from "../features/blog/types";
import type { CollectionEntrySummary } from "../features/blog/types";
import {
  autoRuleKey,
  autoRuleLabel,
  canCreateRule,
  pendingArticleIds,
  summarizeBatchResult,
} from "../features/blog/utils/entryBatch";
import {
  buildCollectionTree,
  collapsibleIds,
  flattenCollectionTree,
} from "../features/blog/utils/collectionTree";
import {
  isSameOrder,
  moveEntryRelative,
  sortEntriesByPosition,
  type DropPosition,
} from "../features/blog/utils/entryOrder";
import { useCollectionArchiveTransfer } from "../features/blog/composables/useCollectionArchiveTransfer";
import CollectionArchiveDialog from "../features/blog/components/CollectionArchiveDialog.vue";

const collections = ref<CollectionDraft[]>([]);
const active = ref<CollectionDraft | null>(null);
const loading = ref(false);
const saving = ref(false);
const submitting = ref(false);
const error = ref("");
const saveStatus = ref("");
const creating = ref(false);
const newTitle = ref("");
const newDescription = ref("");
const listFilter = ref("");

// 新节点表单
const newNodeParent = ref<number | "">("");
const newNodeTitle = ref("");
const newNodeDescription = ref("");
const nodeTitleInputRef = ref<any>(null);
const nodeFilter = ref("");

// 节点树折叠状态
const collapsedNodes = ref<Set<number>>(new Set());
const highlightNodeId = ref<number | null>(null);
let highlightTimer: number | undefined;

// 选文章表单
const entryNode = ref<number | "">("");
const articleQuery = ref("");
const articleCategory = ref("");
const articleOptions = ref<BlogArticle[]>([]);
const articleTotal = ref(0);
const articleLoading = ref(false);
const selectedArticleIds = ref<number[]>([]);
const categories = ref<BlogCategory[]>([]);
const tags = ref<BlogTag[]>([]);
const entryFilter = ref("");

// 自动收录规则（B-065）：分类（+可选标签）命中的已发布文章自动挂到目标节点。
const ruleNode = ref<number | "">("");
const ruleCategory = ref<number | null>(null);
const ruleTag = ref<number | null>(null);
const ruleSaving = ref(false);
const autoApplied = ref(0);

// 文章拖拽排序状态（B-064）：dragEntryId 为被拖动的条目，dropEntryId/Position 为当前落点提示。
const dragEntryId = ref<number | null>(null);
const dropEntryId = ref<number | null>(null);
const dropPosition = ref<DropPosition>("before");

const editorRef = ref<HTMLElement | null>(null);

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

function post(url: string, body: Record<string, unknown>) {
  return requestJson<{ draft_version?: number }>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function loadList() {
  loading.value = true;
  error.value = "";
  try {
    const result = await requestJson<{ items: CollectionDraft[] }>("/api/agent/blog/collections/mine/");
    collections.value = result.items;
    if (active.value) {
      // 列表接口只返回摘要（无 nodes/entries）；同步状态字段但保留已打开的草稿体
      const current = result.items.find((item) => item.public_id === active.value?.public_id);
      if (current) {
        active.value = { ...active.value, ...current, nodes: active.value.nodes, entries: active.value.entries };
      } else {
        active.value = null;
      }
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "领域列表加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadCategories() {
  try {
    categories.value = await requestJson<BlogCategory[]>("/api/agent/blog/categories/");
  } catch {
    // 分类加载失败不阻塞主流程，只少一个筛选维度。
    categories.value = [];
  }
}

async function openDraft(item: CollectionDraft) {
  error.value = "";
  try {
    const draft = await requestJson<CollectionDraft & { auto_applied?: number }>(
      `/api/agent/blog/collections/${item.public_id}/draft/`,
    );
    active.value = draft;
    saveStatus.value = "";
    // 规则补齐是静默发生的，补到了就明确告诉用户，避免"文章怎么自己进来了"。
    if (draft.auto_applied) {
      autoApplied.value = draft.auto_applied;
      ElMessage.info(`自动收录规则补入了 ${draft.auto_applied} 篇新文章`);
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "草稿加载失败";
  }
}

async function createCollection() {
  if (!newTitle.value.trim()) {
    error.value = "请填写领域标题";
    return;
  }
  creating.value = true;
  error.value = "";
  try {
    const created = (await post("/api/agent/blog/collections/", {
      title: newTitle.value.trim(),
      description: newDescription.value.trim(),
    })) as unknown as CollectionDraft;
    const title = newTitle.value.trim();
    newTitle.value = "";
    newDescription.value = "";
    ElMessage.success(`领域「${title}」已创建，接着加节点和文章吧`);
    await loadList();
    if (created?.public_id) {
      await openDraft(created);
      await nextTick();
      editorRef.value?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "创建失败";
  } finally {
    creating.value = false;
  }
}

async function patchCollection(fields: Record<string, unknown>) {
  if (!active.value) return;
  saving.value = true;
  error.value = "";
  try {
    const result = await requestJson<CollectionDraft>(`/api/agent/blog/collections/${active.value.public_id}/draft/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...fields, expected_version: active.value.draft_version }),
    });
    active.value = result;
    saveStatus.value = "已保存到私有工作版。";
    void loadList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "保存失败";
    if (cause instanceof Error && cause.message.includes("409")) {
      saveStatus.value = "";
    }
  } finally {
    saving.value = false;
  }
}

const nodeOptions = computed(() => {
  if (!active.value) return [];
  const nodes = active.value.nodes;
  const depthOf = new Map<number, number>();
  const depth = (nodeId: number | null): number => {
    if (nodeId == null) return 0;
    if (depthOf.has(nodeId)) return depthOf.get(nodeId)!;
    const node = nodes.find((item) => item.id === nodeId);
    const value = node ? 1 + depth(node.parent) : 0;
    depthOf.set(nodeId, value);
    return value;
  };
  return nodes.map((node) => ({ ...node, depth: depth(node.parent) }));
});

function nodeName(nodeId: number | null): string {
  if (nodeId == null) return "领域根";
  const node = nodeOptions.value.find((item) => item.id === nodeId);
  return node ? `${"　".repeat(node.depth)}${node.title}` : "未知节点";
}

/* ---------------- 节点树：折叠与可见性 ---------------- */

const nodeTree = computed(() => (active.value ? buildCollectionTree(active.value.nodes) : []));
const collapsibleNodeIds = computed(() => collapsibleIds(nodeTree.value));
const allNodesCollapsed = computed(
  () => collapsibleNodeIds.value.length > 0 && collapsibleNodeIds.value.every((id) => collapsedNodes.value.has(id)),
);

const nodeRows = computed(() => {
  const kw = nodeFilter.value.trim().toLowerCase();
  // 筛选时忽略折叠状态，否则深层节点会被折叠分支挡住、看起来像搜不到。
  const rows = flattenCollectionTree(nodeTree.value, kw ? new Set<number>() : collapsedNodes.value);
  if (!kw) return rows;

  // 命中节点连同其祖先一起保留，保证层级上下文不丢。
  const parents = new Map((active.value?.nodes ?? []).map((node) => [node.id, node.parent]));
  const keep = new Set<number>();
  for (const row of rows) {
    const hit =
      row.node.title.toLowerCase().includes(kw) || row.node.description.toLowerCase().includes(kw);
    if (!hit) continue;
    keep.add(row.node.id);
    let cursor = parents.get(row.node.id) ?? null;
    while (cursor != null) {
      keep.add(cursor);
      cursor = parents.get(cursor) ?? null;
    }
  }
  return rows.filter((row) => keep.has(row.node.id));
});

const visibleCollections = computed(() => {
  const kw = listFilter.value.trim().toLowerCase();
  if (!kw) return collections.value;
  return collections.value.filter((item) => item.title.toLowerCase().includes(kw));
});

// 归档传输状态只在 composable 中持有；列表刷新沿用页面的 loadList。
const {
  exportBusy, importDialog, importFile, importPlan, importConflict, importBusy, importApplying,
  selectedCount, allVisibleSelected, importSummary, isSelected, toggleSelect, toggleSelectAll,
  exportOne, exportSelected, openImportDialog, pickImportFile, applyImport,
} = useCollectionArchiveTransfer(visibleCollections, loadList);

const visibleEntries = computed(() => {
  const kw = entryFilter.value.trim().toLowerCase();
  const list = active.value?.entries ?? [];
  if (!kw) return list;
  return list.filter((entry) => entry.article.title.toLowerCase().includes(kw));
});

/** 分类按「已发布文章数」降序，常用的排前面。 */
const categoryOptions = computed(() =>
  [...categories.value].sort((a, b) => b.article_count - a.article_count || a.name.localeCompare(b.name, "zh")),
);

/** 标签同样按热度降序，作为自动收录规则的可选二级条件。 */
const tagOptions = computed(() =>
  [...tags.value].sort((a, b) => b.article_count - a.article_count || a.name.localeCompare(b.name, "zh")),
);

const autoRules = computed<CollectionAutoRule[]>(() => active.value?.auto_rules ?? []);
const collectedArticleIds = computed(() => (active.value?.entries ?? []).map((entry) => entry.article.id));
const pendingAddIds = computed(() => pendingArticleIds(selectedArticleIds.value, collectedArticleIds.value));
const activeRuleNodeId = computed<number | null>(() =>
  ruleNode.value === "" ? null : (ruleNode.value as number),
);
const ruleDuplicate = computed(() => {
  const key = autoRuleKey(activeRuleNodeId.value, ruleCategory.value, ruleTag.value);
  return autoRules.value.some(
    (rule) => autoRuleKey(rule.node, rule.category?.id ?? null, rule.tag?.id ?? null) === key,
  );
});

function toggleNodeCollapse(nodeId: number) {
  const next = new Set(collapsedNodes.value);
  if (next.has(nodeId)) next.delete(nodeId);
  else next.add(nodeId);
  collapsedNodes.value = next;
}

function collapseAllNodes() {
  collapsedNodes.value = new Set(collapsibleNodeIds.value);
}

function expandAllNodes() {
  collapsedNodes.value = new Set();
}

function flashNode(nodeId: number) {
  highlightNodeId.value = nodeId;
  window.clearTimeout(highlightTimer);
  highlightTimer = window.setTimeout(() => {
    highlightNodeId.value = null;
  }, 2200);
}

/** 展开目标节点的所有祖先并滚动到它，避免"新建了却看不见"。 */
function revealNode(nodeId: number) {
  const nodes = active.value?.nodes ?? [];
  const parents = new Map(nodes.map((node) => [node.id, node.parent]));
  const next = new Set(collapsedNodes.value);
  let cursor = parents.get(nodeId) ?? null;
  while (cursor != null) {
    next.delete(cursor);
    cursor = parents.get(cursor) ?? null;
  }
  collapsedNodes.value = next;
  flashNode(nodeId);
  void nextTick(() => {
    document.getElementById(`manager-node-${nodeId}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

function startChildNode(parentId: number) {
  newNodeParent.value = parentId;
  void nextTick(() => nodeTitleInputRef.value?.focus?.());
}

// 切换草稿时重置视图状态（保存导致的 active 更新不重置，避免打断操作）
watch(
  () => active.value?.public_id,
  () => {
    collapsedNodes.value = new Set();
    nodeFilter.value = "";
    entryFilter.value = "";
    dragEntryId.value = null;
    dropEntryId.value = null;
    highlightNodeId.value = null;
    newNodeParent.value = "";
    selectedArticleIds.value = [];
    ruleCategory.value = null;
    ruleTag.value = null;
  },
);

/* ---------------- 节点增删改 ---------------- */

async function createNode() {
  if (!active.value || !newNodeTitle.value.trim()) {
    error.value = "请填写节点标题";
    return;
  }
  if (newNodeParent.value !== "" && !active.value.nodes.some((node) => node.id === newNodeParent.value)) {
    error.value = "父节点无效";
    return;
  }
  const publicId = active.value.public_id;
  const title = newNodeTitle.value.trim();
  const parentLabel = newNodeParent.value === "" ? "领域根" : nodeName(newNodeParent.value as number).trim();
  const before = new Set(active.value.nodes.map((node) => node.id));

  saving.value = true;
  error.value = "";
  try {
    await post(`/api/agent/blog/collections/${publicId}/nodes/`, {
      title,
      description: newNodeDescription.value.trim(),
      parent_id: newNodeParent.value === "" ? null : newNodeParent.value,
      expected_version: active.value.draft_version,
    });
    newNodeTitle.value = "";
    newNodeDescription.value = "";
    ElMessage.success(`节点「${title}」已加到 ${parentLabel}`);
    await openDraft({ public_id: publicId } as CollectionDraft);
    void loadList();

    const created = active.value?.nodes.find((node) => !before.has(node.id));
    if (created) revealNode(created.id);
    void nextTick(() => nodeTitleInputRef.value?.focus?.());
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "节点创建失败";
  } finally {
    saving.value = false;
  }
}

async function renameNode(nodeId: number, currentTitle: string) {
  if (!active.value) return;
  try {
    const { value } = await ElMessageBox.prompt("新的节点标题", "重命名节点", {
      inputValue: currentTitle,
      inputPattern: /\S+/,
      inputErrorMessage: "标题不能为空",
    });
    await requestJson(`/api/agent/blog/collections/${active.value.public_id}/nodes/${nodeId}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: value.trim(), expected_version: active.value.draft_version }),
    });
    ElMessage.success("节点已重命名");
    await openDraft({ public_id: active.value.public_id } as CollectionDraft);
    void loadList();
  } catch (cause) {
    if (cause === "cancel" || (cause as Error)?.message === "cancel") return;
    error.value = cause instanceof Error ? cause.message : "重命名失败";
  }
}

async function moveNodeUp(nodeId: number, parent: number | null) {
  if (!active.value) return;
  const siblings = active.value.nodes
    .filter((node) => node.parent === parent)
    .sort((a, b) => a.position - b.position);
  const index = siblings.findIndex((node) => node.id === nodeId);
  if (index <= 0) return;
  const ordered = siblings.map((node) => node.id);
  [ordered[index - 1], ordered[index]] = [ordered[index], ordered[index - 1]];
  await reorder("nodes", ordered, parent);
}

async function moveNodeDown(nodeId: number, parent: number | null) {
  if (!active.value) return;
  const siblings = active.value.nodes
    .filter((node) => node.parent === parent)
    .sort((a, b) => a.position - b.position);
  const index = siblings.findIndex((node) => node.id === nodeId);
  if (index < 0 || index >= siblings.length - 1) return;
  const ordered = siblings.map((node) => node.id);
  [ordered[index + 1], ordered[index]] = [ordered[index], ordered[index + 1]];
  await reorder("nodes", ordered, parent);
}

async function deleteNode(nodeId: number) {
  if (!active.value) return;
  try {
    await ElMessageBox.confirm("删除节点会同时删除其子节点和目录内文章引用（不影响文章本身）。是否继续？", "删除节点", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  saving.value = true;
  try {
    await requestJson(`/api/agent/blog/collections/${active.value.public_id}/nodes/${nodeId}/`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: active.value.draft_version }),
    });
    ElMessage.success("节点已删除");
    await openDraft({ public_id: active.value.public_id } as CollectionDraft);
    void loadList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "删除失败";
  } finally {
    saving.value = false;
  }
}

/* ---------------- 文章加入 ---------------- */

async function searchArticles() {
  articleLoading.value = true;
  try {
    const params = new URLSearchParams({ status: "published", page: "1", page_size: "24" });
    if (articleQuery.value.trim()) params.set("q", articleQuery.value.trim());
    if (articleCategory.value) params.set("category", articleCategory.value);
    const result = await requestJson<{ items: BlogArticle[]; total?: number }>(
      `/api/agent/blog/articles/discover/?${params.toString()}`,
    );
    articleOptions.value = result.items;
    articleTotal.value = result.total ?? result.items.length;
    selectedArticleIds.value = [];
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "文章搜索失败";
  } finally {
    articleLoading.value = false;
  }
}

async function addEntries() {
  if (!active.value) return;
  const ids = pendingAddIds.value;
  if (!ids.length) {
    error.value = selectedArticleIds.value.length
      ? "选择的文章都已在该目录中"
      : "请先搜索并选择要加入的已发布文章（可多选）";
    return;
  }
  const publicId = active.value.public_id;
  const targetLabel = entryNode.value === "" ? "领域根" : nodeName(entryNode.value as number).trim();
  saving.value = true;
  error.value = "";
  try {
    const result = await requestJson<{ added?: number; skipped?: number[] }>(
      `/api/agent/blog/collections/${publicId}/entries/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          article_ids: ids,
          node_id: entryNode.value === "" ? null : entryNode.value,
          expected_version: active.value.draft_version,
        }),
      },
    );
    const added = result.added ?? ids.length;
    const skipped = result.skipped?.length ?? 0;
    ElMessage.success(`${summarizeBatchResult(added, skipped)}（${targetLabel}）`);
    selectedArticleIds.value = [];
    await openDraft({ public_id: publicId } as CollectionDraft);
    void loadList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "加入失败";
  } finally {
    saving.value = false;
  }
}

function selectAllVisibleArticles() {
  const ids = pendingArticleIds(
    articleOptions.value.map((article) => article.id),
    collectedArticleIds.value,
  );
  if (!ids.length) {
    error.value = "当前搜索结果都已在该目录中";
    return;
  }
  selectedArticleIds.value = ids;
  error.value = "";
}

/* ---------------- 自动收录规则（B-065） ---------------- */

async function addAutoRule() {
  if (!active.value) return;
  if (!canCreateRule(ruleCategory.value)) {
    error.value = "请先选择一个分类作为自动收录条件";
    return;
  }
  if (ruleDuplicate.value) {
    error.value = "这条规则已经存在了";
    return;
  }
  const publicId = active.value.public_id;
  ruleSaving.value = true;
  error.value = "";
  try {
    const result = await requestJson<{ added?: number }>(`/api/agent/blog/collections/${publicId}/auto-rules/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        node_id: activeRuleNodeId.value,
        category_id: ruleCategory.value,
        tag_id: ruleTag.value,
      }),
    });
    const added = result.added ?? 0;
    ElMessage.success(added ? `规则已生效，自动收录了 ${added} 篇文章` : "规则已添加，暂无匹配的新文章");
    ruleCategory.value = null;
    ruleTag.value = null;
    await openDraft({ public_id: publicId } as CollectionDraft);
    void loadList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "规则添加失败";
  } finally {
    ruleSaving.value = false;
  }
}

async function setAutoRuleEnabled(rule: CollectionAutoRule, enabled: boolean) {
  if (!active.value) return;
  const publicId = active.value.public_id;
  ruleSaving.value = true;
  error.value = "";
  try {
    const updated = await requestJson<{ added?: number }>(
      `/api/agent/blog/collections/${publicId}/auto-rules/${rule.id}/`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, apply: enabled }),
      },
    );
    const added = updated.added ?? 0;
    ElMessage.success(enabled ? (added ? `已启用并收录 ${added} 篇` : "规则已启用") : "规则已停用");
    await openDraft({ public_id: publicId } as CollectionDraft);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "规则更新失败";
  } finally {
    ruleSaving.value = false;
  }
}

async function removeAutoRule(rule: CollectionAutoRule) {
  if (!active.value) return;
  const publicId = active.value.public_id;
  try {
    await ElMessageBox.confirm(`删除规则「${autoRuleLabel(rule)}」？已收录的文章会保留。`, "删除自动收录规则", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  ruleSaving.value = true;
  error.value = "";
  try {
    await requestJson(`/api/agent/blog/collections/${publicId}/auto-rules/${rule.id}/`, { method: "DELETE" });
    ElMessage.success("规则已删除");
    await openDraft({ public_id: publicId } as CollectionDraft);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "规则删除失败";
  } finally {
    ruleSaving.value = false;
  }
}

function formatRuleTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

/** 手动触发一次补齐：等价于重新打开草稿（后端 GET draft 时会自动应用规则）。 */
async function syncAutoRules() {
  if (!active.value) return;
  const before = active.value.entries.length;
  await openDraft({ public_id: active.value.public_id } as CollectionDraft);
  const added = (active.value?.entries.length ?? 0) - before;
  ElMessage.success(added > 0 ? `已同步 ${added} 篇新文章` : "已是最新，没有新文章需要收录");
}

async function removeEntry(entryId: number) {
  if (!active.value) return;
  saving.value = true;
  try {
    await requestJson(`/api/agent/blog/collections/${active.value.public_id}/entries/${entryId}/`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_version: active.value.draft_version }),
    });
    ElMessage.success("文章已移出目录");
    await openDraft({ public_id: active.value.public_id } as CollectionDraft);
    void loadList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "移除失败";
  } finally {
    saving.value = false;
  }
}

async function moveEntry(entryId: number, node: number | null, offset: -1 | 1) {
  if (!active.value) return;
  const siblings = active.value.entries
    .filter((entry) => entry.node === node)
    .sort((a, b) => a.position - b.position);
  const index = siblings.findIndex((entry) => entry.id === entryId);
  const target = index + offset;
  if (index < 0 || target < 0 || target >= siblings.length) return;
  const ordered = siblings.map((entry) => entry.id);
  [ordered[index], ordered[target]] = [ordered[target], ordered[index]];
  await reorder("entries", ordered, node);
}

/**
 * 后端 reorder 只接受「同一父节点下的完整顺序」，因此跨节点拖动不被支持——
 * 拖拽过程中就把不可落的项标灰，落下时给一句明确提示，而不是静默失败。
 */
function canDropEntryOn(target: CollectionEntrySummary): boolean {
  if (dragEntryId.value === null) return true;
  if (dragEntryId.value === target.id) return false;
  const dragged = active.value?.entries.find((entry) => entry.id === dragEntryId.value);
  return Boolean(dragged) && dragged?.node === target.node;
}

function onEntryDragStart(entry: CollectionEntrySummary, event: DragEvent) {
  if (saving.value || !active.value) {
    event.preventDefault();
    return;
  }
  dragEntryId.value = entry.id;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move";
    // 部分浏览器要求写入数据才触发 drop 事件。
    event.dataTransfer.setData("text/plain", String(entry.id));
  }
}

function onEntryDragOver(entry: CollectionEntrySummary, event: DragEvent) {
  if (dragEntryId.value === null) return;
  if (!canDropEntryOn(entry)) {
    if (event.dataTransfer) event.dataTransfer.dropEffect = "none";
    dropEntryId.value = null;
    return;
  }
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  dropPosition.value = event.clientY < rect.top + rect.height / 2 ? "before" : "after";
  dropEntryId.value = entry.id;
}

function onEntryDragLeave(entry: CollectionEntrySummary) {
  if (dropEntryId.value === entry.id) dropEntryId.value = null;
}

function onEntryDragEnd() {
  dragEntryId.value = null;
  dropEntryId.value = null;
}

async function onEntryDrop(target: CollectionEntrySummary) {
  const dragId = dragEntryId.value;
  const position = dropPosition.value;
  dragEntryId.value = null;
  dropEntryId.value = null;
  if (dragId === null || dragId === target.id || !active.value) return;

  const dragged = active.value.entries.find((entry) => entry.id === dragId);
  if (!dragged) return;
  if (dragged.node !== target.node) {
    ElMessage.warning("暂不支持跨节点拖动：可先移除，再挂到目标节点重新加入。");
    return;
  }

  // 只重排目标节点下的兄弟项；筛选隐藏的条目在 moveEntryRelative 中保持相对顺序。
  const siblings = sortEntriesByPosition(active.value.entries.filter((entry) => entry.node === target.node));
  const before = siblings.map((entry) => entry.id);
  const ordered = moveEntryRelative(before, dragId, target.id, position);
  if (isSameOrder(before, ordered)) return;
  await reorder("entries", ordered, target.node);
}

async function reorder(scope: "nodes" | "entries", orderedIds: number[], parentId: number | null) {
  if (!active.value) return;
  saving.value = true;
  error.value = "";
  try {
    await post(`/api/agent/blog/collections/${active.value.public_id}/reorder/`, {
      scope,
      parent_id: parentId,
      ordered_ids: orderedIds,
      expected_version: active.value.draft_version,
    });
    saveStatus.value = "顺序已保存。";
    await openDraft({ public_id: active.value.public_id } as CollectionDraft);
    void loadList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "排序失败";
  } finally {
    saving.value = false;
  }
}

async function submitForApproval() {
  if (!active.value) return;
  submitting.value = true;
  error.value = "";
  try {
    const result = await requestJson<{ approval_id: number; status: string; detail: string }>(
      `/api/agent/blog/collections/${active.value.public_id}/submit/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
    );
    saveStatus.value = typeof result.detail === "string" ? result.detail : "已提交审核。";
    ElMessage.success("已提交审核");
    await openDraft({ public_id: active.value.public_id } as CollectionDraft);
    void loadList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "提交失败";
  } finally {
    submitting.value = false;
  }
}

async function archiveCollection(item: CollectionDraft) {
  try {
    await ElMessageBox.confirm(
      item.is_published
        ? "归档后该领域将从公开列表移除（私有数据保留）。是否继续？"
        : "删除后私有草稿不可恢复。是否继续？",
      item.is_published ? "归档领域" : "删除草稿",
      { type: "warning", confirmButtonText: "确认", cancelButtonText: "取消" },
    );
  } catch {
    return;
  }
  try {
    const result = await requestJson<{ archived: boolean; detail: string }>(
      `/api/agent/blog/collections/${item.public_id}/draft/`,
      { method: "DELETE" },
    );
    ElMessage.success(result.detail);
    if (active.value?.public_id === item.public_id) active.value = null;
    await loadList();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "操作失败";
  }
}

const statusLabel = (item: CollectionDraft) => {
  if (item.archived_at) return "已归档";
  if (item.has_pending) return "待审";
  if (item.is_published) return `已公开 v${item.publication_version}`;
  return "私有草稿";
};

async function loadTags() {
  try {
    tags.value = await requestJson<BlogTag[]>("/api/agent/blog/tags/");
  } catch {
    tags.value = [];
  }
}

onMounted(() => {
  void loadList();
  void loadCategories();
  void loadTags();
  void searchArticles();
});

onBeforeUnmount(() => {
  window.clearTimeout(highlightTimer);
});
</script>

<template>
  <section class="manager-page">
    <header class="manager-head">
      <h2>我的领域</h2>
      <p>私有工作版可自由编辑；提交后由管理员审核，批准前公开版保持不变。</p>
    </header>

    <el-alert v-if="error" type="error" :title="error" :closable="false" />

    <div class="manager-create">
      <el-input
        v-model="newTitle"
        placeholder="新领域标题，如：算法"
        aria-label="新领域标题"
        maxlength="120"
        @keyup.enter="createCollection"
      />
      <el-input
        v-model="newDescription"
        placeholder="领域简介（可选）"
        aria-label="新领域简介"
        maxlength="500"
        @keyup.enter="createCollection"
      />
      <el-button type="primary" :icon="Plus" :loading="creating" @click="createCollection">创建领域</el-button>
    </div>

    <div class="manager-list">
      <div v-if="collections.length" class="list-toolbar">
        <el-input
          v-model="listFilter"
          size="small"
          placeholder="按标题筛选我的领域"
          clearable
          aria-label="筛选我的领域"
          class="filter-input"
        />
        <span class="section-hint">
          共 {{ collections.length }} 个领域{{ listFilter ? `，匹配 ${visibleCollections.length} 个` : "" }}
        </span>
        <span class="toolbar-spacer" />
        <el-checkbox
          :model-value="allVisibleSelected"
          :disabled="!visibleCollections.length"
          aria-label="全选当前领域"
          @change="toggleSelectAll"
        >
          全选
        </el-checkbox>
        <el-button size="small" :loading="exportBusy" :disabled="!selectedCount" @click="exportSelected">
          导出所选{{ selectedCount ? `（${selectedCount}）` : "" }}
        </el-button>
        <el-button size="small" type="primary" plain @click="openImportDialog">导入压缩包</el-button>
      </div>
      <p v-if="loading" role="status">正在加载…</p>
      <el-empty v-else-if="!collections.length" description="还没有领域草稿，先创建一个吧" />
      <el-empty v-else-if="!visibleCollections.length" description="没有匹配的领域" />
      <table v-else class="manager-table" aria-label="我的领域列表">
        <thead>
          <tr><th class="col-check">导出</th><th>标题</th><th>状态</th><th>最近审核</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in visibleCollections" :key="item.public_id">
            <td class="col-check">
              <el-checkbox
                :model-value="isSelected(item.public_id)"
                :aria-label="`选择领域 ${item.title}`"
                @change="(value: boolean) => toggleSelect(item.public_id, value)"
              />
            </td>
            <td>{{ item.title }}</td>
            <td>
              <el-tag size="small" :type="item.is_published ? 'success' : item.has_pending ? 'warning' : 'info'">{{ statusLabel(item) }}</el-tag>
            </td>
            <td class="review-note">
              <template v-if="item.last_review && item.last_review.status === 'rejected'">
                被拒：{{ item.last_review.review_note || item.last_review.result || "无说明" }}
              </template>
              <template v-else-if="item.pending">审核中</template>
              <template v-else><span class="review-empty">—</span></template>
            </td>
            <td class="row-actions">
              <el-button size="small" type="primary" plain @click="openDraft(item)">编辑</el-button>
              <el-button size="small" plain :loading="exportBusy" @click="exportOne(item)">导出</el-button>
              <el-button size="small" type="danger" plain @click="archiveCollection(item)">{{ item.is_published ? "归档" : "删除" }}</el-button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <section v-if="active" ref="editorRef" class="editor">
      <el-divider />
      <header class="editor-head">
        <h3>编辑：{{ active.title }} <el-tag size="small">{{ statusLabel(active) }}</el-tag></h3>
        <p class="save-status" role="status">
          {{ saveStatus || `工作版 v${active.draft_version}` }}
          <span class="section-hint"> · {{ active.nodes.length }} 个节点 · {{ active.entries.length }} 篇文章</span>
        </p>
      </header>

      <div class="editor-fields">
        <el-input
          :model-value="active.title"
          aria-label="领域标题"
          maxlength="120"
          @change="patchCollection({ title: $event })"
        />
        <el-input
          :model-value="active.description"
          type="textarea"
          :rows="2"
          aria-label="领域简介"
          maxlength="500"
          @change="patchCollection({ description: $event })"
        />
      </div>

      <div class="editor-section">
        <div class="section-head">
          <h4>目录节点（领域根下最多三级）</h4>
          <span class="section-hint">{{ nodeRows.length }} / {{ active.nodes.length }} 个可见</span>
        </div>

        <div class="node-create">
          <el-select v-model="newNodeParent" placeholder="父节点（不选=领域根）" aria-label="父节点" class="parent-select">
            <el-option label="领域根" :value="''" />
            <el-option v-for="node in nodeOptions" :key="node.id" :label="nodeName(node.id)" :value="node.id" :disabled="node.depth >= 2" />
          </el-select>
          <el-input ref="nodeTitleInputRef" v-model="newNodeTitle" placeholder="节点标题" aria-label="节点标题" maxlength="120" @keyup.enter="createNode" />
          <el-input v-model="newNodeDescription" placeholder="节点说明（可选）" aria-label="节点说明" maxlength="500" @keyup.enter="createNode" />
          <el-button type="primary" :loading="saving" @click="createNode">添加节点</el-button>
        </div>

        <div v-if="active.nodes.length" class="tree-toolbar">
          <el-input
            v-model="nodeFilter"
            size="small"
            placeholder="按标题筛选节点"
            clearable
            aria-label="筛选节点"
            class="filter-input"
          />
          <el-button size="small" text :disabled="allNodesCollapsed" @click="collapseAllNodes">全部折叠</el-button>
          <el-button size="small" text :disabled="!collapsedNodes.size" @click="expandAllNodes">全部展开</el-button>
        </div>

        <div v-if="nodeRows.length" class="scroll-box">
          <ul class="node-tree" aria-label="节点列表">
            <li
              v-for="row in nodeRows"
              :id="`manager-node-${row.node.id}`"
              :key="row.node.id"
              class="node-row tree-row"
              :class="{ 'is-highlight': highlightNodeId === row.node.id }"
              :style="{ paddingLeft: `${8 + (row.depth - 1) * 18}px` }"
            >
              <button
                v-if="row.hasChildren"
                class="tree-fold"
                :aria-expanded="!collapsedNodes.has(row.node.id)"
                :aria-label="`${collapsedNodes.has(row.node.id) ? '展开' : '折叠'} ${row.node.title}`"
                @click="toggleNodeCollapse(row.node.id)"
              >{{ collapsedNodes.has(row.node.id) ? "▸" : "▾" }}</button>
              <span v-else class="tree-fold-placeholder" aria-hidden="true"></span>

              <span class="node-name">
                {{ row.node.title }}
                <small v-if="row.hasChildren" class="node-meta">· {{ row.childCount }} 个子节点</small>
              </span>
              <span class="node-actions">
                <el-button size="small" text :disabled="saving" aria-label="在此节点下添加子节点" title="在此节点下添加子节点" @click="startChildNode(row.node.id)">+ 子节点</el-button>
                <el-button size="small" text :disabled="saving" aria-label="上移节点" @click="moveNodeUp(row.node.id, row.node.parent)">↑</el-button>
                <el-button size="small" text :disabled="saving" aria-label="下移节点" @click="moveNodeDown(row.node.id, row.node.parent)">↓</el-button>
                <el-button size="small" text @click="renameNode(row.node.id, row.node.title)">重命名</el-button>
                <el-button size="small" text type="danger" :disabled="saving" @click="deleteNode(row.node.id)">删除</el-button>
              </span>
            </li>
          </ul>
        </div>
        <p v-if="!active.nodes.length" class="empty-hint">还没有节点。先建一门“课程”，再在课程下建“章节”和“知识点”。</p>
        <p v-else-if="!nodeRows.length" class="empty-hint">没有匹配「{{ nodeFilter }}」的节点。</p>
      </div>

      <div class="editor-section">
        <div class="section-head">
          <h4>加入已发布文章</h4>
          <span class="section-hint">已加入 {{ active.entries.length }} 篇</span>
        </div>

        <div class="entry-create">
          <el-select v-model="entryNode" placeholder="挂到哪个节点（不选=领域根）" aria-label="文章挂载节点" class="parent-select">
            <el-option label="领域根" :value="''" />
            <el-option v-for="node in nodeOptions" :key="node.id" :label="nodeName(node.id)" :value="node.id" />
          </el-select>
          <el-select
            v-model="articleCategory"
            placeholder="按分类筛选（可选）"
            aria-label="按分类筛选文章"
            class="category-select"
            clearable
            @change="searchArticles"
          >
            <el-option
              v-for="category in categoryOptions"
              :key="category.slug"
              :label="`${category.name}（${category.article_count} 篇）`"
              :value="category.slug"
            />
          </el-select>
          <el-input v-model="articleQuery" placeholder="按标题搜索已发布文章" aria-label="搜索文章" @keyup.enter="searchArticles" />
          <el-button :loading="articleLoading" @click="searchArticles">搜索</el-button>
        </div>

        <div class="entry-pick">
          <el-select
            v-model="selectedArticleIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            :max-collapse-tags="3"
            placeholder="选择文章（可多选，输入关键词过滤）"
            aria-label="选择文章（可多选）"
            class="article-select"
          >
            <el-option
              v-for="article in articleOptions"
              :key="article.id"
              :label="`${article.title}（${article.category?.name ?? '未分类'} · ${article.author_name}）`"
              :value="article.id"
              :disabled="collectedArticleIds.includes(article.id)"
            />
          </el-select>
          <el-button
            type="primary"
            :loading="saving"
            :disabled="!pendingAddIds.length"
            @click="addEntries"
          >
            {{ pendingAddIds.length ? `加入所选 ${pendingAddIds.length} 篇` : "加入所选" }}
          </el-button>
          <el-button :disabled="!articleOptions.length" @click="selectAllVisibleArticles">全选当前结果</el-button>
          <span class="section-hint">
            {{ articleLoading ? "搜索中…" : `匹配 ${articleTotal} 篇，已载入 ${articleOptions.length} 篇` }}
          </span>
        </div>

      <div class="editor-section">
        <div class="section-head">
          <h4>自动收录规则</h4>
          <span class="section-hint">
            {{
              autoRules.length
                ? `${autoRules.filter((rule) => rule.enabled).length} / ${autoRules.length} 条启用`
                : "还没有规则"
            }}
          </span>
        </div>
        <p class="rule-tip">
          指定分类（可选再限定标签）后，凡是已发布且命中的文章都会自动挂到目标节点下：打开本页或提交审核时自动补齐，已收录的文章不会重复加入。
        </p>

        <div class="rule-create">
          <el-select
            v-model="ruleNode"
            placeholder="挂到哪个节点（不选=领域根）"
            aria-label="规则目标节点"
            class="parent-select"
          >
            <el-option label="领域根" :value="''" />
            <el-option v-for="node in nodeOptions" :key="node.id" :label="nodeName(node.id)" :value="node.id" />
          </el-select>
          <el-select
            v-model="ruleCategory"
            placeholder="选择分类（必填）"
            aria-label="规则分类"
            class="category-select"
            clearable
          >
            <el-option
              v-for="category in categoryOptions"
              :key="category.id"
              :label="`${category.name}（${category.article_count} 篇）`"
              :value="category.id"
            />
          </el-select>
          <el-select
            v-model="ruleTag"
            placeholder="限定标签（可选）"
            aria-label="规则标签"
            class="category-select"
            clearable
          >
            <el-option
              v-for="tag in tagOptions"
              :key="tag.id"
              :label="`${tag.name}（${tag.article_count} 篇）`"
              :value="tag.id"
            />
          </el-select>
          <el-button
            type="primary"
            :loading="ruleSaving"
            :disabled="!canCreateRule(ruleCategory) || ruleDuplicate"
            @click="addAutoRule"
          >
            {{ ruleDuplicate ? "规则已存在" : "添加规则" }}
          </el-button>
        </div>

        <ul v-if="autoRules.length" class="rule-list" aria-label="自动收录规则列表">
          <li v-for="rule in autoRules" :key="rule.id" class="rule-row" :class="{ 'is-disabled': !rule.enabled }">
            <span class="rule-label">{{ autoRuleLabel(rule) }}</span>
            <span class="section-hint">
              {{ rule.last_applied_at ? `上次同步 ${formatRuleTime(rule.last_applied_at)}` : "尚未同步" }}
            </span>
            <span class="node-actions">
              <el-switch
                :model-value="rule.enabled"
                :disabled="ruleSaving"
                aria-label="启用规则"
                @change="(value: boolean | string | number) => setAutoRuleEnabled(rule, Boolean(value))"
              />
              <el-button size="small" text type="danger" :disabled="ruleSaving" @click="removeAutoRule(rule)">
                删除
              </el-button>
            </span>
          </li>
        </ul>

        <div v-if="autoRules.length" class="rule-actions">
          <el-button size="small" :loading="saving" @click="syncAutoRules">立即同步新文章</el-button>
          <span class="section-hint">没有新发布的匹配文章时，同步不会产生任何变化</span>
        </div>
      </div>

        <div v-if="active.entries.length" class="tree-toolbar">
          <el-input
            v-model="entryFilter"
            size="small"
            placeholder="筛选已加入文章"
            clearable
            aria-label="筛选已加入文章"
            class="filter-input"
          />
          <span class="section-hint">
            {{ visibleEntries.length }} / {{ active.entries.length }} 篇可见 · 按住条目可直接拖动排序（同一节点内）
          </span>
        </div>

        <div v-if="visibleEntries.length" class="scroll-box">
          <ul class="entry-list" aria-label="目录文章列表">
            <li
              v-for="entry in visibleEntries"
              :key="entry.id"
              class="node-row entry-row"
              :class="{
                'is-dragging': dragEntryId === entry.id,
                'is-drop-before': dropEntryId === entry.id && dropPosition === 'before',
                'is-drop-after': dropEntryId === entry.id && dropPosition === 'after',
                'is-drop-blocked': dragEntryId !== null && !canDropEntryOn(entry),
              }"
              :draggable="!saving"
              :aria-grabbed="dragEntryId === entry.id"
              @dragstart="onEntryDragStart(entry, $event)"
              @dragover.prevent="onEntryDragOver(entry, $event)"
              @dragleave="onEntryDragLeave(entry)"
              @drop.prevent="onEntryDrop(entry)"
              @dragend="onEntryDragEnd"
            >
              <span class="entry-grip" aria-hidden="true" title="按住拖动可排序">⋮⋮</span>
              <span class="node-name">
                <span class="entry-node">{{ nodeName(entry.node).trim() }}</span>
                · <strong>{{ entry.article.title }}</strong>
                <small>（{{ entry.article.author_name }}{{ entry.article.status !== "published" ? " · 已下架" : "" }}）</small>
              </span>
              <span class="node-actions">
                <el-button size="small" text :disabled="saving" aria-label="上移文章" @click="moveEntry(entry.id, entry.node, -1)">↑</el-button>
                <el-button size="small" text :disabled="saving" aria-label="下移文章" @click="moveEntry(entry.id, entry.node, 1)">↓</el-button>
                <el-button size="small" text type="danger" :disabled="saving" @click="removeEntry(entry.id)">移除</el-button>
              </span>
            </li>
          </ul>
        </div>
        <p v-if="!active.entries.length" class="empty-hint">还没有文章。可以从本站已发布文章中选择加入。</p>
        <p v-else-if="!visibleEntries.length" class="empty-hint">没有匹配「{{ entryFilter }}」的文章。</p>
      </div>

      <div class="submit-row">
        <p v-if="active.pending">当前版本待审中，批准前公开版保持不变。</p>
        <p v-else-if="active.last_review && active.last_review.status === 'rejected'" class="reject-note">
          上次被拒：{{ active.last_review.review_note || active.last_review.result || "无说明" }}；可修改后重新提交。
        </p>
        <el-button type="primary" :loading="submitting" @click="submitForApproval">提交审核公开</el-button>
      </div>
    </section>

    <CollectionArchiveDialog
      v-model:open="importDialog"
      v-model:conflict="importConflict"
      :file="importFile"
      :plan="importPlan"
      :busy="importBusy"
      :applying="importApplying"
      :summary="importSummary"
      @pick-file="pickImportFile"
      @apply="applyImport"
    />
  </section>
</template>

<style scoped>
.manager-page {
  max-width: 980px;
  margin: calc(-1 * var(--page-bleed-block)) auto;
  padding: var(--space-6) 0;
  box-sizing: border-box;
  /* 高度锁定：编辑区过长时由本页统一滚动，节点/文章列表另有限高的滑动框。 */
  height: var(--page-available-height);
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  scrollbar-gutter: stable;
}
/* 限高容器里的 flex 子项默认会被压扁而不是撑出滚动条，统一禁止收缩。 */
.manager-page > * { flex: none; }
.manager-head h2 { margin: 0; }
.manager-head p { margin: 4px 0 0; color: #63716e; font-size: 14px; }
/* 创建区：白底卡片分组，与下方列表形成同一「面板」语言，操作层级更清晰 */
.manager-create {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 10px;
  align-items: center;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-bg-surface);
  padding: 14px 16px;
  box-shadow: var(--shadow-sm);
}
.manager-list {
  border: 1px solid var(--color-border);
  border-radius: 10px;
  background: var(--color-bg-surface);
  padding: 14px 18px 18px;
  box-shadow: var(--shadow-sm);
}
.manager-table { width: 100%; border-collapse: collapse; font-size: 14px; }
/* 表头小字距 + 去掉双线；行距放宽、hover 反馈，行内信息更好扫读 */
.manager-table th {
  padding: 8px 10px 10px;
  border-bottom: 1px solid var(--color-divider);
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-align: left;
}
.manager-table td { border-bottom: 1px solid #eef2f1; padding: 13px 10px; text-align: left; }
.manager-table tbody tr:last-child td { border-bottom: 0; }
.manager-table tbody tr { transition: background var(--transition-fast); }
.manager-table tbody tr:hover { background: #f7faf9; }
.review-note { color: #b25e5e; max-width: 320px; overflow-wrap: anywhere; }
.review-empty { color: #b9c2bf; }
.row-actions { white-space: nowrap; }
.col-check { width: 56px; }
.toolbar-spacer { flex: 1 1 auto; }
.list-toolbar, .tree-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.filter-input { max-width: 240px; }
.section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.section-hint { color: #8a9793; font-size: 12px; }
.editor { scroll-margin-top: 16px; display: grid; gap: 14px; }
.editor-head h3 { margin: 0; display: flex; align-items: center; gap: 8px; }
.save-status { margin: 4px 0 0; color: #63716e; font-size: 13px; }
.editor-fields { display: grid; gap: 8px; }
.editor-section { display: grid; gap: 8px; }
.editor-section h4 { margin: 0; }
.node-create, .entry-create, .entry-pick, .rule-create { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.parent-select { width: 240px; }
.category-select { width: 220px; }
.article-select { min-width: 280px; flex: 1; }
.entry-list, .node-tree { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.node-row { display: flex; justify-content: space-between; gap: 10px; border: 1px solid #edf1f0; border-radius: 8px; padding: 6px 10px; align-items: center; }
.tree-row { transition: background-color 0.4s ease, border-color 0.4s ease; }
.tree-row.is-highlight { background: #fff8e1; border-color: #e6c96a; }
.tree-fold { border: none; background: none; cursor: pointer; padding: 0 4px; color: #63716e; flex: none; }
.tree-fold-placeholder { display: inline-block; width: 17px; flex: none; }
.node-name { min-width: 0; overflow-wrap: anywhere; flex: 1; }
.node-meta { color: #8a9793; }
.entry-node { color: #1f6f54; }
/* 拖拽排序（B-064）：抓手提示 + 拖动中 / 落点高亮 / 不可落灰显 */
.entry-row { cursor: grab; }
.entry-grip { flex: none; color: #b6c0bd; letter-spacing: -2px; user-select: none; }
.entry-row:hover .entry-grip { color: #63716e; }
.entry-row.is-dragging { opacity: 0.45; cursor: grabbing; background: #f4f7f6; }
.entry-row.is-drop-before { border-top: 2px solid #1f6f54; }
.entry-row.is-drop-after { border-bottom: 2px solid #1f6f54; }
.entry-row.is-drop-blocked { opacity: 0.4; cursor: not-allowed; }
.node-actions { white-space: nowrap; flex: none; }
.empty-hint { margin: 0; color: #8a9793; font-size: 13px; }
/* 自动收录规则（B-065） */
.rule-tip { margin: 0; color: #63716e; font-size: 13px; line-height: 1.6; }
.rule-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.rule-row { display: flex; align-items: center; gap: 10px; border: 1px solid #edf1f0; border-radius: 8px; padding: 6px 10px; }
.rule-row.is-disabled { background: #f7f9f8; }
.rule-row.is-disabled .rule-label { color: #9aa6a2; text-decoration: line-through; }
.rule-label { flex: 1; min-width: 0; overflow-wrap: anywhere; font-size: 14px; }
.rule-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.submit-row { display: grid; gap: 8px; justify-items: start; }
.reject-note { color: #b25e5e; margin: 0; }

/* 节点/文章列表过长时收进可滑动区域，避免编辑区被无限拉长 */
.scroll-box { max-height: 320px; overflow-y: auto; border: 1px solid #edf1f0; border-radius: 10px; padding: 6px; }

@media (max-width: 720px) {
  .manager-page { height: auto; min-height: var(--page-available-height); margin: 0; padding: 0; overflow: visible; }
  .manager-create { grid-template-columns: 1fr; }
  .manager-list { padding: 12px 12px 14px; }
  .parent-select, .category-select, .filter-input { width: 100%; max-width: none; }
  .scroll-box { max-height: 260px; }
}
</style>
