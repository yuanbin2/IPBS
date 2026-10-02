<script setup lang="ts">
import { computed, ref, nextTick, watch, onMounted, onBeforeUnmount } from "vue";
import { ChatDotRound, Delete, ArrowLeft, Loading, View, Notebook } from "@element-plus/icons-vue";
import { MdPreview, type HeadList } from "md-editor-v3";
import type { BlogArticle, BlogComment, PrivateNote } from "../types";
import { useThemeStore } from "../stores/themeStore";
import { applyThemeToElement } from "../themes/applyTheme";
import xss from "xss";
import ThemeSwitcher from "./ThemeSwitcher.vue";
import ThemeCreator from "./ThemeCreator.vue";
import InlineArticleEditor from "./InlineArticleEditor.vue";
import type { DraftOwner } from "../utils/draftStorage";

const props = defineProps<{
  article: BlogArticle;
  commentDraft: { content: string };
  commentAuthor: string;
  canComment: boolean;
  canReport: boolean;
  restrictionMessage: string;
  canDelete: boolean;
  canSync: boolean;
  canEdit: boolean;
  canTakeNotes: boolean;
  draftOwner: DraftOwner | null;
  uploadHandler: (files: File[]) => Promise<Array<{ url: string; alt?: string; title?: string }>>;
  publishing: boolean;
  submittingComment: boolean;
  deletingSlug: string;
  relatedArticles: BlogArticle[];
  relatedLoading: boolean;
}>();

const emit = defineEmits<{
  back: [];
  askAgent: [article: BlogArticle];
  sync: [article: BlogArticle];
  remove: [article: BlogArticle];
  submitComment: [article: BlogArticle];
  reportComment: [comment: BlogComment];
  openAppeal: [];
  openRelated: [article: BlogArticle];
  revisionSubmitted: [];
  commentPublished: [];
  takeNote: [article: BlogArticle, quote: string];
}>();

const headings = ref<HeadList[]>([]);
const editorHeadings = ref<Array<{ text: string; level: number }>>([]);
const activeHeadingIndex = ref(0);
const contentRef = ref<HTMLElement>();
const collapsedSections = ref<Set<number>>(new Set());
const themeStore = useThemeStore();
const articleThemeRef = ref<HTMLElement>();
const readingProgress = ref(0);
const inlineEditing = computed(() => Boolean(props.canEdit && props.draftOwner));
const outlineHeadings = computed(() => inlineEditing.value ? editorHeadings.value : headings.value);
const inlineEditorRef = ref<InstanceType<typeof InlineArticleEditor>>();
const editorDirty = ref(false);
const canQuotePublished = computed(() => props.canComment && (!inlineEditing.value || (!editorDirty.value && !props.article.pending_revision)));
const selectedArticleQuote = ref("");
const selectedArticleOffset = ref<number | null>(null);
const annotationNotes = ref<PrivateNote[]>([]);
const annotationsOpen = ref(!window.matchMedia("(max-width: 900px)").matches);
const annotationsLoading = ref(false);
const annotationError = ref("");
const annotationContent = ref("");
const annotationSaving = ref(false);
const publicAnnotationContent = ref("");
const publicAnnotationSaving = ref(false);
const publicAnnotationMessage = ref("");
const annotationPage = ref(1);
const annotationPages = ref(0);
const editingAnnotationId = ref<number | null>(null);
type CommentKind = "quote" | "plain";
type CommentPage = {
  items: BlogComment[];
  total: number;
  nextBeforeId: number | null;
  cursors: Array<number | null>;
  index: number;
  loading: boolean;
  loaded: boolean;
  error: string;
};
const newCommentPage = (): CommentPage => ({ items: [], total: 0, nextBeforeId: null, cursors: [null], index: 0, loading: false, loaded: false, error: "" });
const quotePage = ref<CommentPage>(newCommentPage());
const plainPage = ref<CommentPage>(newCommentPage());
const plainVisible = ref(false);
const commentSectionRef = ref<HTMLElement>();
let commentSectionObserver: IntersectionObserver | undefined;
const commentSequences: Record<CommentKind, number> = { quote: 0, plain: 0 };
const publicAnnotations = computed(() => quotePage.value.items);
const expandedQuotes = ref<Set<number>>(new Set());
function toggleQuote(id: number) {
  const next = new Set(expandedQuotes.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedQuotes.value = next;
}

async function loadCommentPage(kind: CommentKind, cursor: number | null = null, targetIndex = 0) {
  if (props.article.status !== "published") return;
  const state = kind === "quote" ? quotePage : plainPage;
  const slug = props.article.slug;
  const sequence = ++commentSequences[kind];
  state.value.loading = true;
  state.value.error = "";
  try {
    const params = new URLSearchParams({ kind, limit: "20" });
    if (cursor !== null) params.set("before_id", String(cursor));
    const response = await fetch(`/api/agent/blog/articles/${encodeURIComponent(slug)}/comments/?${params}`);
    if (!response.ok) throw new Error("评论加载失败，请重试");
    const page = await response.json() as { items: BlogComment[]; total: number; next_before_id: number | null };
    if (sequence !== commentSequences[kind] || props.article.slug !== slug) return;
    state.value.items = page.items;
    state.value.total = page.total;
    state.value.nextBeforeId = page.next_before_id;
    state.value.index = targetIndex;
    state.value.cursors = state.value.cursors.slice(0, targetIndex + 1);
    state.value.cursors[targetIndex] = cursor;
    state.value.loaded = true;
  } catch (cause) {
    if (sequence === commentSequences[kind] && props.article.slug === slug) {
      state.value.error = cause instanceof Error ? cause.message : "评论加载失败，请重试";
    }
  } finally {
    if (sequence === commentSequences[kind]) state.value.loading = false;
  }
}

function moveCommentPage(kind: CommentKind, direction: -1 | 1) {
  const state = (kind === "quote" ? quotePage : plainPage).value;
  if (state.loading) return;
  if (direction === 1 && state.nextBeforeId !== null) {
    void loadCommentPage(kind, state.nextBeforeId, state.index + 1);
  } else if (direction === -1 && state.index > 0) {
    void loadCommentPage(kind, state.cursors[state.index - 1] ?? null, state.index - 1);
  }
}

watch(() => [props.article.slug, props.article.status, props.article.comment_count], () => {
  commentSequences.quote++;
  commentSequences.plain++;
  quotePage.value = newCommentPage();
  plainPage.value = newCommentPage();
  expandedQuotes.value = new Set();
  if (annotationsOpen.value) void loadCommentPage("quote");
  if (plainVisible.value) void loadCommentPage("plain");
}, { immediate: true });
watch(annotationsOpen, (open) => {
  if (open && !quotePage.value.loaded && !quotePage.value.loading) void loadCommentPage("quote");
});
let highlightTimer: ReturnType<typeof setTimeout> | undefined;
let annotationObserver: MutationObserver | undefined;
const highlightName = "blog-private-annotations";
const publicHighlightName = "blog-public-comments";
const rendererClass = /^(?:md-editor-[a-z0-9_-]+|hljs(?:-[a-z0-9_-]+)?|language-[a-z0-9_-]+|katex(?:-[a-z0-9_-]+)?)$/i;
const sanitizeArticleHtml = (html: string) => xss(html, {
  stripIgnoreTag: true,
  stripIgnoreTagBody: ["script", "style"],
  onTagAttr: (tag, name, value) => {
    if (name === "id" && /^h[1-6]$/.test(tag) && /^heading-\d+$/.test(value)) {
      return `id="${value}"`;
    }
    if (name !== "class") return undefined;
    // The previewer needs these classes to lay out code blocks and math.
    // Keep all other HTML attributes under xss's default allowlist.
    const classes = value.split(/\s+/).filter((token) => rendererClass.test(token)).slice(0, 24);
    return classes.length ? `class="${classes.join(" ")}"` : "";
  },
});

const readingMinutes = computed(() => {
  const text = (props.article.content || "").replace(/```[\s\S]*?```/g, "").replace(/\s+/g, "");
  return Math.max(1, Math.ceil(text.length / 450));
});

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric"
  }).format(new Date(dateStr));
}

