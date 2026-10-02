<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { BlogArticle, BlogDraft } from "../types";
import {
  getDraftCacheStatus,
  getVditorCacheId,
  getWriterContextStorageKey,
  readWriterDraft,
  removeWriterDraft,
  saveWriterDraft,
  type DraftOwner,
  type WriterContext
} from "../utils/draftStorage";
import VditorEditor from "./VditorEditor.vue";

const props = defineProps<{
  article: BlogArticle;
  owner: DraftOwner;
  uploadHandler: (files: File[]) => Promise<Array<{ url: string; alt?: string; title?: string }>>;
}>();
const emit = defineEmits<{ saved: []; ready: []; "dirty-change": [dirty: boolean] }>();

const context: WriterContext = { kind: "article", id: String(props.article.id), slug: props.article.slug, open: false };
const cacheId = getVditorCacheId(props.owner, context);
const cacheKey = getWriterContextStorageKey(props.owner, context);
const tabId = crypto.randomUUID();
function articleDraft(article: BlogArticle): BlogDraft {
  const revision = article.pending_revision;
  return revision
    ? {
        title: revision.title,
        summary: revision.summary,
        cover_image: revision.cover_image,
        category: revision.category,
        tags: revision.tags.join(", "),
        content: revision.content
      }
    : {
        title: article.title,
        summary: article.summary || "",
        cover_image: article.cover_image || "",
        category: article.category?.name || "",
        tags: article.tags.map((tag) => tag.name).join(", "),
        content: article.content || ""
      };
}

const initialDraft = articleDraft(props.article);
const cached = readWriterDraft(props.owner, context);
const draft = ref<BlogDraft>(cached ? { ...cached.draft } : { ...initialDraft });
const editorRef = ref<InstanceType<typeof VditorEditor>>();
const restored = ref(Boolean(cached));
const saveStatus = ref(cached ? "已恢复这篇文章在本机保存的修改。" : "修改会自动保存在本机，提交后等待管理员审核。");
const error = ref("");
const saving = ref(false);
const conflict = ref(false);
const showHeadingMarkers = ref(false);
const actionsRef = ref<HTMLElement>();
const actionsHeight = ref(52);
const dirty = computed(() => JSON.stringify(draft.value) !== JSON.stringify(initialDraft));
const displayTags = computed(() => draft.value.tags.split(",").map((tag) => tag.trim()).filter(Boolean));
let saveTimer: ReturnType<typeof setTimeout> | undefined;
let contentSyncTimer: ReturnType<typeof setInterval> | undefined;
let actionsObserver: ResizeObserver | undefined;
let caretFrame = 0;
let submitted = false;

function revealCaret() {
  caretFrame = 0;
  const selection = window.getSelection();
  if (!selection?.isCollapsed || !selection.rangeCount) return;
  const anchor = selection.anchorNode?.parentElement;
  const editor = anchor?.closest(".inline-article-editor .vditor-wysiwyg");
  const main = actionsRef.value?.closest<HTMLElement>(".article-main");
  const toolbar = editor?.closest(".vditor")?.querySelector<HTMLElement>(".vditor-toolbar");
  if (!anchor || !editor || !main || !toolbar) return;
  const caret = selection.getRangeAt(0).getClientRects()[0] ?? anchor.getBoundingClientRect();
  const viewport = main.getBoundingClientRect();
  const visibleTop = Math.max(viewport.top, toolbar.getBoundingClientRect().bottom) + 12;
  if (caret.top < visibleTop) main.scrollTop -= visibleTop - caret.top;
  else if (caret.bottom > viewport.bottom - 12) main.scrollTop += caret.bottom - viewport.bottom + 12;
}

function scheduleCaretReveal() {
  if (caretFrame) cancelAnimationFrame(caretFrame);
  caretFrame = requestAnimationFrame(revealCaret);
}

function syncVisualContent() {
  if (!editorRef.value?.isReady()) return;
  const content = editorRef.value.getValue();
  if (content !== draft.value.content) draft.value.content = content;
}

