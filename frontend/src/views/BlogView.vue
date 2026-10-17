<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  Refresh,
  Search,
  Loading,
} from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import "md-editor-v3/lib/style.css";
import { RouterLink, onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import BlogSidebar from "../features/blog/components/BlogSidebar.vue";
import BlogAgentWidget from "../features/blog/components/BlogAgentWidget.vue";
import BlogWriter from "../features/blog/components/BlogWriter.vue";
import HtmlImportDialog from "../features/blog/components/HtmlImportDialog.vue";
import ArticleDetail from "../features/blog/components/ArticleDetail.vue";
import ArticleList from "../features/blog/components/ArticleList.vue";
import PrivateNotesDrawer from "../features/blog/components/PrivateNotesDrawer.vue";
import type {
  ApprovalRequest,
  ArchiveGroup,
  BlogAgentChatMessage,
  BlogArticle,
  BlogComment,
  BlogDraft,
  BlogCategory,
  BlogTag,
  CollectionArticleContext,
  WritingAssistantRequest,
  WritingAssistantResult
} from "../features/blog/types";
import type { ParsedMarkdown } from "../features/blog/utils/parseMarkdownFile";
import { normalizeTagList } from "../features/blog/utils/tagInput";
import { defaultCoverImage } from "../features/blog/utils/articleCover";
import {
  clearWebClipFragment,
  consumeWebClip,
  readWebClipFragment,
} from "../features/blog/utils/webClipHandoff";
import type { WebClipNoteDraft } from "../features/blog/components/PrivateNotesDrawer.vue";
import ScreenshotOcrDialog, { type ScreenshotJobInput } from "../features/blog/components/ScreenshotOcrDialog.vue";
import {
  clearScreenshotFragment,
  consumeScreenshotHandoff,
  readScreenshotFragment,
} from "../features/blog/utils/screenshotHandoff";

import {
  getDraftCacheStatus,
  getDraftOwner,
  getVditorCacheId,
  getWriterContextStorageKey,
  readWriterContext,
  readWriterDraft,
  removeWriterDraft,
  saveWriterContext,
  saveWriterDraft,
  type DraftOwner,
  type WriterContext
} from "../features/blog/utils/draftStorage";

const auth = useAuthStore();

const route = useRoute();
const router = useRouter();

const articles = ref<BlogArticle[]>([]);
const currentArticle = ref<BlogArticle | null>(null);
const articleDetailRef = ref<InstanceType<typeof ArticleDetail> | null>(null);
onBeforeRouteUpdate(() => articleDetailRef.value?.confirmLeave() ?? true);
onBeforeRouteLeave(() => articleDetailRef.value?.confirmLeave() ?? true);
const tags = ref<BlogTag[]>([]);
const categories = ref<BlogCategory[]>([]);
const archive = ref<ArchiveGroup[]>([]);
const about = ref<{ title: string; content: string; highlights: string[]; author_name?: string } | null>(null);
const siteSettings = ref<{ site_title: string; site_tagline: string; footer_text: string } | null>(null);
const loading = ref(false);
const publishing = ref(false);
const submittingComment = ref(false);
const uploadingImage = ref(false);
const deletingArticleSlug = ref("");
const editorError = ref("");
const writerContext = ref<WriterContext | null>(null);
const writerOwner = ref<DraftOwner | null>(null);
const writerTabId = ref("");
const draftSaveStatus = ref("草稿仅保存在本机浏览器；登录后可按账号、工作空间和文章隔离恢复。");
const draftConflict = ref(false);
const restoringWriter = ref(false);
const browserOnline = ref(navigator.onLine);
let articleLoadSequence = 0;
let conflictListener: ((event: StorageEvent) => void) | null = null;
const approvalDialogOpen = ref(false);
const pendingApproval = ref<ApprovalRequest | null>(null);
const reviewingApproval = ref(false);
const reviewer = ref("admin");
const reviewNote = ref("");
const blogAgentOpen = ref(false);
const blogAgentLoading = ref(false);
const blogAgentInput = ref("这个博客项目的技术栈是什么？");
const blogAgentSource = ref<"legacy" | "ragagent">(
  localStorage.getItem("blogAgentSource") === "ragagent" ? "ragagent" : "legacy"
);
const blogAgentSessionKey = ref(localStorage.getItem("blogAgentSessionKey") || "");
const blogAgentMessages = ref<BlogAgentChatMessage[]>([
  {
    role: "agent",
    content: "你好，我是这个博客里的智能体。你可以问公开文章、项目经历、技术栈、LangGraph 或 Agentic RAG。"
  }
]);
const blogAgentSuggestions = ["你做过哪些 LangGraph 项目？", "这个项目架构是什么？", "Agentic RAG 是怎么实现的？"];
const commentDraft = ref({
  content: ""
});
interface ModerationComment {
  id: number;
  article_title: string;
  author_name: string;
  content: string;
  quote: string;
  created_at: string;
}
interface ModerationReport {
  id: number;
  comment_id: number;
  article_title: string;
  comment_content: string;
  reporter_name: string;
  reason: string;
  detail: string;
  created_at: string;
}
interface InteractionRestriction {
  id: number;
  username: string;
  reason: string;
  expires_at: string;
  created_at: string;
  active: boolean;
  appeal_status: "none" | "pending" | "upheld" | "accepted";
  appeal_message: string;
  imposed_by?: string;
}
const moderationOpen = ref(false);
const moderationStatus = ref<"pending" | "approved" | "reports" | "restrictions">("approved");
const moderationComments = ref<ModerationComment[]>([]);
const moderationReports = ref<ModerationReport[]>([]);
const moderationRestrictions = ref<InteractionRestriction[]>([]);
const moderationLoading = ref(false);
const restrictionUsername = ref("");
const restrictionReason = ref("");
const restrictionDays = ref(3);
const restricting = ref(false);
const reviewingRestrictionId = ref<number | null>(null);
const myRestriction = ref<InteractionRestriction | null>(null);
const restrictionDialogOpen = ref(false);
const appealMessage = ref("");
const appealing = ref(false);
const moderatingCommentId = ref<number | null>(null);
const reviewingReportId = ref<number | null>(null);
const reportDialogOpen = ref(false);
const reportTarget = ref<BlogComment | null>(null);
const reportReason = ref("spam");
const reportDetail = ref("");
const submittingReport = ref(false);
const myPendingArticles = ref<BlogArticle[]>([]);
const myPublishedArticles = ref<BlogArticle[]>([]);
const authorName = ref(localStorage.getItem("blogAuthorName") || "");
const myArticlesLoading = ref(false);
const editingArticle = ref<BlogArticle | null>(null);
const updatingArticle = ref(false);
const relatedArticles = ref<BlogArticle[]>([]);
const relatedLoading = ref(false);
const collectionContext = ref<CollectionArticleContext | null>(null);
const htmlClipFile = ref<File | null>(null);
const noteClipFile = ref<File | null>(null);
const noteClipApplying = ref(false);
const webClipSource = ref<{ sourceUrl: string; title: string; site: string; ownNote: string; captureTarget: string } | null>(null);
const webClipNoteDraft = ref<WebClipNoteDraft | null>(null);
/** B-045：截图识别对话框（本地 OCR + 校对），写作台与私有笔记抽屉都可打开。 */
const screenshotOcrOpen = ref(false);
const screenshotOcrJob = ref<ScreenshotJobInput | null>(null);
const clipStatus = ref<{ kind: "ok" | "error" | "info"; text: string } | null>(null);
const activeCategory = ref("");
const activeTag = ref("");
const articleTotal = ref(0);
const articlePage = ref(1);
const articlePages = ref(0);
const articlePageSize = ref(12);
const myOnly = ref(false);
let discoveryLoadSequence = 0;
const showWriter = ref(false);
const showMyArticles = ref(false);
const showPrivateNotes = ref(false);
const noteSourceArticle = ref<BlogArticle | null>(null);
const noteQuote = ref("");

async function openPrivateNotes(article: BlogArticle | null = null, quote = "") {
  noteSourceArticle.value = article;
  noteQuote.value = quote;
  await nextTick();
  showPrivateNotes.value = true;
}
const searchQuery = ref("");
const writingAssistantLoading = ref(false);
const writingAssistantError = ref("");
const writingAssistantResult = ref<WritingAssistantResult | null>(null);

const libraryArticleCount = computed(() => {
  const categorizedCount = categories.value.reduce((total, item) => total + item.article_count, 0);
  return Math.max(articleTotal.value, categorizedCount);
});

const draft = ref<BlogDraft>(emptyBlogDraft());

function emptyBlogDraft(): BlogDraft {
  return { title: "", summary: "", cover_image: "", category: "", tags: [], content: "" };
}

const noteTemplates = [
  {
    name: "项目复盘",
    content: "## 背景\n\n## 目标\n\n## 技术方案\n\n## 关键实现\n\n## 遇到的问题\n\n## 复盘总结\n"
  },
  {
    name: "论文笔记",
    content: "## 论文信息\n\n## 核心问题\n\n## 方法概述\n\n## 实验结论\n\n## 可借鉴点\n"
  },
  {
    name: "技术方案",
    content: "## 需求\n\n## 架构设计\n\n## 数据模型\n\n## API 设计\n\n## 风险与取舍\n\n## 下一步\n"
  }
];

const editorStats = computed(() => {
  const plain = draft.value.content.replace(/```[\s\S]*?```/g, "").replace(/[#>*_\-\[\]()`]/g, "");
  const compact = plain.replace(/\s+/g, "");
  const englishWords = plain.match(/[A-Za-z0-9]+/g)?.length ?? 0;
  const count = compact.length + englishWords;

  const headingLines = draft.value.content
    .split("\n")
    .filter((line) => /^#{1,3}\s+/.test(line));

  const headings = headingLines.map((line) => line.replace(/^#{1,3}\s+/, "").trim());

  const headingItems = headingLines.map((line) => {
    const match = line.match(/^(#{1,3})\s+(.*)/);
    return {
      level: match ? match[1].length : 1,
      text: match ? match[2].trim() : line.trim()
    };
  });

  return {
    words: count,
    readingMinutes: Math.max(1, Math.ceil(count / 450)),
    headings,
    headingItems
  };
});

const activeSlug = computed(() => String(route.params.slug ?? ""));
const articleListScrollY = ref(0);
function routeFilter(name: string): string {
  const value = route.query[name];
  return String(Array.isArray(value) ? value[0] ?? "" : value ?? "").trim();
}

function syncDiscoveryState() {
  searchQuery.value = routeFilter("q");
  activeCategory.value = routeFilter("category");
  activeTag.value = routeFilter("tag");
  myOnly.value = routeFilter("my") === "1" && auth.isAuthenticated;
  const requestedPage = Number(routeFilter("page"));
  articlePage.value = Number.isInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;
}

watch(() => route.query, () => {
  syncDiscoveryState();
  if (!activeSlug.value) void loadArticles();
});
const authenticatedDraftOwner = computed(() => getDraftOwner(auth.session.actor, auth.session.workspace_key));
const editorCacheId = computed(() => writerOwner.value && writerContext.value
  ? getVditorCacheId(writerOwner.value, writerContext.value)
  : "blog-v2-unavailable");
const writerComponentKey = computed(() => `${editorCacheId.value}:${writerContext.value?.kind ?? "none"}`);
const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);
const storedRightWidth = Number(localStorage.getItem("blogLayoutRightWidth"));
const rightPanelVisible = ref(localStorage.getItem("blogLayoutRightVisible") !== "false");
const rightPanelWidth = ref(clamp(Number.isFinite(storedRightWidth) && storedRightWidth > 0 ? storedRightWidth : 360, 260, 560));
const resizingPanel = ref<"right" | null>(null);
const clearingDraft = ref(false);
const blogLayoutStyle = computed(() => ({
  "--blog-panel-width": `${rightPanelWidth.value}px`
}));

function resizePanels(event: PointerEvent) {
  if (resizingPanel.value === "right") {
    const nextWidth = window.innerWidth - event.clientX;
    if (nextWidth <= 210) {
      rightPanelVisible.value = false;
      stopPanelResize();
      return;
    }
    rightPanelWidth.value = clamp(nextWidth, 260, 560);
  }
}

function stopPanelResize() {
  if (!resizingPanel.value) return;
  resizingPanel.value = null;
  document.body.classList.remove("blog-panel-resizing");
  window.removeEventListener("pointermove", resizePanels);
  window.removeEventListener("pointerup", stopPanelResize);
}

function startPanelResize(panel: "right", event: PointerEvent) {
  if (window.matchMedia("(max-width: 980px)").matches) return;
  resizingPanel.value = panel;
  document.body.classList.add("blog-panel-resizing");
  window.addEventListener("pointermove", resizePanels);
  window.addEventListener("pointerup", stopPanelResize);
  event.preventDefault();
}

onMounted(async () => {
  syncDiscoveryState();
  await restoreWriterSession();
  await Promise.all([loadArticles(), loadTags(), loadCategories(), loadArchive(), loadAbout()]);
  if (activeSlug.value) {
    await loadArticle(activeSlug.value);
  }
  await loadBlogAgentHistory();
  if (auth.isAuthenticated) {
    await loadMyArticles();
    await loadOwnRestriction();
  }
  // 扩展交接放在登录态确定之后：未登录不消费、不在跳转链上带笔记。
  await consumeExtensionClip();
  // 扩展在已打开的 /blog 上追加 fragment 时（同文档导航不重挂载）也要能消费；
  // consumeExtensionClip 会立刻清掉 fragment，因此不会重复消费。
  window.addEventListener("hashchange", consumeExtensionClip);
  window.addEventListener("online", updateOnlineStatus);
  window.addEventListener("offline", updateOnlineStatus);
  conflictListener = handleDraftStorageConflict;
  window.addEventListener("storage", conflictListener);
});

watch(draft, persistCurrentDraft, { deep: true });

watch(
  () => authenticatedDraftOwner.value && `${authenticatedDraftOwner.value.actor}\u0000${authenticatedDraftOwner.value.workspace}`,
  (nextOwnerKey, previousOwnerKey) => {
    if (nextOwnerKey === previousOwnerKey) return;
    persistCurrentDraft();
    showWriter.value = false;
    editingArticle.value = null;
    writerContext.value = null;
    writerOwner.value = null;
    writerTabId.value = "";
    draftConflict.value = false;
    draft.value = emptyBlogDraft();
    myRestriction.value = null;
    if (auth.isAuthenticated) void loadOwnRestriction();
    if (authenticatedDraftOwner.value) void restoreWriterSession();
  },
  { flush: "sync" }
);

watch(activeSlug, async (slug) => {
  if (slug) {
    await loadArticle(slug);
  } else {
    currentArticle.value = null;
  }
});

watch([rightPanelWidth, rightPanelVisible], () => {
  localStorage.setItem("blogLayoutRightWidth", String(rightPanelWidth.value));
  localStorage.setItem("blogLayoutRightVisible", String(rightPanelVisible.value));
});

onBeforeUnmount(() => {
  persistCurrentDraft();
  if (conflictListener) window.removeEventListener("storage", conflictListener);
  window.removeEventListener("hashchange", consumeExtensionClip);
  window.removeEventListener("online", updateOnlineStatus);
  window.removeEventListener("offline", updateOnlineStatus);
  stopPanelResize();
});

function beginWriterContext(context: WriterContext) {
  writerOwner.value = authenticatedDraftOwner.value;
  writerContext.value = context;
  // sessionStorage can be cloned when the browser duplicates a tab. Keep the
  // writer identity in page memory so concurrent editors remain distinguishable.
  writerTabId.value = writerOwner.value ? crypto.randomUUID() : "";
  draftConflict.value = false;
  if (writerOwner.value) saveWriterContext(writerOwner.value, context);
  draftSaveStatus.value = writerOwner.value
    ? "草稿自动保存在当前账号与工作空间的本机浏览器中。"
    : "尚未登录，草稿不会写入共享浏览器存储。";
}

function persistCurrentDraft() {
  if (!showWriter.value || restoringWriter.value || clearingDraft.value || !writerOwner.value || !writerContext.value) return;
  if (!auth.isAuthenticated) return;
  if (draftConflict.value) {
    draftSaveStatus.value = "检测到其他标签页修改，自动保存已暂停。";
    return;
  }
  try {
    saveWriterDraft(writerOwner.value, writerContext.value, draft.value, writerTabId.value);
    saveWriterContext(writerOwner.value, { ...writerContext.value, open: true });
    draftSaveStatus.value = browserOnline.value
      ? "已自动保存在本机浏览器；尚未提交到服务器。"
      : "网络已断开；草稿仍保存在本机浏览器，恢复联网后可继续提交。";
  } catch (error) {
    draftSaveStatus.value = getDraftCacheStatus(error);
  }
}

function clearActiveDraftAfterServerSave() {
  if (writerOwner.value && writerContext.value) {
    removeWriterDraft(writerOwner.value, writerContext.value);
    saveWriterContext(writerOwner.value, { ...writerContext.value, open: false });
  }
  draftSaveStatus.value = "服务器已保存，当前本地草稿已清理。";
}

async function restoreWriterSession() {
  const owner = authenticatedDraftOwner.value;
  if (!owner) return;
  const context = readWriterContext(owner);
  if (!context?.open) return;
  beginWriterContext(context);
  const cached = readWriterDraft(owner, context);
  restoringWriter.value = true;
  if (cached) draft.value = { ...cached.draft };
  showWriter.value = true;
  draftSaveStatus.value = cached ? "已从本机恢复未提交草稿。" : "恢复了编辑窗口；本地没有可恢复的草稿内容。";
  const draftBeforeFetch = JSON.stringify(draft.value);
  await nextTick();
  restoringWriter.value = false;
  persistCurrentDraft();

  if (context.kind === "article" && context.slug) {
    const sequence = ++articleLoadSequence;
    try {
      const article = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(context.slug)}/`);
      if (sequence === articleLoadSequence && writerContext.value?.id === context.id) {
        editingArticle.value = article;
        if (!cached && JSON.stringify(draft.value) === draftBeforeFetch) {
          draft.value = articleToDraft(article);
          persistCurrentDraft();
        }
      }
    } catch {
      if (sequence === articleLoadSequence) {
        editorError.value = "无法从服务器读取文章；本机缓存仍保留，请检查网络或稍后重试。";
      }
    }
  }
}

function articleToDraft(article: BlogArticle): BlogDraft {
  if (article.pending_revision) {
    const pending = article.pending_revision;
    return {
      title: pending.title,
      summary: pending.summary,
      cover_image: pending.cover_image,
      category: pending.category,
      tags: normalizeTagList(pending.tags),
      content: pending.content
    };
  }
  return {
    title: article.title,
    summary: article.summary || "",
    cover_image: article.cover_image || "",
    category: article.category?.name || "",
    tags: normalizeTagList(article.tags?.map((tag) => tag.name)),
    content: article.content || ""
  };
}

function updateOnlineStatus() {
  browserOnline.value = navigator.onLine;
  if (showWriter.value && !draftConflict.value) {
    draftSaveStatus.value = browserOnline.value
      ? "网络已恢复；本机草稿仍在，可继续提交。"
      : "网络已断开；草稿仍保存在本机浏览器。";
  }
}

function handleDraftStorageConflict(event: StorageEvent) {
  if (!writerOwner.value || !writerContext.value || !event.key) return;
  const currentStorageKey = getWriterContextStorageKey(writerOwner.value, writerContext.value);
  if (event.key !== currentStorageKey || !event.newValue) return;
  // A storage event is delivered only to other same-origin documents. Do not
  // compare tab IDs here: browsers may clone session state when duplicating tabs.
  draftConflict.value = true;
  draftSaveStatus.value = "另一标签页修改了这篇草稿；为避免互相覆盖，自动保存已暂停。";
}

function resolveDraftConflict() {
  draftConflict.value = false;
  persistCurrentDraft();
}

function reloadConflictingDraft() {
  if (!writerOwner.value || !writerContext.value) return;
  const latest = readWriterDraft(writerOwner.value, writerContext.value);
  if (!latest) return;
  restoringWriter.value = true;
  draft.value = { ...latest.draft };
  draftConflict.value = false;
  void nextTick(() => {
    restoringWriter.value = false;
    draftSaveStatus.value = "已载入另一标签页保存的版本。";
  });
}

async function loadArticles() {
  const sequence = ++discoveryLoadSequence;
  loading.value = true;
  try {
    const params = new URLSearchParams({ page: String(articlePage.value), page_size: String(articlePageSize.value) });
    if (searchQuery.value.trim()) params.set("q", searchQuery.value.trim());
    if (activeCategory.value) params.set("category", activeCategory.value);
    if (activeTag.value) params.set("tag", activeTag.value);
    if (myOnly.value && auth.isAuthenticated) params.set("my", "1");
    const result = await requestJson(`/api/agent/blog/articles/discover/?${params.toString()}`);
    if (sequence !== discoveryLoadSequence) return;
    articles.value = result.items;
    articleTotal.value = result.total;
    articlePages.value = result.pages;
  } finally {
    if (sequence === discoveryLoadSequence) loading.value = false;
  }
}

async function loadArticle(slug: string) {
  currentArticle.value = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(slug)}/?include_comments=0`);
  loadRelatedArticles(slug);
  loadCollectionContext(slug);
}

async function loadCollectionContext(slug: string) {
  collectionContext.value = null;
  const requested = route.query.collection;
  try {
    const params = new URLSearchParams();
    params.set("article", String(currentArticle.value?.id ?? ""));
    if (typeof requested === "string" && requested) params.set("collection", requested);
    if (currentArticle.value?.id) {
      collectionContext.value = await requestJson(`/api/agent/blog/collections/context/?${params.toString()}`);
    }
  } catch {
    collectionContext.value = null;
  }
}

function clearCollectionContext() {
  collectionContext.value = null;
}

/**
 * B-043：消费浏览器扩展的一次性交接。fragment 里只有随机 nonce 与扩展 ID；
 * 页面负责尽快清掉它，等登录态就绪后才向扩展取值，并只把它当作不可信输入。
 */
async function consumeExtensionClip() {
  // screenshot-v1 截图交接优先，v2 通用网页剪藏其次。
  // 注：v1 力扣链接交接（#clip=）已于 2026-10-07 随「力扣导入」功能一并移除。
  const shotFragment = readScreenshotFragment(window.location.hash ?? "");
  if (shotFragment) {
    clearScreenshotFragment();
    if (!auth.isAuthenticated) {
      clipStatus.value = {
        kind: "error",
        text: "请先登录博客，再从浏览器扩展重新发送一次。截图只保存在扩展的本地暂存里（15 分钟），地址栏已清除。"
      };
      ElMessage.error("请先登录博客，再从浏览器扩展重新发送一次。");
      return;
    }
    clipStatus.value = { kind: "info", text: "正在接收截图…" };
    const outcome = await consumeScreenshotHandoff(shotFragment.nonce, shotFragment.extensionId);
    if (outcome.status === "failed") {
      clipStatus.value = { kind: "error", text: outcome.failure.detail };
      ElMessage.error(outcome.failure.detail);
      return;
    }
    const { meta, tiles } = outcome.payload;
    screenshotOcrJob.value = {
      tiles: tiles.map((tile) => ({
        file: tile.file,
        width: tile.meta.width,
        height: tile.meta.height,
        scrollX: tile.meta.scrollX,
        scrollY: tile.meta.scrollY,
        imageCandidates: tile.meta.imageCandidates,
      })),
      mode: meta.mode,
      sourceUrl: meta.sourceUrl,
      titleCandidate: meta.titleCandidate,
      capturedAt: meta.capturedAt,
      covered: meta.covered,
      truncated: meta.truncated,
      selection: meta.selection,
      viewport: meta.viewport,
      warnings: meta.warnings,
      cropRequired: meta.mode === "region",
    };
    screenshotOcrOpen.value = true;
    clipStatus.value = {
      kind: "ok",
      text: meta.truncated
        ? "已接收截图（未覆盖完整范围）：识别后请核对覆盖范围。"
        : "已接收截图：正在本地识别，请在校对页核对内容。",
    };
    return;
  }

  const webFragment = readWebClipFragment(window.location.hash ?? "");
  if (webFragment) {
    clearWebClipFragment();
    if (!auth.isAuthenticated) {
      clipStatus.value = {
        kind: "error",
        text: "请先登录博客，再从浏览器扩展重新发送一次。交接正文只保存在扩展的临时存储里，地址栏已清除。"
      };
      ElMessage.error("请先登录博客，再从浏览器扩展重新发送一次。");
      return;
    }
    clipStatus.value = { kind: "info", text: "正在接收网页剪藏…" };
    const outcome = await consumeWebClip(webFragment.nonce, webFragment.extensionId);
    if (outcome.status === "failed") {
      clipStatus.value = { kind: "error", text: outcome.detail };
      ElMessage.error(outcome.detail);
      return;
    }
    const { meta, html } = outcome.payload;
    webClipSource.value = {
      sourceUrl: meta.sourceUrl,
      title: meta.titleCandidate,
      site: meta.siteCandidate,
      ownNote: meta.ownNote,
      captureTarget: meta.captureTarget,
    };
    if (meta.captureTarget === "private_note") {
      // 默认目标：先经过与文章相同的服务端 HTML 安全预览与逐块选择。
      noteClipFile.value = new File([html], "web-clip.html", { type: "text/html" });
    } else {
      // 显式选择博客草稿：走既有 HTML 导入预览与覆盖确认。
      htmlClipFile.value = new File([html], "web-clip.html", { type: "text/html" });
      if (!showWriter.value) openWriterForNew();
    }
    clipStatus.value = {
      kind: "ok",
      text: meta.captureTarget === "article_draft"
        ? "已带入网页剪藏：请在导入预览里核对后应用为博客草稿。"
        : "已带入网页剪藏：请在预览里选好区块，再放入私有笔记编辑器。"
    };
    return;
  }
}

function dismissClipStatus() {
  clipStatus.value = null;
}

/** 用户确认区块后才把图片下载到私有存储；任何失败都保留预览供重试。 */
async function applyWebClipToPrivateNote(
  data: { title: string; content: string; source_url: string },
  localImages: Array<{ reference: string; alt: string; file: File }>,
  remoteImages: Array<{ reference: string; alt: string }>,
) {
  if (noteClipApplying.value) return;
  noteClipApplying.value = true;
  try {
    if (localImages.length + remoteImages.length > 20) throw new Error("单次最多处理 20 张图片，请先减少区块");
    let content = data.content;
    const imageIds: number[] = [];
    const replaceImage = (reference: string, url: string) => {
      content = content.split(reference).join(url);
    };
    for (const image of localImages) {
      const form = new FormData();
      form.append("image", image.file);
      const response = await fetch("/api/agent/blog/notes/images/", { method: "POST", body: form });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? `私有图片上传失败 (${response.status})`);
      imageIds.push(result.id);
      replaceImage(image.reference, result.url);
    }
    for (const image of remoteImages) {
      const response = await fetch("/api/agent/blog/notes/images/fetch/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: image.reference }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? `远程图片保存失败 (${response.status})`);
      imageIds.push(result.id);
      replaceImage(image.reference, result.url);
    }
    const source = webClipSource.value;
    const ownNote = source?.ownNote?.trim();
    if (ownNote) content = `> 来源说明：${ownNote}\n\n${content}`;
    if (content.length > 50_000) throw new Error("选中内容超过私有笔记 50,000 字上限，请减少区块");
    webClipNoteDraft.value = {
      title: data.title,
      content,
      source_url: data.source_url || source?.sourceUrl || "",
      source_title: source?.site ? `${data.title} · ${source.site}`.slice(0, 200) : data.title,
      imageIds,
    };
    noteClipFile.value = null;
    showPrivateNotes.value = true;
    clipStatus.value = { kind: "ok", text: "剪藏已进入私有笔记编辑器；核对并点击保存后才会落库。" };
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : "剪藏处理失败，请重试";
    ElMessage.error(detail);
    clipStatus.value = { kind: "error", text: detail };
  } finally {
    noteClipApplying.value = false;
  }
}

/**
 * B-045：截图识别校对完成后的落点。默认进入私有笔记草稿（仅内存，
 * 用户点击保存才落库）；选择博客草稿时只覆盖写作台未提交草稿，
 * 且在已有内容时必须确认，不自动发布。
 */
function applyScreenshotOcrContent(payload: { title: string; content: string; target: "private_note" | "article_draft" }) {
  const source = screenshotOcrJob.value;
  const sourceTitle = source?.titleCandidate ?? "";
  const sourceUrl = source?.sourceUrl ?? "";
  if (payload.target === "article_draft") {
    void applyScreenshotToDraft(payload, sourceTitle, sourceUrl);
    return;
  }
  screenshotOcrOpen.value = false;
  webClipNoteDraft.value = {
    title: payload.title || "截图笔记",
    content: payload.content,
    source_url: sourceUrl,
    source_title: sourceTitle,
  };
  showPrivateNotes.value = true;
  ElMessage.success("识别内容已带入私有笔记编辑器；核对后点击“保存私有笔记”。");
}

async function applyScreenshotToDraft(
  payload: { title: string; content: string },
  sourceTitle: string,
  sourceUrl: string,
) {
  const sourceLine = [
    payload.title,
    sourceUrl,
    "截图识别（OCR），内容需人工校对",
  ]
    .filter(Boolean)
    .join(" · ");
  const content = `> 来源：${sourceLine}\n\n${payload.content}`;
  if (draft.value.content.trim()) {
    try {
      await ElMessageBox.confirm(
        "写作台当前草稿已有内容，应用截图识别会覆盖正文（标题与本机草稿缓存仍保留）。是否继续？",
        "应用为博客草稿",
        { type: "warning", confirmButtonText: "覆盖草稿", cancelButtonText: "取消" },
      );
    } catch {
      return;
    }
  }
  if (!showWriter.value) openWriterForNew();
  draft.value.title = payload.title || "截图笔记";
  draft.value.content = content;
  screenshotOcrOpen.value = false;
  showWriter.value = true;
  ElMessage.success("已应用到写作台草稿；只有你主动提交才会进入审核。");
}

async function loadRelatedArticles(slug: string) {
  relatedLoading.value = true;
  relatedArticles.value = [];
  try {
    relatedArticles.value = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(slug)}/related/`);
  } catch {
    relatedArticles.value = [];
  } finally {
    relatedLoading.value = false;
  }
}

async function loadTags() {
  tags.value = await requestJson("/api/agent/blog/tags/");
}

async function loadCategories() {
  categories.value = await requestJson("/api/agent/blog/categories/");
}

async function loadArchive() {
  archive.value = await requestJson("/api/agent/blog/archive/");
}

async function loadAbout() {
  about.value = await requestJson("/api/agent/blog/about/");
  try {
    const settings = await requestJson("/api/agent/blog/settings/");
    siteSettings.value = settings;
    // 设置里的每页数量生效（显式查询参数优先，这里只在用户未指定时跟随）
    const perPage = Number(settings.articles_per_page);
    if (Number.isFinite(perPage) && perPage >= 4 && perPage <= 24 && articlePage.value === 1) {
      articlePageSize.value = perPage;
    }
  } catch {
    siteSettings.value = null; // 设置读取失败不影响页面：回退到内置文案
  }
}

async function loadMyArticles() {
  // 只有登录用户才能加载笔记
  if (!auth.isAuthenticated) {
    myPendingArticles.value = [];
    myPublishedArticles.value = [];
    return;
  }

  myArticlesLoading.value = true;
  try {
    // 后端已根据 context.actor 过滤草稿/拒绝文章
    // 已发布文章通过 my=1 参数过滤为自己的
    const [drafts, rejected, published] = await Promise.all([
      requestJson('/api/agent/blog/articles/?status=draft'),
      requestJson('/api/agent/blog/articles/?status=rejected'),
      requestJson('/api/agent/blog/articles/?status=published&my=1')
    ]);
    myPendingArticles.value = [...drafts, ...rejected];
    myPublishedArticles.value = published;
  } finally {
    myArticlesLoading.value = false;
  }
}

async function openArticle(article: BlogArticle) {
  if (!currentArticle.value) articleListScrollY.value = window.scrollY;
  await router.push({ name: "blog", params: { slug: article.slug }, query: route.query });
}

async function returnToArticleList() {
  currentArticle.value = null;
  await router.push({ name: "blog", query: route.query });
  await nextTick();
  requestAnimationFrame(() => window.scrollTo({ top: articleListScrollY.value, behavior: "auto" }));
}

async function handleInlineRevisionSubmitted() {
  const slug = currentArticle.value?.slug;
  ElMessage.success("修订已提交审核；当前公开版本继续可读。");
  if (!slug) return;
  try {
    const [updated] = await Promise.all([
      requestJson(`/api/agent/blog/articles/${encodeURIComponent(slug)}/`),
      loadArticles(),
      loadMyArticles()
    ]);
    currentArticle.value = updated;
  } catch {
    ElMessage.warning("修订已保存，但页面未能刷新；请稍后重新打开文章。");
  }
}

async function applyFilter(params: Record<string, string>) {
  const nextFilters = Object.fromEntries(Object.entries(params).map(([key, value]) => [key, value || undefined]));
  await router.push({ name: "blog", query: { ...route.query, ...nextFilters, page: undefined } });
}

async function filterByCategory(slug: string) {
  await applyFilter({ category: slug });
}

async function clearCategoryFilter() {
  await applyFilter({ category: "" });
}

async function searchArticles() {
  const q = searchQuery.value.trim();
  await applyFilter({ q });
}

async function changeArticlePage(page: number) {
  await router.push({ name: "blog", query: { ...route.query, page: page === 1 ? undefined : String(page) } });
}

async function changeTagFilter(tag: string) {
  await applyFilter({ tag });
}

async function changeMyFilter(checked: boolean) {
  await applyFilter({ my: checked ? "1" : "" });
}

async function clearDiscoveryFilters() {
  await router.push({ name: "blog" });
}

function openWriterForNew() {
  editingArticle.value = null;
  const owner = authenticatedDraftOwner.value;
  const previousContext = owner ? readWriterContext(owner) : null;
  const previousDraft = owner && previousContext?.kind === "new"
    ? readWriterDraft(owner, previousContext)
    : null;
  const context = previousDraft && previousContext
    ? { ...previousContext, open: true }
    : { kind: "new" as const, id: crypto.randomUUID(), open: true };
  beginWriterContext(context);
  draft.value = previousDraft ? { ...previousDraft.draft } : emptyBlogDraft();
  if (previousDraft) draftSaveStatus.value = "已从本机恢复未完成草稿。";
  showWriter.value = true;
}

function openWriterForEdit(article: BlogArticle) {
  editingArticle.value = article;
  editPendingArticle(article);
  showWriter.value = true;
}

function closeWriter() {
  persistCurrentDraft();
  if (writerOwner.value && writerContext.value) {
    saveWriterContext(writerOwner.value, { ...writerContext.value, open: false });
  }
  showWriter.value = false;
  editingArticle.value = null;
}

async function openRelatedArticle(article: BlogArticle) {
  await router.push({ name: "blog", params: { slug: article.slug }, query: route.query });
}

async function handleCoverImageUpload(file: File) {
  uploadingImage.value = true;
  try {
    const formData = new FormData();
    formData.append("image", file);
    const payload = await requestJson("/api/agent/blog/images/", {
      method: "POST",
      body: formData
    });
    draft.value.cover_image = payload.url;
    ElMessage.success("封面图已上传");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "封面图上传失败");
  } finally {
    uploadingImage.value = false;
  }
}

async function publishDraft(addToKnowledgeBase = false) {
  editorError.value = "";
  if (!draft.value.title.trim() || !draft.value.content.trim()) {
    editorError.value = "标题和正文不能为空。";
    return;
  }

  if (!auth.isAuthenticated) {
    editorError.value = "请先登录后再发布笔记。";
    return;
  }

  publishing.value = true;
  try {
    // 没填封面就用正文第一张图片（后端也会兜底，这里让作者在提交前立刻看到结果）。
    const autoCover = defaultCoverImage(draft.value.cover_image, draft.value.content);
    if (autoCover) {
      draft.value.cover_image = autoCover;
      ElMessage.info("未填写封面，已自动使用正文中的第一张图片");
    }
    const payload = await requestJson("/api/agent/blog/articles/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...draft.value,
        tags: normalizeTagList(draft.value.tags),
        publish: true,
        add_to_knowledge_base: addToKnowledgeBase
      })
    });
    clearActiveDraftAfterServerSave();
    await loadArticles();
    await loadArchive();
    await loadMyArticles();
    if (payload.approval_required) {
      clearActiveDraftAfterServerSave();
      showWriter.value = false;
      ElMessage.success("笔记已提交，等待管理员审核后会公开发布。");
      return;
    }
    clearActiveDraftAfterServerSave();
    showWriter.value = false;
    await openArticle(payload);
  } catch (error) {
    editorError.value = error instanceof Error ? error.message : "发布失败，请稍后重试。";
  } finally {
    publishing.value = false;
  }
}

async function syncArticleKnowledge(article: BlogArticle) {
  publishing.value = true;
  try {
    const payload = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(article.slug)}/publish/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ add_to_knowledge_base: true })
    });
    await Promise.all([loadArticles(), loadArchive()]);
    if (payload.approval_required) {
      openApprovalDialog(payload.approval);
      ElMessage.warning(`发布审批 #${payload.approval.id} 已创建，批准后才会进入知识库`);
      return;
    }
    await loadArticle(article.slug);
  } finally {
    publishing.value = false;
  }
}

async function deleteArticle(article: BlogArticle) {
  try {
    await ElMessageBox.confirm(
      `确定提交删除文章「${article.title}」的审批吗？批准后会删除对应知识库文档，并清理没有被其他文章或笔记引用的图片。`,
      "删除文章",
      {
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        type: "warning",
        confirmButtonClass: "el-button--danger"
      }
    );
  } catch {
    return;
  }

  deletingArticleSlug.value = article.slug;
  try {
    const payload = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(article.slug)}/`, {
      method: "DELETE"
    });
    if (payload?.approval_required) {
      openApprovalDialog(payload.approval);
      ElMessage.warning(`删除审批 #${payload.approval.id} 已创建，批准后才会删除文章`);
      return;
    }
    if (currentArticle.value?.slug === article.slug) {
      currentArticle.value = null;
      await router.push("/blog");
    }
    await Promise.all([loadArticles(), loadArchive(), loadTags(), loadCategories()]);
    ElMessage.success("文章已删除");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除文章失败");
  } finally {
    deletingArticleSlug.value = "";
  }
}

function applyTemplate(content: string) {
  draft.value.content = content;
}

function insertSnippet(snippet: string) {
  draft.value.content = `${draft.value.content.trim()}\n\n${snippet}\n`;
}

async function generateWithWritingAssistant(request: WritingAssistantRequest) {
  if (!auth.isAuthenticated) {
    writingAssistantError.value = "请先登录后再使用写作助手。";
    return;
  }

  writingAssistantLoading.value = true;
  writingAssistantError.value = "";
  try {
    const payload = await requestJson("/api/agent/blog/writing-agent/generate/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: request.mode,
        instruction: request.instruction,
        draft: draft.value
      })
    });
    writingAssistantResult.value = {
      markdown: payload.markdown,
      mode: payload.mode,
      model: payload.model,
      apiKeySource: payload.api_key_source
    };
  } catch (error) {
    writingAssistantError.value = error instanceof Error ? error.message : "写作助手暂时不可用。";
  } finally {
    writingAssistantLoading.value = false;
  }
}