function handleArticleScroll(event: Event) {
  const element = event.currentTarget as HTMLElement;
  const scrollable = element.scrollHeight - element.clientHeight;
  readingProgress.value = scrollable > 0 ? Math.min(100, Math.round((element.scrollTop / scrollable) * 100)) : 100;
  const preview = element.querySelector(inlineEditing.value ? '.inline-article-editor .vditor-wysiwyg' : '.md-editor-preview');
  const articleHeadings = preview?.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6');
  if (!articleHeadings?.length) return;
  const visibleTop = element.getBoundingClientRect().top + 56;
  let active = 0;
  articleHeadings.forEach((heading, index) => {
    if (heading.getBoundingClientRect().top <= visibleTop) active = index;
  });
  if (activeHeadingIndex.value !== active) activeHeadingIndex.value = active;
}

// Apply theme to article content
function applyCurrentTheme() {
  if (articleThemeRef.value) {
    applyThemeToElement(articleThemeRef.value, themeStore.currentTheme);
  }
}

// Watch for theme changes
watch(() => themeStore.currentTheme, () => {
  applyCurrentTheme();
}, { deep: true });

onMounted(() => {
  applyCurrentTheme();
});

// 自定义标题 ID 生成函数
function generateHeadingId(options: { text: string; level: number; index: number }) {
  return `heading-${options.index}`;
}

// 获取目录
function handleGetCatalog(list: HeadList[]) {
  headings.value = list;
  nextTick(() => applyCollapsibleSections());
}

function refreshEditorOutline() {
  if (!inlineEditing.value) return;
  const elements = contentRef.value?.querySelectorAll<HTMLElement>(
    '.inline-article-editor .vditor-wysiwyg h1, .inline-article-editor .vditor-wysiwyg h2, .inline-article-editor .vditor-wysiwyg h3, .inline-article-editor .vditor-wysiwyg h4, .inline-article-editor .vditor-wysiwyg h5, .inline-article-editor .vditor-wysiwyg h6'
  );
  const next = Array.from(elements ?? []).map((element) => ({
    text: (element.textContent || '').replace(/[\u200b-\u200d\ufeff]/g, '').trim(),
    level: Number(element.tagName.slice(1)),
  }));
  if (JSON.stringify(next) !== JSON.stringify(editorHeadings.value)) editorHeadings.value = next;
}