function onEditorReady() {
  if (!cached && editorRef.value) {
    // Vditor canonicalizes Markdown while mounting. Treat that representation
    // as the starting point, rather than a change made by the author.
    const normalizedContent = editorRef.value.getValue();
    initialDraft.content = normalizedContent;
    draft.value.content = normalizedContent;
  }
  emit("ready");
}

function persistDraft() {
  syncVisualContent();
  if (!dirty.value || submitted || conflict.value) return;
  try {
    saveWriterDraft(props.owner, context, draft.value, tabId);
    saveStatus.value = "修改已自动保存在本机；尚未提交审核。";
  } catch (cause) {
    saveStatus.value = getDraftCacheStatus(cause);
  }
}

watch(draft, () => {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(persistDraft, 300);
}, { deep: true });
watch(dirty, (value) => emit("dirty-change", value), { immediate: true });

function handleStorage(event: StorageEvent) {
  if (event.key !== cacheKey || !event.newValue) return;
  try {
    const changed = JSON.parse(event.newValue) as { writerTabId?: string };
    if (changed.writerTabId !== tabId) {
      conflict.value = true;
      saveStatus.value = "另一标签页也在修改这篇文章；请先复制当前内容，再刷新以核对差异。";
    }
  } catch {
    conflict.value = true;
  }
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  syncVisualContent();
  if (!dirty.value || submitted) return;
  persistDraft();
  event.preventDefault();
  event.returnValue = "";
}

onMounted(() => {
  if (actionsRef.value) {
    const actions = actionsRef.value;
    const updateHeight = () => { actionsHeight.value = Math.ceil(actions.getBoundingClientRect().height); };
    updateHeight();
    actionsObserver = new ResizeObserver(updateHeight);
    actionsObserver.observe(actions);
  }
  window.addEventListener("storage", handleStorage);
  window.addEventListener("beforeunload", handleBeforeUnload);
  // Vditor may normalize pasted or IME text after its input callback. Read its
  // Markdown state too, so autosave and submit always use what the user sees.
  contentSyncTimer = setInterval(syncVisualContent, 500);
});
onBeforeUnmount(() => {
  actionsObserver?.disconnect();
  if (caretFrame) cancelAnimationFrame(caretFrame);
  if (saveTimer) clearTimeout(saveTimer);
  if (contentSyncTimer) clearInterval(contentSyncTimer);
  syncVisualContent();
  persistDraft();
  window.removeEventListener("storage", handleStorage);
  window.removeEventListener("beforeunload", handleBeforeUnload);
});