async function applyWritingAssistantResult(strategy: "append" | "replace") {
  const result = writingAssistantResult.value;
  if (!result) return;

  if (strategy === "replace" && draft.value.content.trim()) {
    try {
      await ElMessageBox.confirm(
        "替换会覆盖当前正文，但本地自动保存仍会记录替换后的内容。是否继续？",
        "替换正文",
        { confirmButtonText: "确认替换", cancelButtonText: "取消", type: "warning" }
      );
    } catch {
      return;
    }
  }

  if (strategy === "replace") {
    draft.value.content = result.markdown;
  } else {
    const current = draft.value.content.trimEnd();
    draft.value.content = current ? `${current}\n\n${result.markdown}\n` : `${result.markdown}\n`;
  }
  ElMessage.success(strategy === "replace" ? "已用生成结果替换正文" : "已将生成结果追加到正文");
}

async function clearDraftCache() {
  try {
    await ElMessageBox.confirm(
      "将清空标题、摘要、分类、标签和正文，且无法从本地草稿恢复。是否继续？",
      "清空本地草稿",
      {
        confirmButtonText: "确认清空",
        cancelButtonText: "取消",
        type: "warning"
      }
    );
  } catch {
    return;
  }

  clearingDraft.value = true;
  draft.value = emptyBlogDraft();
  await nextTick();
  if (writerOwner.value && writerContext.value) removeWriterDraft(writerOwner.value, writerContext.value);
  clearingDraft.value = false;
  draftSaveStatus.value = "草稿已清空。";
  ElMessage.success("本地草稿和编辑器内容已清空");
}