// 跳转到标题
function scrollToHeading(index: number) {
  const main = contentRef.value;
  const preview = main?.querySelector(inlineEditing.value ? '.inline-article-editor .vditor-wysiwyg' : '.md-editor-preview');
  const element = preview?.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6').item(index);
  if (!main || !element) return;

  if (!inlineEditing.value) {
    // A heading inside a folded parent cannot be measured or scrolled into view.
    const foldedParents: HTMLElement[] = [];
    for (let parent = element.parentElement; parent && parent !== preview; parent = parent.parentElement) {
      if (parent.classList.contains('collapsible-section-wrapper') && parent.classList.contains('collapsed')) {
        foldedParents.push(parent);
      }
    }
    for (const parent of foldedParents.reverse()) {
      const sectionIndex = Number(parent.dataset.sectionIndex);
      if (Number.isInteger(sectionIndex)) toggleSection(sectionIndex);
    }
  }

  activeHeadingIndex.value = index;
  requestAnimationFrame(() => {
    if (!element.isConnected) return;
    const top = element.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop - 12;
    main.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
  });
}

// 应用折叠功能到所有标题 (H1-H6)
function applyCollapsibleSections() {
  if (!contentRef.value) return;

  // 清理旧的折叠包装器
  contentRef.value.querySelectorAll('.collapsible-section-wrapper').forEach(wrapper => {
    const parent = wrapper.parentNode;
    if (!parent) return;
    while (wrapper.firstChild) {
      parent.insertBefore(wrapper.firstChild, wrapper);
    }
    parent.removeChild(wrapper);
  });

  // 移除旧的折叠按钮
  contentRef.value.querySelectorAll('.section-toggle-btn').forEach(btn => btn.remove());

  const previewEl = contentRef.value.querySelector('.md-editor-preview');
  if (!previewEl) return;

  // 找到所有标题 (H1-H6)
  const allHeadings = previewEl.querySelectorAll('h1, h2, h3, h4, h5, h6');
  if (allHeadings.length < 2) return; // 只有一个或没有标题时不添加折叠

  // 获取标题级别 (1-6)
  function getHeadingLevel(el: Element): number {
    return parseInt(el.tagName.charAt(1));
  }

  let sectionIndex = 0;

  allHeadings.forEach((heading) => {
    const currentLevel = getHeadingLevel(heading);

    // 收集此标题到下一个同级或更高级标题之间的所有元素
    const sectionContent: Element[] = [];
    let nextSibling = heading.nextElementSibling;

    while (nextSibling) {
      // 如果遇到标题，检查级别
      if (/^H[1-6]$/.test(nextSibling.tagName)) {
        const nextLevel = getHeadingLevel(nextSibling);
        // 如果下一个标题级别 <= 当前级别 (更高级或同级)，停止收集
        if (nextLevel <= currentLevel) break;
      }
      sectionContent.push(nextSibling);
      nextSibling = nextSibling.nextElementSibling;
    }

    // 只有当有内容可折叠时才添加按钮
    if (sectionContent.length === 0) return;

    const currentIndex = sectionIndex++;

    // 创建折叠按钮
    const toggleBtn = document.createElement('button');
    toggleBtn.className = `section-toggle-btn level-${currentLevel}`;
    toggleBtn.setAttribute('data-section-index', String(currentIndex));
    toggleBtn.innerHTML = `<span class="toggle-icon">${collapsedSections.value.has(currentIndex) ? '▶' : '▼'}</span>`;
    toggleBtn.title = collapsedSections.value.has(currentIndex) ? '展开此章节' : '折叠此章节';

    // 添加点击事件
    toggleBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleSection(currentIndex);
    });

    // 在标题前插入按钮
    heading.insertBefore(toggleBtn, heading.firstChild);
    heading.classList.add('collapsible-heading');

    // 创建包裹器
    const wrapper = document.createElement('div');
    wrapper.className = `collapsible-section-wrapper${collapsedSections.value.has(currentIndex) ? ' collapsed' : ''}`;
    wrapper.setAttribute('data-section-index', String(currentIndex));

    // 将内容移入包裹器
    const parent = heading.parentNode;
    if (parent) {
      parent.insertBefore(wrapper, heading.nextSibling);
      sectionContent.forEach(el => wrapper.appendChild(el));
    }
  });
}

// 切换章节折叠状态
function toggleSection(index: number) {
  if (collapsedSections.value.has(index)) {
    collapsedSections.value.delete(index);
  } else {
    collapsedSections.value.add(index);
  }

  // 直接操作 DOM 更新状态
  if (!contentRef.value) return;

  const wrapper = contentRef.value.querySelector(`.collapsible-section-wrapper[data-section-index="${index}"]`);
  const toggleBtn = contentRef.value.querySelector(`.section-toggle-btn[data-section-index="${index}"] .toggle-icon`);

  if (wrapper) {
    wrapper.classList.toggle('collapsed');
  }
  if (toggleBtn) {
    toggleBtn.textContent = collapsedSections.value.has(index) ? '▶' : '▼';
  }
}

// 监听文章内容变化，重新应用折叠
watch(() => props.article.content, () => {
  collapsedSections.value.clear();
  nextTick(() => applyCollapsibleSections());
});

function excerpt(text: string, maxLen = 60): string {
  if (!text) return "";
  return text.length > maxLen ? text.slice(0, maxLen) + "..." : text;
}