async function submitRevision() {
  if (saving.value || conflict.value) return;
  syncVisualContent();
  if (!draft.value.title.trim() || !draft.value.content.trim()) {
    error.value = "标题和正文不能为空。";
    return;
  }
  persistDraft();
  saving.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/agent/blog/articles/${encodeURIComponent(props.article.slug)}/`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...draft.value,
        publication_version: props.article.publication_version,
        tags: draft.value.tags.split(",").map((tag) => tag.trim()).filter(Boolean)
      })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || `保存失败：HTTP ${response.status}`);
    submitted = true;
    removeWriterDraft(props.owner, context);
    Object.assign(initialDraft, draft.value);
    draft.value = { ...draft.value };
    saveStatus.value = "已提交审核；可继续在正文原处修改。";
    emit("saved");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "保存失败；本机修改仍保留。";
  } finally {
    saving.value = false;
    submitted = false;
  }
}

async function uploadImages(files: File[]) {
  const uploaded = await props.uploadHandler(files);
  if (uploaded.length !== files.length) throw new Error("图片上传失败；正文仍保留，请重试。");
  return uploaded;
}

defineExpose({ hasUnsavedChanges: () => dirty.value && !submitted, persistDraft });
</script>

<template>
  <section class="inline-article-editor" :class="{ 'show-heading-markers': showHeadingMarkers }" :style="{ '--inline-actions-height': `${actionsHeight}px` }" aria-label="可直接编辑的文章">
    <h1 class="article-title inline-editor-title" :aria-label="draft.title">
      <input v-model="draft.title" maxlength="180" aria-label="编辑文章标题" placeholder="文章标题" />
    </h1>
    <textarea v-model="draft.summary" class="article-summary inline-editor-summary" rows="2" aria-label="编辑文章摘要" placeholder="添加文章摘要…" />
    <slot name="byline" />
    <div v-if="displayTags.length" class="tag-row article-tags">
      <span v-for="tag in displayTags" :key="tag"># {{ tag }}</span>
    </div>
    <div v-if="draft.cover_image" class="article-cover">
      <img :src="draft.cover_image" :alt="draft.title" />
    </div>
    <div ref="actionsRef" class="inline-editor-actions">
      <span>{{ article.pending_revision ? "待审核修订 · 单击标题或正文可继续修改" : "单击标题或正文可直接修改 · 自动保存在本机" }}</span>
      <el-button size="small" text :aria-pressed="showHeadingMarkers" @click="showHeadingMarkers = !showHeadingMarkers">{{ showHeadingMarkers ? "隐藏标题层级" : "显示标题层级" }}</el-button>
      <el-button type="primary" :loading="saving" :disabled="conflict" @click="submitRevision">保存并提交审核</el-button>
    </div>
    <p v-if="restored" class="inline-editor-restored">已从本机恢复未提交的修改。</p>
    <details class="inline-editor-metadata">
      <summary>文章信息 · 分类、标签与封面</summary>
      <div class="inline-editor-metadata-fields">
        <div class="inline-editor-fields">
          <label>分类<el-input v-model="draft.category" aria-label="编辑文章分类" /></label>
          <label>标签（用逗号分隔）<el-input v-model="draft.tags" aria-label="编辑文章标签" /></label>
        </div>
        <label>封面图片地址<el-input v-model="draft.cover_image" aria-label="编辑文章封面" /></label>
      </div>
    </details>
    <div class="inline-editor-body" @mouseup="scheduleCaretReveal" @keyup="scheduleCaretReveal">
      <VditorEditor ref="editorRef" v-model="draft.content" :cache-id="cacheId" :upload-handler="uploadImages" visual-only external-outline height="auto" @ready="onEditorReady" @upload-error="error = $event" />
    </div>
    <p role="status" class="inline-editor-status">{{ saveStatus }}</p>
    <p v-if="conflict" role="alert" class="inline-editor-error">另一标签页已有新修改；此页停止提交，避免覆盖。</p>
    <p v-if="error" role="alert" class="inline-editor-error">{{ error }}</p>
  </section>
</template>

<style scoped>
.inline-article-editor { display: grid; gap: 12px; min-width: 0; }
.inline-editor-body { min-width: 0; }
.inline-editor-title { margin-bottom: 0 !important; }
.inline-editor-title input { width: 100%; border: 0; outline: 0; background: transparent; color: inherit; font: inherit; letter-spacing: inherit; }
.inline-editor-title input:focus { box-shadow: inset 0 -2px 0 var(--el-color-primary); }
.inline-editor-summary { width: 100%; min-height: 56px; border: 0; outline: 0; resize: vertical; background: transparent; color: inherit; font: inherit; line-height: inherit; }
.inline-editor-summary:focus { box-shadow: inset 0 -2px 0 var(--el-color-primary); }
.inline-editor-status, .inline-editor-restored { color: var(--el-text-color-secondary); }
.inline-article-editor label { display: grid; gap: 7px; font-weight: 600; }
.inline-editor-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.inline-editor-metadata { border-bottom: 1px solid var(--el-border-color); }
.inline-editor-metadata summary { padding: 8px 2px; cursor: pointer; color: var(--el-text-color-secondary); }
.inline-editor-metadata-fields { display: grid; gap: 12px; padding: 12px 0 18px; }
.inline-editor-actions { position: sticky; top: 0; display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px; padding: 10px 0; background: var(--el-bg-color); z-index: 2; border-bottom: 1px solid var(--el-border-color); }
.inline-editor-actions span { margin-right: auto; color: var(--el-text-color-secondary); font-size: 13px; }
.inline-editor-error { color: var(--el-color-danger); }
@media (max-width: 700px) { .inline-editor-fields { grid-template-columns: 1fr; } }
</style>