async function importMarkdownFile(data: ParsedMarkdown, confirmed = false) {
  // If draft has meaningful content, confirm overwrite
  if (!confirmed && (draft.value.title.trim() || draft.value.content.trim())) {
    try {
      await ElMessageBox.confirm(
        "导入会覆盖当前草稿内容，是否继续？",
        "导入 Markdown",
        { confirmButtonText: "继续导入", cancelButtonText: "取消", type: "warning" }
      );
    } catch {
      return;
    }
  }

  draft.value.title = data.title;
  draft.value.summary = data.summary;
  draft.value.category = data.category;
  draft.value.tags = normalizeTagList(data.tags);
  draft.value.content = data.content;
  ElMessage.success("文件已导入，请检查并编辑后发布。");
}

function openApprovalDialog(approval: ApprovalRequest) {
  if (auth.session.role !== "admin") return;
  pendingApproval.value = approval;
  approvalDialogOpen.value = true;
}

async function editPendingArticle(article: BlogArticle) {
  const sequence = ++articleLoadSequence;
  const owner = authenticatedDraftOwner.value;
  if (!owner) {
    editorError.value = "登录后才能编辑并保存文章草稿。";
    return;
  }
  editingArticle.value = article;
  const context: WriterContext = { kind: "article", id: String(article.id), slug: article.slug, open: true };
  beginWriterContext(context);
  const cached = readWriterDraft(owner, context);
  restoringWriter.value = true;
  draft.value = cached ? { ...cached.draft } : articleToDraft(article);
  if (cached) draftSaveStatus.value = "已恢复这篇文章未提交的本地修改。";
  const draftBeforeFetch = JSON.stringify(draft.value);
  await nextTick();
  restoringWriter.value = false;
  persistCurrentDraft();
  if (!article.content && !cached) {
    try {
      const fullArticle = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(article.slug)}/`);
      if (
        sequence === articleLoadSequence &&
        writerContext.value?.id === context.id &&
        JSON.stringify(draft.value) === draftBeforeFetch
      ) {
        editingArticle.value = fullArticle;
        draft.value = articleToDraft(fullArticle);
        persistCurrentDraft();
      }
    } catch {
      if (sequence === articleLoadSequence) {
        editorError.value = "文章正文暂时无法从服务器读取；请检查网络后重试。";
      }
    }
  }
  // Scroll to editor
  nextTick(() => {
    document.querySelector(".write-box")?.scrollIntoView({ behavior: "smooth" });
  });
}

function cancelEditArticle() {
  persistCurrentDraft();
  if (writerOwner.value && writerContext.value) {
    saveWriterContext(writerOwner.value, { ...writerContext.value, open: false });
  }
  editingArticle.value = null;
  showWriter.value = false;
}

async function updatePendingArticle() {
  if (!editingArticle.value) return;

  editorError.value = "";
  if (!draft.value.title.trim() || !draft.value.content.trim()) {
    editorError.value = "标题和正文不能为空。";
    return;
  }

  if (!auth.isAuthenticated) {
    editorError.value = "请先登录后再更新笔记。";
    return;
  }

  updatingArticle.value = true;
  try {
    const payload = await requestJson(`/api/agent/blog/articles/${encodeURIComponent(editingArticle.value.slug)}/`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...draft.value,
        publication_version: editingArticle.value.publication_version,
        tags: normalizeTagList(draft.value.tags)
      })
    });
    await loadArticles();
    await loadMyArticles();
    clearActiveDraftAfterServerSave();
    editingArticle.value = null;
    showWriter.value = false;
    ElMessage.success("文章已更新，等待管理员审核。");
  } catch (error) {
    editorError.value = error instanceof Error ? error.message : "更新失败，请稍后重试。";
  } finally {
    updatingArticle.value = false;
  }
}

async function reviewCurrentApproval(decision: "approve" | "reject") {
  if (!pendingApproval.value) return;
  reviewingApproval.value = true;
  try {
    const payload = await requestJson(`/api/agent/approvals/${pendingApproval.value.id}/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reviewer: reviewer.value, note: reviewNote.value })
    });
    pendingApproval.value = payload;
    approvalDialogOpen.value = false;
    ElMessage.success(decision === "approve" ? "审批已通过并执行" : "审批已拒绝");
    await Promise.all([loadArticles(), loadArchive(), loadTags(), loadCategories()]);
    if (currentArticle.value?.slug) {
      try {
        await loadArticle(currentArticle.value.slug);
      } catch {
        currentArticle.value = null;
        await router.push("/blog");
      }
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "审批处理失败");
  } finally {
    reviewingApproval.value = false;
  }
}