function annotationSurface(): HTMLElement | null {
  return contentRef.value?.querySelector<HTMLElement>(
    inlineEditing.value ? '.vditor-wysiwyg [contenteditable="true"]' : ".md-editor-preview"
  ) ?? null;
}

function compactText(value: string): string {
  return value.replace(/[\u200b-\u200d\ufeff\s]/g, "");
}

function captureSelection() {
  const surface = annotationSurface();
  const selection = window.getSelection();
  if (!surface || !selection?.rangeCount || selection.isCollapsed) return;
  const range = selection.getRangeAt(0);
  if (!surface.contains(range.commonAncestorContainer)) return;
  const quote = selection.toString().trim().slice(0, 2000);
  if (!quote) return;
  const prefix = document.createRange();
  prefix.selectNodeContents(surface);
  prefix.setEnd(range.startContainer, range.startOffset);
  selectedArticleQuote.value = quote;
  selectedArticleOffset.value = compactText(prefix.toString()).length;
  if (props.canTakeNotes || props.canComment) annotationsOpen.value = true;
}

function clearSelectedQuote() {
  selectedArticleQuote.value = "";
  selectedArticleOffset.value = null;
  window.getSelection()?.removeAllRanges();
}

function textPositions(root: HTMLElement) {
  const chars: Array<{ node: Text; offset: number; value: string }> = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    for (let offset = 0; offset < node.data.length; offset++) {
      const value = node.data[offset];
      if (!/[\u200b-\u200d\ufeff\s]/.test(value)) chars.push({ node, offset, value });
    }
  }
  return chars;
}

function rangeForNote(note: Pick<PrivateNote, "quote" | "anchor_offset">, chars: ReturnType<typeof textPositions>, fullText: string): Range | null {
  const quote = compactText(note.quote);
  if (!quote) return null;
  const matches: number[] = [];
  let position = fullText.indexOf(quote);
  while (position !== -1) {
    matches.push(position);
    position = fullText.indexOf(quote, position + 1);
  }
  if (!matches.length) return null;
  const start = note.anchor_offset === null
    ? matches[0]
    : matches.reduce((closest, next) =>
        Math.abs(next - note.anchor_offset!) < Math.abs(closest - note.anchor_offset!) ? next : closest
      );
  const first = chars[start];
  const last = chars[start + quote.length - 1];
  if (!first || !last) return null;
  const range = document.createRange();
  range.setStart(first.node, first.offset);
  range.setEnd(last.node, last.offset + 1);
  return range;
}

function applyAnnotationHighlights() {
  const registry = (CSS as unknown as { highlights?: { set: (name: string, highlight: unknown) => void; delete: (name: string) => void } }).highlights;
  const HighlightClass = (window as unknown as { Highlight?: new (...ranges: Range[]) => unknown }).Highlight;
  registry?.delete(highlightName);
  registry?.delete(publicHighlightName);
  const surface = annotationSurface();
  if (!surface || !registry || !HighlightClass) return;
  const chars = textPositions(surface);
  const fullText = chars.map((item) => item.value).join("");
  const ranges = annotationNotes.value
    .map((note) => rangeForNote(note, chars, fullText))
    .filter((range): range is Range => range !== null);
  if (ranges.length) registry.set(highlightName, new HighlightClass(...ranges));
  const publicRanges = publicAnnotations.value
    .map((comment) => rangeForNote(comment, chars, fullText))
    .filter((range): range is Range => range !== null);
  if (publicRanges.length) registry.set(publicHighlightName, new HighlightClass(...publicRanges));
}

function scheduleHighlights() {
  if (highlightTimer) clearTimeout(highlightTimer);
  highlightTimer = setTimeout(() => {
    applyAnnotationHighlights();
    refreshEditorOutline();
  }, 120);
}

let annotationLoadSequence = 0;
async function loadAnnotations(reset = true) {
  if (!props.canTakeNotes) {
    annotationNotes.value = [];
    return;
  }
  const sequence = ++annotationLoadSequence;
  if (reset) {
    annotationPage.value = 1;
    annotationNotes.value = [];
  }
  annotationsLoading.value = true;
  annotationError.value = "";
  try {
    const params = new URLSearchParams({
      source_article: String(props.article.id),
      page: String(annotationPage.value),
      page_size: "50"
    });
    const response = await fetch("/api/agent/blog/notes/?" + params.toString());
    const data = await response.json();
    if (!response.ok) throw new Error(data?.detail || "旁注读取失败");
    if (sequence !== annotationLoadSequence) return;
    annotationNotes.value = reset ? data.items : [...annotationNotes.value, ...data.items];
    annotationPages.value = data.pages;
    scheduleHighlights();
  } catch (cause) {
    if (sequence === annotationLoadSequence) {
      annotationError.value = cause instanceof Error ? cause.message : "旁注读取失败";
    }
  } finally {
    if (sequence === annotationLoadSequence) annotationsLoading.value = false;
  }
}

async function moreAnnotations() {
  if (annotationPage.value >= annotationPages.value) return;
  annotationPage.value += 1;
  await loadAnnotations(false);
}

async function saveAnnotation(kind: "highlight" | "comment") {
  const quote = selectedArticleQuote.value.trim();
  const content = kind === "comment" ? annotationContent.value.trim() : "";
  if (!quote) {
    annotationError.value = "请先在正文中选中要标记的文字。";
    return;
  }
  if (kind === "comment" && !content) {
    annotationError.value = "请写下旁注内容。";
    return;
  }
  annotationSaving.value = true;
  annotationError.value = "";
  try {
    const response = await fetch("/api/agent/blog/notes/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: (kind === "highlight" ? "高亮" : "旁注") + " · " + excerpt(quote, 45),
        content,
        quote,
        anchor_offset: selectedArticleOffset.value,
        source_article: props.article.id
      })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || "保存失败");
    annotationContent.value = "";
    clearSelectedQuote();
    await loadAnnotations();
  } catch (cause) {
    annotationError.value = cause instanceof Error ? cause.message : "保存失败";
  } finally {
    annotationSaving.value = false;
  }
}

async function submitPublicAnnotation() {
  const quote = selectedArticleQuote.value.trim();
  const content = publicAnnotationContent.value.trim();
  if (!quote || !content || !canQuotePublished.value) return;
  publicAnnotationSaving.value = true;
  publicAnnotationMessage.value = "";
  try {
    const response = await fetch(`/api/agent/blog/articles/${encodeURIComponent(props.article.slug)}/comments/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, quote, anchor_offset: selectedArticleOffset.value })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || "评论提交失败");
    publicAnnotationContent.value = "";
    publicAnnotationMessage.value = "评论已公开，其他读者现在可以在文章侧边看到。";
    clearSelectedQuote();
    emit("commentPublished");
  } catch (cause) {
    annotationError.value = cause instanceof Error ? cause.message : "评论提交失败";
  } finally {
    publicAnnotationSaving.value = false;
  }
}

async function updateAnnotation(note: PrivateNote) {
  annotationSaving.value = true;
  annotationError.value = "";
  try {
    const response = await fetch("/api/agent/blog/notes/" + note.id + "/", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: annotationContent.value.trim(), version: note.version })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || "更新失败");
    editingAnnotationId.value = null;
    annotationContent.value = "";
    await loadAnnotations();
  } catch (cause) {
    annotationError.value = cause instanceof Error ? cause.message : "更新失败";
  } finally {
    annotationSaving.value = false;
  }
}

async function deleteAnnotation(note: PrivateNote) {
  if (!window.confirm("删除这条私人高亮或旁注？可在笔记回收站恢复。")) return;
  annotationError.value = "";
  try {
    const response = await fetch("/api/agent/blog/notes/" + note.id + "/", { method: "DELETE" });
    if (!response.ok) throw new Error("删除失败");
    await loadAnnotations();
  } catch (cause) {
    annotationError.value = cause instanceof Error ? cause.message : "删除失败";
  }
}

function jumpToAnnotation(note: Pick<PrivateNote, "quote" | "anchor_offset">) {
  const surface = annotationSurface();
  if (!surface) return;
  const chars = textPositions(surface);
  const range = rangeForNote(note, chars, chars.map((item) => item.value).join(""));
  const element = range?.startContainer.parentElement;
  if (element) element.scrollIntoView({ behavior: "smooth", block: "center" });
  else annotationError.value = "文章内容已变化，暂时无法定位这段摘录。";
}

function jumpToPublicComment(comment: BlogComment) {
  jumpToAnnotation(comment);
}

watch(() => [props.article.id, props.canTakeNotes], () => {
  clearSelectedQuote();
  void loadAnnotations();
}, { immediate: true });
watch([annotationNotes, publicAnnotations, inlineEditing], () => nextTick(scheduleHighlights));
onMounted(() => {
  if (articleThemeRef.value) {
    annotationObserver = new MutationObserver(scheduleHighlights);
    annotationObserver.observe(articleThemeRef.value, { childList: true, characterData: true, subtree: true });
  }
  if (commentSectionRef.value && "IntersectionObserver" in window) {
    commentSectionObserver = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      plainVisible.value = true;
      if (!plainPage.value.loaded && !plainPage.value.loading) void loadCommentPage("plain");
    }, { root: contentRef.value, rootMargin: "300px" });
    commentSectionObserver.observe(commentSectionRef.value);
  } else {
    plainVisible.value = true;
    void loadCommentPage("plain");
  }
  scheduleHighlights();
});
onBeforeUnmount(() => {
  commentSectionObserver?.disconnect();
  commentSequences.quote++;
  commentSequences.plain++;
  annotationObserver?.disconnect();
  if (highlightTimer) clearTimeout(highlightTimer);
  (CSS as unknown as { highlights?: { delete: (name: string) => void } }).highlights?.delete(highlightName);
  (CSS as unknown as { highlights?: { delete: (name: string) => void } }).highlights?.delete(publicHighlightName);
});

function leaveEditor(): boolean {
  if (!inlineEditing.value) return true;
  inlineEditorRef.value?.persistDraft();
  if (inlineEditorRef.value?.hasUnsavedChanges() && !window.confirm("修改已保存在本机，确定离开文章吗？")) return false;
  return true;
}

function backToList() {
  if (leaveEditor()) emit("back");
}

function openRelatedArticle(article: BlogArticle) {
  if (leaveEditor()) emit("openRelated", article);
}

function revisionSubmitted() {
  emit("revisionSubmitted");
}

function takeNote() {
  captureSelection();
  const selected = selectedArticleQuote.value;
  clearSelectedQuote();
  emit("takeNote", props.article, selected);
}

watch(() => props.article.slug, () => {
  editorDirty.value = false;
  editorHeadings.value = [];
  annotationContent.value = "";
  editingAnnotationId.value = null;
});
defineExpose({ confirmLeave: leaveEditor });
</script>

<template>
  <section class="article-detail-fullscreen">
    <div class="reading-progress" aria-hidden="true">
      <span :style="{ width: `${readingProgress}%` }" />
    </div>
    <!-- 顶部导航栏 -->
    <header class="article-header">
      <button class="back-button" type="button" @click="backToList">
        <el-icon><ArrowLeft /></el-icon>
        返回文章列表
      </button>
      <div class="article-header-context">
        <strong>技术文章</strong>
        <span>/</span>
        <span>{{ article.category?.name || "未分类" }}</span>
      </div>
      <div class="article-actions-bar">
        <ThemeSwitcher />
        <el-button v-if="canTakeNotes" :icon="Notebook" @pointerdown="captureSelection" @click="takeNote">笔记本</el-button>
        <el-button type="primary" :icon="ChatDotRound" @click="$emit('askAgent', article)">让 Agent 总结</el-button>
        <el-button
          v-if="canSync && !article.knowledge_document_id"
          :loading="publishing"
          @click="$emit('sync', article)"
        >
          同步到知识库
        </el-button>
        <el-button
          v-if="canDelete"
          type="danger"
          plain
          :icon="Delete"
          :loading="deletingSlug === article.slug"
          @click="$emit('remove', article)"
        >
          删除
        </el-button>
      </div>
    </header>

    <!-- 主内容区域 -->
    <div class="article-content-wrapper" :class="{ 'is-editing': inlineEditing, 'has-outline': outlineHeadings.length > 0 }">
      <!-- 左侧大纲 -->
      <aside class="article-outline" v-if="outlineHeadings.length">
        <div class="outline-header">
          <span>本文目录</span>
          <small>{{ outlineHeadings.length }} 节</small>
        </div>
        <nav class="outline-nav">
          <a
            v-for="(item, index) in outlineHeadings"
            :key="index"
            :href="inlineEditing ? '#' : `#heading-${index + 1}`"
            :class="['outline-item', `level-${item.level}`, { active: activeHeadingIndex === index }]"
            @click.prevent="scrollToHeading(index)"
          >
            {{ item.text }}
          </a>
        </nav>
      </aside>

      <!-- 右侧文章内容 -->
      <main class="article-main" ref="contentRef" @scroll="handleArticleScroll" @mouseup="captureSelection" @keyup="captureSelection">
        <div ref="articleThemeRef" class="article-theme-container">
          <div class="article-breadcrumb">
            <span>文章</span><b>/</b><strong>{{ article.category?.name || "未分类" }}</strong>
          </div>
          <template v-if="!inlineEditing">
            <h1 class="article-title">{{ article.title }}</h1>
            <p v-if="article.summary" class="article-summary">{{ article.summary }}</p>
            <div class="article-byline">
              <div class="author-avatar">{{ (article.author_name || "匿").charAt(0).toUpperCase() }}</div>
              <div class="author-copy">
                <strong>{{ article.author_name || "匿名作者" }}</strong>
                <span>{{ formatDate(article.published_at || article.created_at) }} · 约 {{ readingMinutes }} 分钟阅读</span>
              </div>
              <div class="article-metrics">
                <span><el-icon><View /></el-icon>{{ article.view_count }} 浏览</span>
                <span>{{ article.comment_count }} 评论</span>
                <span v-if="article.knowledge_document_id" class="knowledge-status">已收录知识库</span>
              </div>
            </div>
            <div class="tag-row article-tags" v-if="article.tags.length">
              <span v-for="tag in article.tags" :key="tag.id"># {{ tag.name }}</span>
            </div>
            <div class="article-cover" v-if="article.cover_image">
              <img :src="article.cover_image" :alt="article.title" />
            </div>
            <div class="article-read-body">
              <MdPreview
                :model-value="article.content || ''"
                :sanitize="sanitizeArticleHtml"
                language="zh-CN"
                preview-theme="github"
                code-theme="github"
                :show-code-row-number="true"
                :md-heading-id="generateHeadingId"
                @onGetCatalog="handleGetCatalog"
                class="article-content blog-md-preview"
              />
            </div>
          </template>
          <InlineArticleEditor
            v-else-if="draftOwner"
            :key="article.id"
            ref="inlineEditorRef"
            :article="article"
            :owner="draftOwner"
            :upload-handler="uploadHandler"
            @saved="revisionSubmitted"
            @dirty-change="editorDirty = $event"
            @ready="refreshEditorOutline"
          >
            <template #byline>
              <div class="article-byline">
                <div class="author-avatar">{{ (article.author_name || "匿").charAt(0).toUpperCase() }}</div>
                <div class="author-copy">
                  <strong>{{ article.author_name || "匿名作者" }}</strong>
                  <span>{{ formatDate(article.published_at || article.created_at) }} · 约 {{ readingMinutes }} 分钟阅读</span>
                </div>
                <div class="article-metrics">
                  <span><el-icon><View /></el-icon>{{ article.view_count }} 浏览</span>
                  <span>{{ article.comment_count }} 评论</span>
                  <span v-if="article.knowledge_document_id" class="knowledge-status">已收录知识库</span>
                </div>
              </div>
            </template>
          </InlineArticleEditor>
        </div>

        <!-- 相关推荐 -->
        <section class="related-articles" v-if="relatedArticles.length">
          <h3>相关推荐</h3>
          <div class="related-grid">
            <article
              v-for="related in relatedArticles"
              :key="related.id"
              class="related-card"
              @click="openRelatedArticle(related)"
            >
              <div class="related-cover" v-if="related.cover_image">
                <img :src="related.cover_image" :alt="related.title" loading="lazy" />
              </div>
              <div class="related-cover placeholder" v-else>
                <span>{{ related.title.charAt(0) }}</span>
              </div>
              <div class="related-info">
                <h4>{{ related.title }}</h4>
                <p>{{ excerpt(related.summary) }}</p>
                <footer>
                  <span v-if="related.category">{{ related.category.name }}</span>
                  <span>{{ related.view_count }} 浏览</span>
                </footer>
              </div>
            </article>
          </div>
        </section>

        <div class="related-loading" v-if="relatedLoading">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>正在加载推荐...</span>
        </div>

        <!-- 评论区 -->
        <section ref="commentSectionRef" class="comment-section">
          <h3>评论 <small v-if="plainPage.loaded">{{ plainPage.total }}</small></h3>
          <p v-if="plainPage.loading" role="status">正在加载评论…</p>
          <div v-if="plainPage.error" role="alert">{{ plainPage.error }} <el-button text @click="loadCommentPage('plain', plainPage.cursors[plainPage.index] ?? null, plainPage.index)">重试</el-button></div>
          <p v-if="plainPage.loaded && !plainPage.items.length" class="annotation-empty">暂无评论。</p>
          <article v-for="comment in plainPage.items" :key="comment.id" class="comment-item">
            <strong>{{ comment.author_name }}</strong>
            <p>{{ comment.content }}</p>
            <el-button v-if="canReport" size="small" text @click="$emit('reportComment', comment)">举报评论</el-button>
          </article>
          <nav v-if="plainPage.loaded && plainPage.total > 20" class="comment-page-controls" aria-label="普通评论翻页">
            <span>第 {{ plainPage.index + 1 }} 批 · 本批 {{ plainPage.items.length }} / 共 {{ plainPage.total }}</span>
            <el-button size="small" :disabled="plainPage.loading || plainPage.index === 0" @click="moveCommentPage('plain', -1)">较新评论</el-button>
            <el-button size="small" :disabled="plainPage.loading || plainPage.nextBeforeId === null" @click="moveCommentPage('plain', 1)">更早评论</el-button>
          </nav>
          <div v-if="restrictionMessage" class="comment-login-prompt">
            <p>{{ restrictionMessage }}</p>
            <el-button size="small" @click="$emit('openAppeal')">查看限制与申诉</el-button>
          </div>
          <form v-else-if="canComment" class="comment-form" @submit.prevent="$emit('submitComment', article)">
            <el-input :model-value="commentAuthor" disabled aria-label="评论署名为当前账户" />
            <el-input v-model="commentDraft.content" type="textarea" :rows="3" :maxlength="2000" show-word-limit placeholder="写下你的想法" />
            <el-button type="primary" native-type="submit" :loading="submittingComment">发表评论</el-button>
          </form>
          <p v-else class="comment-login-prompt">
            <RouterLink :to="{ path: '/login', query: { redirect: `/blog/${article.slug}` } }">登录后参与评论</RouterLink>
          </p>
        </section>
      </main>
      <aside v-if="article.status === 'published' || canTakeNotes" class="article-annotations" :class="{ collapsed: !annotationsOpen }" aria-label="高亮与侧边评论">
        <button class="annotation-toggle" type="button" :aria-expanded="annotationsOpen" @click="annotationsOpen = !annotationsOpen">
          <span>高亮与评论 <small v-if="quotePage.loaded">{{ annotationNotes.length + quotePage.total }}</small></span>
          <span aria-hidden="true">{{ annotationsOpen ? "›" : "‹" }}</span>
        </button>
        <div v-if="annotationsOpen" class="annotation-panel-body">
          <p v-if="canTakeNotes" class="annotation-private-hint">选中文字后，可保存私人高亮、私人旁注或提交公开评论。</p>
          <section v-if="selectedArticleQuote && (canTakeNotes || canComment)" class="annotation-selection" aria-label="当前选中的文字">
            <blockquote>{{ selectedArticleQuote }}</blockquote>
            <div v-if="canTakeNotes" class="annotation-action-row">
              <el-button size="small" type="warning" :loading="annotationSaving" @click="saveAnnotation('highlight')">高亮</el-button>
              <el-button size="small" @click="annotationContent = ''; editingAnnotationId = null">添加旁注</el-button>
              <el-button size="small" text @click="clearSelectedQuote">取消</el-button>
            </div>
            <div v-if="canTakeNotes" class="annotation-composer">
              <small>私人旁注 · 仅自己可见</small>
              <el-input v-model="annotationContent" type="textarea" :rows="3" maxlength="50000" aria-label="旁注内容" placeholder="写下你的想法、疑问或待办…" />
              <el-button type="primary" size="small" :loading="annotationSaving" @click="saveAnnotation('comment')">保存旁注</el-button>
            </div>
            <small v-if="canComment && !canQuotePublished" class="annotation-private-hint">当前正文有未提交或待审核的修改；公开划线评论只能引用已发布版本。</small>
            <div v-if="canQuotePublished" class="annotation-composer annotation-public-composer">
              <small>公开评论 · 发布后其他读者立即可见</small>
              <el-input v-model="publicAnnotationContent" type="textarea" :rows="3" maxlength="2000" aria-label="公开划线评论" placeholder="对这段文字发表评论…" />
              <el-button size="small" :disabled="!publicAnnotationContent.trim()" :loading="publicAnnotationSaving" @click="submitPublicAnnotation">提交公开评论</el-button>
            </div>
          </section>
          <p v-if="publicAnnotationMessage" class="annotation-success" role="status">{{ publicAnnotationMessage }}</p>
          <p v-if="annotationError" class="annotation-error" role="alert">{{ annotationError }}</p>
          <h3 v-if="canTakeNotes" class="annotation-section-title">我的高亮与旁注</h3>
          <p v-if="canTakeNotes && annotationsLoading" class="annotation-private-hint">正在读取旁注…</p>
          <p v-else-if="canTakeNotes && !annotationNotes.length" class="annotation-empty">还没有私人标注。</p>
          <div v-if="canTakeNotes && annotationNotes.length" class="annotation-list">
            <article v-for="note in annotationNotes" :key="note.id" class="annotation-card">
              <div class="annotation-card-top">
                <span>{{ note.content.trim() ? "私人旁注" : "高亮" }}</span>
                <time>{{ new Date(note.updated_at).toLocaleDateString("zh-CN") }}</time>
              </div>
              <button class="annotation-quote" type="button" @click="jumpToAnnotation(note)">{{ note.quote }}</button>
              <template v-if="editingAnnotationId === note.id">
                <el-input v-model="annotationContent" type="textarea" :rows="3" maxlength="50000" aria-label="编辑旁注" />
                <div class="annotation-card-actions">
                  <el-button size="small" @click="editingAnnotationId = null; annotationContent = ''">取消</el-button>
                  <el-button size="small" type="primary" :loading="annotationSaving" @click="updateAnnotation(note)">保存</el-button>
                </div>
              </template>
              <MdPreview
                v-else-if="note.content.trim()"
                :model-value="note.content"
                :sanitize="sanitizeArticleHtml"
                language="zh-CN"
                preview-theme="github"
                class="annotation-markdown"
              />
              <div v-if="editingAnnotationId !== note.id" class="annotation-card-actions">
                <el-button size="small" text @click="editingAnnotationId = note.id; annotationContent = note.content">编辑</el-button>
                <el-button size="small" text type="danger" @click="deleteAnnotation(note)">删除</el-button>
              </div>
            </article>
          </div>
          <el-button v-if="annotationPage < annotationPages" :loading="annotationsLoading" @click="moreAnnotations">加载更多</el-button>
          <h3 class="annotation-section-title">公开划线评论 <small v-if="quotePage.loaded">{{ quotePage.total }}</small></h3>
          <p v-if="quotePage.loading" class="annotation-private-hint" role="status">正在加载划线评论…</p>
          <div v-if="quotePage.error" class="annotation-error" role="alert">{{ quotePage.error }} <el-button size="small" text @click="loadCommentPage('quote', quotePage.cursors[quotePage.index] ?? null, quotePage.index)">重试</el-button></div>
          <p v-if="quotePage.loaded && !publicAnnotations.length" class="annotation-empty">还没有公开划线评论。</p>
          <div v-else class="annotation-list">
            <article v-for="comment in publicAnnotations" :key="comment.id" class="annotation-card public-annotation-card">
              <div class="annotation-card-top">
                <strong>{{ comment.author_name }}</strong>
                <time>{{ new Date(comment.created_at).toLocaleDateString("zh-CN") }}</time>
              </div>
              <button class="annotation-quote" :class="{ 'is-clamped': comment.quote.length > 90 && !expandedQuotes.has(comment.id) }" type="button" :title="'跳到原文：' + comment.quote" @click="jumpToPublicComment(comment)">{{ comment.quote }}</button>
              <button v-if="comment.quote.length > 90" class="annotation-expand" type="button" :aria-expanded="expandedQuotes.has(comment.id)" @click="toggleQuote(comment.id)">{{ expandedQuotes.has(comment.id) ? '收起摘录' : '展开摘录' }}</button>
              <p class="public-annotation-content">{{ comment.content }}</p>
              <div v-if="canReport" class="annotation-card-actions">
                <el-button size="small" text @click="$emit('reportComment', comment)">举报评论</el-button>
              </div>
            </article>
          </div>
          <nav v-if="quotePage.loaded && quotePage.total > 20" class="comment-page-controls" aria-label="划线评论翻页">
            <span>第 {{ quotePage.index + 1 }} 批 · 本批 {{ quotePage.items.length }} / 共 {{ quotePage.total }}</span>
            <el-button size="small" :disabled="quotePage.loading || quotePage.index === 0" @click="moveCommentPage('quote', -1)">较新评论</el-button>
            <el-button size="small" :disabled="quotePage.loading || quotePage.nextBeforeId === null" @click="moveCommentPage('quote', 1)">更早评论</el-button>
          </nav>
        </div>
      </aside>
    </div>
  </section>

  <ThemeCreator />
</template>