async function submitComment(article: BlogArticle) {
  if (!commentDraft.value.content.trim()) return;
  submittingComment.value = true;
  try {
    await requestJson(`/api/agent/blog/articles/${encodeURIComponent(article.slug)}/comments/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: commentDraft.value.content })
    });
    commentDraft.value.content = "";
    await loadArticle(article.slug);
    ElMessage.success("评论已公开。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "评论提交失败");
    void loadOwnRestriction();
  } finally {
    submittingComment.value = false;
  }
}

async function refreshPublishedComment() {
  if (currentArticle.value) await loadArticle(currentArticle.value.slug);
}

async function loadOwnRestriction() {
  if (!auth.isAuthenticated) {
    myRestriction.value = null;
    return;
  }
  try {
    const result = await requestJson("/api/agent/blog/comment-restriction/me/");
    myRestriction.value = result.restriction;
  } catch {
    myRestriction.value = null;
  }
}

async function submitRestrictionAppeal() {
  if (!appealMessage.value.trim()) return;
  appealing.value = true;
  try {
    await requestJson("/api/agent/blog/comment-restriction/appeal/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: appealMessage.value.trim() })
    });
    appealMessage.value = "";
    await loadOwnRestriction();
    ElMessage.success("申诉已提交，等待管理员处理");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "申诉提交失败");
  } finally {
    appealing.value = false;
  }
}

async function loadModerationComments() {
  if (!auth.isAuthenticated || auth.session.role !== "admin") return;
  moderationLoading.value = true;
  try {
    if (moderationStatus.value === "restrictions") {
      moderationRestrictions.value = await requestJson("/api/agent/blog/comment-restrictions/");
    } else if (moderationStatus.value === "reports") {
      moderationReports.value = await requestJson("/api/agent/blog/comments/reports/");
    } else {
      moderationComments.value = await requestJson(`/api/agent/blog/comments/moderation/?status=${moderationStatus.value}`);
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "评论审核列表加载失败");
  } finally {
    moderationLoading.value = false;
  }
}

async function restrictAccount() {
  if (!restrictionUsername.value.trim() || !restrictionReason.value.trim()) return;
  restricting.value = true;
  try {
    await requestJson("/api/agent/blog/comment-restrictions/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: restrictionUsername.value.trim(),
        reason: restrictionReason.value.trim(),
        days: restrictionDays.value
      })
    });
    restrictionUsername.value = "";
    restrictionReason.value = "";
    await loadModerationComments();
    ElMessage.success("已限制该账号的评论与举报功能");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "限制账号失败");
  } finally {
    restricting.value = false;
  }
}

async function reviewRestriction(restriction: InteractionRestriction, action: "lift" | "accept_appeal" | "uphold_appeal") {
  reviewingRestrictionId.value = restriction.id;
  try {
    await requestJson(`/api/agent/blog/comment-restrictions/${restriction.id}/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    await loadModerationComments();
    ElMessage.success(action === "uphold_appeal" ? "申诉已驳回" : "限制已解除");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "处理失败");
  } finally {
    reviewingRestrictionId.value = null;
  }
}

function openReportDialog(comment: BlogComment) {
  reportTarget.value = comment;
  reportReason.value = "spam";
  reportDetail.value = "";
  reportDialogOpen.value = true;
}

async function submitReport() {
  if (!reportTarget.value) return;
  submittingReport.value = true;
  try {
    await requestJson(`/api/agent/blog/comments/${reportTarget.value.id}/reports/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reportReason.value, detail: reportDetail.value })
    });
    reportDialogOpen.value = false;
    ElMessage.success("举报已提交，管理员会处理。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "举报提交失败");
    void loadOwnRestriction();
  } finally {
    submittingReport.value = false;
  }
}

async function reviewReport(report: ModerationReport, decision: "hide" | "dismiss") {
  reviewingReportId.value = report.id;
  try {
    await requestJson(`/api/agent/blog/comments/reports/${report.id}/review/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision })
    });
    ElMessage.success(decision === "hide" ? "评论已隐藏" : "举报已驳回");
    await loadModerationComments();
    if (currentArticle.value) await loadArticle(currentArticle.value.slug);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "举报处理失败");
  } finally {
    reviewingReportId.value = null;
  }
}

async function moderateComment(comment: ModerationComment, decision: "approve" | "reject") {
  moderatingCommentId.value = comment.id;
  try {
    await requestJson(`/api/agent/blog/comments/${comment.id}/moderate/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision })
    });
    ElMessage.success(decision === "approve" ? "评论已批准" : "评论已隐藏");
    await loadModerationComments();
    if (currentArticle.value) await loadArticle(currentArticle.value.slug);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "评论审核失败");
  } finally {
    moderatingCommentId.value = null;
  }
}

function askAgent(article: BlogArticle) {
  if (!auth.isAuthenticated) {
    blogAgentOpen.value = true;
    blogAgentInput.value = `根据博客文章《${article.title}》，总结项目经验并给出原文依据`;
    return;
  }
  void router.push(`/chat`);
  localStorage.setItem("pendingAgentQuestion", `根据我的博客文章《${article.title}》，总结我的项目经验`);
}

async function loadBlogAgentHistory() {
  if (!blogAgentSessionKey.value) return;
  try {
    const payload = await requestJson(`/api/agent/blog/agent/chat/?session_key=${encodeURIComponent(blogAgentSessionKey.value)}`);
    if (payload.messages?.length) {
      blogAgentMessages.value = payload.messages.map((message: any) => ({
        role: message.role,
        content: message.content,
        sources: message.sources
      }));
    }
  } catch {
    localStorage.removeItem("blogAgentSessionKey");
    blogAgentSessionKey.value = "";
  }
}

async function sendBlogAgentMessage(prompt?: string) {
  const message = (prompt ?? blogAgentInput.value).trim();
  if (!message || blogAgentLoading.value) return;

  blogAgentOpen.value = true;
  blogAgentMessages.value.push({ role: "user", content: message });
  const pendingMessage: BlogAgentChatMessage = {
    role: "agent",
    content: "正在根据公开博客资料检索...",
    pending: true
  };
  const pendingText =
    blogAgentSource.value === "ragagent"
      ? "正在通过 RAG-Agent 检索本站隔离知识..."
      : "正在根据公开博客资料检索...";
  blogAgentMessages.value.push(pendingMessage);
  blogAgentInput.value = "";
  blogAgentLoading.value = true;

  try {
    const payload = await requestJson("/api/agent/blog/agent/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        session_key: blogAgentSessionKey.value,
        rag_source: blogAgentSource.value
      })
    });
    blogAgentSessionKey.value = payload.session_key;
    localStorage.setItem("blogAgentSessionKey", payload.session_key);
    Object.assign(pendingMessage, {
      content: payload.answer,
      sources: payload.sources,
      blocked: payload.blocked,
      pending: false
    });
  } catch (error) {
    Object.assign(pendingMessage, {
      content: error instanceof Error ? error.message : "博客智能体暂时不可用，请稍后再试。",
      pending: false
    });
  } finally {
    blogAgentLoading.value = false;
  }
}

function handleBlogAgentKeydown(event: KeyboardEvent) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  void sendBlogAgentMessage();
}

const handleEditorUpload = async (files: File[]): Promise<Array<{ url: string; alt?: string; title?: string }>> => {
  editorError.value = "";
  uploadingImage.value = true;
  try {
    const uploaded = await Promise.all(
      files.map(async (file) => {
        const formData = new FormData();
        formData.append("image", file);
        const payload = await requestJson("/api/agent/blog/images/", {
          method: "POST",
          body: formData
        });
        return {
          url: payload.url,
          alt: file.name.replace(/\.[^.]+$/, ""),
          title: file.name
        };
      })
    );
    return uploaded;
  } catch (error) {
    editorError.value = error instanceof Error ? error.message : "图片上传失败。";
    return [];
  } finally {
    uploadingImage.value = false;
  }
};

async function requestJson(url: string, options: RequestInit = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") ?? "";
  const text = await response.text();
  let payload: any = null;

  if (contentType.includes("application/json") && text) {
    payload = JSON.parse(text);
  } else if (text) {
    const plainText = text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    payload = { detail: plainText.slice(0, 220) || "服务返回了非 JSON 响应。" };
  }

  if (!response.ok) {
    throw new Error(payload?.detail ?? `请求失败：HTTP ${response.status}`);
  }
  return payload;
}
</script>

<template>
  <div
    class="blog-shell"
    :class="{
      'right-panel-hidden': !rightPanelVisible,
      'is-resizing': resizingPanel
    }"
    :style="blogLayoutStyle"
  >
    <header v-if="!auth.isAuthenticated" class="blog-visitor-header">
      <RouterLink to="/landing">返回首页</RouterLink>
      <strong>公开技术文章</strong>
      <div class="blog-visitor-actions">
        <RouterLink :to="{ path: '/login', query: { redirect: route.fullPath } }">登录</RouterLink>
        <RouterLink :to="{ path: '/login', query: { mode: 'register', redirect: route.fullPath } }">注册账号</RouterLink>
      </div>
    </header>
    <section class="blog-workspace">
      <section class="blog-layout">
        <button
          class="panel-toggle right-panel-toggle"
          type="button"
          :aria-label="rightPanelVisible ? '隐藏辅助栏' : '显示辅助栏'"
          :title="rightPanelVisible ? '隐藏辅助栏' : '显示辅助栏'"
          @click="rightPanelVisible = !rightPanelVisible"
        >
          {{ rightPanelVisible ? "›" : "‹" }}
        </button>
        <main class="blog-main">
          <section v-if="!currentArticle" class="blog-library-hero">
            <div class="library-hero-copy">
              <span class="section-eyebrow">ENGINEERING · ALGORITHMS · AGENTS</span>
              <h1>{{ siteSettings?.site_title || "技术笔记与项目实践" }}</h1>
              <p>{{ siteSettings?.site_tagline || "沉淀可检索、可复用的工程经验。按分类进入主题，按标签定位具体知识点。" }}</p>
            </div>
            <dl class="library-hero-stats">
              <div><dt>{{ libraryArticleCount }}</dt><dd>公开文章</dd></div>
              <div><dt>{{ categories.length }}</dt><dd>主题分类</dd></div>
              <div><dt>{{ tags.length }}</dt><dd>知识标签</dd></div>
            </dl>
          </section>

          <!-- 顶部工具栏：搜索 + 操作按钮 -->
          <section class="blog-toolbar" v-if="!currentArticle">
            <div class="blog-search-bar">
              <label>检索文章</label>
              <el-input
                v-model="searchQuery"
                placeholder="输入算法、框架或项目关键词"
                size="large"
                clearable
                @keyup.enter="searchArticles"
                @clear="searchArticles"
              >
                <template #prefix>
                  <el-icon><Search /></el-icon>
                </template>
                <template #append>
                  <el-button @click="searchArticles">搜索</el-button>
                </template>
              </el-input>
            </div>
            <el-select v-model="activeTag" aria-label="按标签筛选" placeholder="全部标签" clearable style="width: 170px" @change="changeTagFilter">
              <el-option v-for="tag in tags" :key="tag.id" :label="tag.name" :value="tag.slug" />
            </el-select>
            <el-checkbox v-if="auth.isAuthenticated" v-model="myOnly" @change="changeMyFilter(Boolean($event))">仅看我的文章</el-checkbox>
            <div class="blog-toolbar-actions">
              <el-button
                v-if="auth.isAuthenticated && auth.session.role === 'admin'"
                @click="router.push('/blog/settings')"
              >
                站点设置
              </el-button>
              <el-button
                v-if="auth.isAuthenticated && auth.session.role === 'admin'"
                @click="moderationOpen = true; moderationStatus = 'approved'; loadModerationComments()"
              >
                评论管理
              </el-button>
              <el-button
                v-if="auth.isAuthenticated"
                type="default"
                @click="showMyArticles = true"
              >
                我的文章
              </el-button>
              <el-button @click="router.push('/blog/collections')">领域目录</el-button>
              <el-button v-if="auth.isAuthenticated" @click="openPrivateNotes()">我的笔记</el-button>
              <el-button v-if="myRestriction?.active" type="warning" plain @click="restrictionDialogOpen = true">评论限制与申诉</el-button>
              <el-button
                v-if="!auth.isAuthenticated"
                type="default"
              >
                <RouterLink to="/login" style="text-decoration: none; color: inherit;">登录</RouterLink>
              </el-button>
              <el-button
                v-if="auth.isAuthenticated"
                type="primary"
                @click="openWriterForNew"
              >
                写博客
              </el-button>
            </div>
          </section>

          <!-- 编辑器覆盖层 -->
          <el-alert
            v-if="clipStatus"
            class="clip-status-alert"
            :type="clipStatus.kind === 'error' ? 'error' : clipStatus.kind === 'ok' ? 'success' : 'info'"
            :closable="true"
            :title="clipStatus.text"
            @close="dismissClipStatus"
          />
          <div v-if="showWriter" class="writer-overlay">
            <div class="writer-overlay-header">
              <h2>{{ editingArticle ? `编辑: ${editingArticle.title}` : '写新博客' }}</h2>
              <div class="writer-overlay-actions">
                <span v-if="auth.isAuthenticated" class="writer-user-badge">
                  {{ auth.session.actor }}
                </span>
                <el-button @click="closeWriter">关闭</el-button>
                <el-button
                  type="primary"
                  :loading="editingArticle ? updatingArticle : publishing"
                  @click="editingArticle ? updatePendingArticle() : publishDraft(true)"
                >
                  {{ editingArticle ? '更新并重新提交' : '发布并加入知识库' }}
                </el-button>
              </div>
            </div>
            <BlogWriter
              :key="writerComponentKey"
              :draft="draft"
              :editor-cache-id="editorCacheId"
              :draft-save-status="draftSaveStatus"
              :draft-conflict="draftConflict"
              :templates="noteTemplates"
              :categories="categories"
              :tag-options="tags.map((tag) => tag.name)"
              :stats="editorStats"
              :publishing="publishing"
              :uploading-image="uploadingImage"
              :error="editorError"
              :upload-handler="handleEditorUpload"
              :editing-article="editingArticle"
              :updating="updatingArticle"
              :authenticated="auth.isAuthenticated"
              :writing-assistant-loading="writingAssistantLoading"
              :writing-assistant-error="writingAssistantError"
              :writing-assistant-result="writingAssistantResult"
              :html-clip-file="htmlClipFile"
              :html-clip-source-url="webClipSource?.sourceUrl"
              :html-clip-title="webClipSource?.title"
              :html-clip-own-note="webClipSource?.ownNote"
              @update:html-clip-file="htmlClipFile = $event"
              @publish="publishDraft"
              @update="updatePendingArticle"
              @cancel-edit="closeWriter"
              @apply-template="applyTemplate"
              @insert-snippet="insertSnippet"
              @clear-draft="clearDraftCache"
              @import-markdown="importMarkdownFile"
              @upload-cover-image="handleCoverImageUpload"
              @generate-with-assistant="generateWithWritingAssistant"
              @apply-assistant-result="applyWritingAssistantResult"
              @clear-assistant-result="writingAssistantResult = null; writingAssistantError = ''"
              @resolve-draft-conflict="resolveDraftConflict"
              @reload-conflicting-draft="reloadConflictingDraft"
              @open-screenshot-ocr="screenshotOcrOpen = true"
            />
          </div>

          <!-- 投稿和私有笔记有独立入口，避免误把私人记录提交发布。 -->
          <el-dialog v-model="showMyArticles" title="我的文章" width="700px" align-center>
            <section v-if="myArticlesLoading" class="my-notes-loading">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>加载中...</span>
            </section>
            <section v-else-if="!myPendingArticles.length && !myPublishedArticles.length" class="my-notes-empty">
              <p>你还没有提交过文章。</p>
            </section>
            <section v-else class="my-notes-content">
              <template v-if="myPendingArticles.length">
                <h3>待审核文章</h3>
                <article
                  v-for="item in myPendingArticles"
                  :key="item.id"
                  class="my-note-item"
                >
                  <div class="my-note-info">
                    <span :class="['status-pill', item.status === 'rejected' ? 'rejected' : 'pending']">
                      {{ item.status === 'rejected' ? '已拒绝' : '待审核' }}
                    </span>
                    <strong>{{ item.title }}</strong>
                    <small>{{ item.created_at }}</small>
                  </div>
                  <el-button size="small" type="primary" plain @click="openWriterForEdit(item); showMyArticles = false">编辑</el-button>
                </article>
              </template>
              <template v-if="myPublishedArticles.length">
                <h3>已发布文章</h3>
                <article
                  v-for="item in myPublishedArticles"
                  :key="item.id"
                  class="my-note-item"
                >
                  <div class="my-note-info">
                    <span class="status-pill published">已发布</span>
                    <strong @click="openArticle(item); showMyArticles = false" style="cursor: pointer;">{{ item.title }}</strong>
                    <small>{{ item.published_at || item.created_at }}</small>
                  </div>
                  <div>
                    <el-button size="small" @click="openArticle(item); showMyArticles = false">查看</el-button>
                    <el-button size="small" type="primary" plain @click="openWriterForEdit(item); showMyArticles = false">编辑</el-button>
                  </div>
                </article>
              </template>
            </section>
          </el-dialog>

          <HtmlImportDialog
            v-if="auth.isAuthenticated"
            :file="null"
            :clip-file="noteClipFile"
            :visible="Boolean(noteClipFile)"
            :applying="noteClipApplying"
            :clip-source-url="webClipSource?.sourceUrl"
            :clip-title="webClipSource?.title"
            destination="private_note"
            @close="noteClipFile = null"
            @apply-note="applyWebClipToPrivateNote"
          />

          <PrivateNotesDrawer
            v-if="auth.isAuthenticated"
            :key="`${auth.session.actor}:${auth.session.workspace_key}`"
            v-model="showPrivateNotes"
            :source-article="noteSourceArticle"
            :selected-quote="noteQuote"
            :web-clip-draft="webClipNoteDraft"
            @open-source="(slug) => { showPrivateNotes = false; router.push({ name: 'blog', params: { slug } }) }"
            @clip-draft-applied="webClipNoteDraft = null"
            @import-screenshot="screenshotOcrOpen = true"
          />

          <ScreenshotOcrDialog
            v-if="auth.isAuthenticated"
            v-model="screenshotOcrOpen"
            :initial-job="screenshotOcrJob"
            @apply-content="applyScreenshotOcrContent"
          />

          <el-dialog v-model="restrictionDialogOpen" title="评论与举报状态" width="480px" align-center>
            <template v-if="myRestriction?.active">
              <p>评论与举报功能暂停至 {{ new Date(myRestriction.expires_at).toLocaleString('zh-CN') }}。阅读、文章与私有笔记仍可使用。</p>
              <p>原因：{{ myRestriction.reason }}</p>
              <template v-if="myRestriction.appeal_status === 'none'">
                <el-input v-model="appealMessage" type="textarea" :rows="4" :maxlength="1000" show-word-limit aria-label="申诉说明" placeholder="说明情况及希望复核的理由，至少 10 字" />
                <el-button type="primary" :loading="appealing" style="margin-top: 12px" @click="submitRestrictionAppeal">提交申诉</el-button>
              </template>
              <p v-else-if="myRestriction.appeal_status === 'pending'">申诉已提交，等待管理员处理。</p>
              <p v-else-if="myRestriction.appeal_status === 'upheld'">申诉已复核，限制保持至到期。也可等待管理员提前解除。</p>
            </template>
            <p v-else>当前没有评论或举报限制。</p>
            <el-button @click="loadOwnRestriction">刷新状态</el-button>
          </el-dialog>

          <el-dialog v-model="moderationOpen" title="评论管理" width="min(680px, 96vw)" align-center>
            <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px">
              <el-button :type="moderationStatus === 'pending' ? 'primary' : 'default'" @click="moderationStatus = 'pending'; loadModerationComments()">历史待处理</el-button>
              <el-button :type="moderationStatus === 'approved' ? 'primary' : 'default'" @click="moderationStatus = 'approved'; loadModerationComments()">已公开</el-button>
              <el-button :type="moderationStatus === 'reports' ? 'primary' : 'default'" @click="moderationStatus = 'reports'; loadModerationComments()">举报待处理</el-button>
              <el-button :type="moderationStatus === 'restrictions' ? 'primary' : 'default'" @click="moderationStatus = 'restrictions'; loadModerationComments()">账号限制</el-button>
            </div>
            <p v-if="moderationLoading">正在加载评论…</p>
            <p v-else-if="moderationStatus === 'reports' && !moderationReports.length">暂无待处理举报</p>
            <p v-else-if="moderationStatus === 'restrictions' && !moderationRestrictions.length">暂无账号限制</p>
            <p v-else-if="moderationStatus !== 'reports' && moderationStatus !== 'restrictions' && !moderationComments.length">暂无评论</p>
            <section v-if="moderationStatus === 'restrictions'" style="display: grid; gap: 8px; margin-bottom: 16px">
              <p>仅暂停指定账号在当前工作空间的评论与举报，不影响阅读、文章和笔记。限制自动到期，用户可申诉。原因会展示给该用户，请勿写入他人隐私。</p>
              <el-input v-model="restrictionUsername" aria-label="限制账号用户名" placeholder="准确填写用户名" />
              <el-input v-model="restrictionReason" aria-label="限制原因" :maxlength="500" show-word-limit placeholder="说明证据与原因（10～500 字）" />
              <el-select v-model="restrictionDays" aria-label="限制天数" style="width: 160px">
                <el-option label="1 天" :value="1" /><el-option label="3 天" :value="3" /><el-option label="7 天" :value="7" /><el-option label="30 天" :value="30" />
              </el-select>
              <el-button type="danger" :loading="restricting" @click="restrictAccount">限制评论与举报</el-button>
              <article v-for="restriction in moderationRestrictions" :key="restriction.id" style="border-top: 1px solid var(--el-border-color); padding: 12px 0">
                <strong>{{ restriction.username }} · {{ restriction.active ? '限制中' : '已结束' }}</strong>
                <p>{{ restriction.reason }}</p>
                <small>至 {{ new Date(restriction.expires_at).toLocaleString('zh-CN') }} · 申诉：{{ restriction.appeal_status }}</small>
                <p v-if="restriction.appeal_message">申诉说明：{{ restriction.appeal_message }}</p>
                <div v-if="restriction.active || restriction.appeal_status === 'pending'" style="display: flex; gap: 8px; margin-top: 8px">
                  <el-button v-if="restriction.active" size="small" :loading="reviewingRestrictionId === restriction.id" @click="reviewRestriction(restriction, 'lift')">提前解除</el-button>
                  <el-button v-if="restriction.appeal_status === 'pending'" size="small" type="primary" :loading="reviewingRestrictionId === restriction.id" @click="reviewRestriction(restriction, 'accept_appeal')">接受申诉</el-button>
                  <el-button v-if="restriction.appeal_status === 'pending'" size="small" :loading="reviewingRestrictionId === restriction.id" @click="reviewRestriction(restriction, 'uphold_appeal')">维持限制</el-button>
                </div>
              </article>
            </section>
            <article v-for="report in moderationStatus === 'reports' ? moderationReports : []" :key="report.id" style="border-top: 1px solid var(--el-border-color); padding: 12px 0">
              <strong>{{ report.article_title }}</strong>
              <p>{{ report.comment_content }}</p>
              <small>举报者：{{ report.reporter_name }} · 原因：{{ report.reason }} · {{ report.detail || '无补充说明' }} · {{ report.created_at }}</small>
              <div style="display: flex; gap: 8px; margin-top: 8px">
                <el-button size="small" type="danger" :loading="reviewingReportId === report.id" @click="reviewReport(report, 'hide')">隐藏评论</el-button>
                <el-button size="small" :loading="reviewingReportId === report.id" @click="reviewReport(report, 'dismiss')">驳回举报</el-button>
              </div>
            </article>
            <article v-for="comment in moderationStatus === 'pending' || moderationStatus === 'approved' ? moderationComments : []" :key="comment.id" style="border-top: 1px solid var(--el-border-color); padding: 12px 0">
              <strong>{{ comment.article_title }}</strong>
              <blockquote v-if="comment.quote">引用原文：{{ comment.quote }}</blockquote>
              <p>{{ comment.content }}</p>
              <small>{{ comment.author_name }} · {{ comment.created_at }}</small>
              <div style="display: flex; gap: 8px; margin-top: 8px">
                <el-button v-if="moderationStatus === 'pending'" size="small" type="primary" :loading="moderatingCommentId === comment.id" @click="moderateComment(comment, 'approve')">批准公开</el-button>
                <el-button size="small" :loading="moderatingCommentId === comment.id" @click="moderateComment(comment, 'reject')">{{ moderationStatus === 'approved' ? '隐藏' : '拒绝' }}</el-button>
              </div>
            </article>
          </el-dialog>

          <el-dialog v-model="reportDialogOpen" title="举报评论" width="480px" align-center>
            <p>请选择原因。举报内容仅管理员可见。</p>
            <el-select v-model="reportReason" aria-label="举报原因" style="width: 100%">
              <el-option label="垃圾广告" value="spam" />
              <el-option label="攻击或骚扰" value="abuse" />
              <el-option label="其他" value="other" />
            </el-select>
            <el-input v-model="reportDetail" type="textarea" :rows="3" :maxlength="500" show-word-limit placeholder="补充说明（可选）" style="margin-top: 12px" />
            <template #footer>
              <el-button @click="reportDialogOpen = false">取消</el-button>
              <el-button type="primary" :loading="submittingReport" @click="submitReport">提交举报</el-button>
            </template>
          </el-dialog>

          <ArticleDetail
            v-if="currentArticle"
            ref="articleDetailRef"
            :article="currentArticle"
            :comment-draft="commentDraft"
            :comment-author="auth.session.actor"
            :can-comment="auth.isAuthenticated"
            :can-report="auth.isAuthenticated && !myRestriction?.active"
            :restriction-message="myRestriction?.active ? `评论与举报功能已暂停至 ${new Date(myRestriction.expires_at).toLocaleString('zh-CN')}，可提交申诉。` : ''"
            :can-delete="auth.session.role === 'admin' && auth.isAuthenticated"
            :can-sync="auth.isAuthenticated && auth.session.role !== 'visitor'"
            :can-edit="auth.isAuthenticated && (auth.session.role === 'admin' || auth.session.role === 'operator' || currentArticle.author_name.toLocaleLowerCase() === auth.session.actor.toLocaleLowerCase())"
            :can-take-notes="auth.isAuthenticated"
            :draft-owner="authenticatedDraftOwner"
            :upload-handler="handleEditorUpload"
            :publishing="publishing"
            :submitting-comment="submittingComment"
            :deleting-slug="deletingArticleSlug"
            :related-articles="relatedArticles"
            :related-loading="relatedLoading"
            :collection-context="collectionContext"
            @back="returnToArticleList"
            @ask-agent="askAgent"
            @sync="syncArticleKnowledge"
            @remove="deleteArticle"
            @submit-comment="submitComment"
            @report-comment="openReportDialog"
            @open-appeal="restrictionDialogOpen = true"
            @open-related="openRelatedArticle"
            @revision-submitted="handleInlineRevisionSubmitted"
            @comment-published="refreshPublishedComment"
            @take-note="openPrivateNotes"
          />
          <ArticleList
            v-else
            :articles="articles"
            :total="articleTotal"
            :page="articlePage"
            :pages="articlePages"
            :page-size="articlePageSize"
            :deleting-slug="deletingArticleSlug"
            :active-category="activeCategory"
            :categories="categories"
            :can-delete="auth.session.role === 'admin' && auth.isAuthenticated"
            @open="openArticle"
            @remove="deleteArticle"
            @filter-category="filterByCategory"
            @clear-filter="clearCategoryFilter"
            @page-change="changeArticlePage"
            @clear-all-filters="clearDiscoveryFilters"
          />
        </main>

        <button
          v-show="rightPanelVisible && !currentArticle"
          class="panel-resizer right-panel-resizer"
          type="button"
          aria-label="拖动调整辅助栏宽度"
          title="拖动调整辅助栏宽度"
          @pointerdown="startPanelResize('right', $event)"
        />

        <BlogSidebar
          v-show="rightPanelVisible && !currentArticle"
          :archive="archive"
          :about="about"
        />
      </section>

      <el-dialog v-model="approvalDialogOpen" title="审批博客操作" width="560px" align-center>
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
          <p v-if="pendingApproval.result" class="approval-result">{{ pendingApproval.result }}</p>
        </section>
        <template #footer>
          <el-button :loading="reviewingApproval" @click="reviewCurrentApproval('reject')">拒绝</el-button>
          <el-button type="primary" :loading="reviewingApproval" @click="reviewCurrentApproval('approve')">
            批准并执行
          </el-button>
        </template>
      </el-dialog>
    </section>

    <footer v-if="siteSettings?.footer_text" class="blog-site-footer">{{ siteSettings.footer_text }}</footer>
    <BlogAgentWidget
      v-model:open="blogAgentOpen"
      v-model:input="blogAgentInput"
      v-model:source="blogAgentSource"
      :loading="blogAgentLoading"
      :messages="blogAgentMessages"
      :suggestions="blogAgentSuggestions"
      @send="sendBlogAgentMessage"
      @keydown="handleBlogAgentKeydown"
    />
  </div>
</template>

<style scoped>
.blog-site-footer {
  padding: 20px 16px 28px;
  text-align: center;
  color: var(--color-text-secondary, #6b7a72);
  font-size: 12px;
  border-top: 1px solid var(--color-divider, #e4e8e2);
}
.clip-status-alert { margin-bottom: 10px; }
</style>
