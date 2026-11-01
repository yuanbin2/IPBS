<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { MdPreview } from "md-editor-v3";
import xss from "xss";
import type { BlogArticle, PrivateNote } from "../types";
import VditorEditor from "./VditorEditor.vue";

const props = defineProps<{
  modelValue: boolean;
  sourceArticle: BlogArticle | null;
  selectedQuote: string;
  /** B-043：浏览器扩展通用网页剪藏交接来的未保存笔记草稿。 */
  webClipDraft?: WebClipNoteDraft | null;
}>();
const emit = defineEmits<{
  "update:modelValue": [value: boolean];
  openSource: [slug: string];
  clipDraftApplied: [];
  importScreenshot: [];
}>();

/** 扩展交接的网页剪藏草稿：只在内存中，用户点“保存私有笔记”才落库。 */
export interface WebClipNoteDraft {
  title: string;
  content: string;
  source_url: string;
  source_title: string;
  imageIds?: number[];
}

interface NoteDraft {
  title: string;
  content: string;
  quote: string;
  source_article: number | null;
  source_url: string;
  source_title: string;
}

const notes = ref<PrivateNote[]>([]);
const selected = ref<PrivateNote | null>(null);
const reading = ref(false);
const draft = ref<NoteDraft>({
  title: "",
  content: "",
  quote: "",
  source_article: null,
  source_url: "",
  source_title: "",
});
const clipPending = ref(false);
const baseline = ref(JSON.stringify(draft.value));
const loading = ref(false);
const saving = ref(false);
const query = ref("");
const deleted = ref(false);
const page = ref(1);
const pages = ref(0);
const total = ref(0);
const error = ref("");
const imageWarning = ref("");
const summaryIds = ref<number[]>([]);
const summaryInstruction = ref("");
const summaryLoading = ref(false);
const summarySaving = ref(false);
const summaryError = ref("");
const summaryMarkdown = ref("");
const summaryEditorRef = ref<InstanceType<typeof VditorEditor> | null>(null);
const noteEditorRef = ref<InstanceType<typeof VditorEditor> | null>(null);
const pendingImageIds = ref<number[]>([]);
const privateImageBlobs = new Map<string, string>();
const summaryResult = ref<{
  model: string;
  api_key_source: "dedicated" | "shared";
  generated_at: string;
  truncated: boolean;
  sources: Array<{ note_id: number; title: string; included_chars: number; truncated: boolean }>;
} | null>(null);
let requestSequence = 0;

function canonicalizePrivateImages(markdown: string): string {
  let content = markdown;
  for (const [privateUrl, blobUrl] of privateImageBlobs) content = content.split(blobUrl).join(privateUrl);
  return content;
}

function releasePrivateImages() {
  for (const url of privateImageBlobs.values()) URL.revokeObjectURL(url);
  privateImageBlobs.clear();
  imageWarning.value = "";
}

async function displayPrivateImages(markdown: string): Promise<string> {
  releasePrivateImages();
  let display = markdown;
  const urls = [...new Set(markdown.match(/\/api\/agent\/blog\/notes\/images\/\d+\//g) ?? [])];
  let failed = 0;
  for (const url of urls) {
    try {
      const response = await fetch(url);
      if (!response.ok) {
        failed += 1;
        continue;
      }
      const blob = URL.createObjectURL(await response.blob());
      privateImageBlobs.set(url, blob);
      display = display.split(url).join(blob);
    } catch {
      failed += 1;
    }
  }
  if (failed) imageWarning.value = `${failed} 张私有图片暂时无法读取；文字仍可编辑，请检查登录状态或稍后重试。`;
  return display;
}

function canonicalDraft(): NoteDraft {
  return { ...draft.value, content: canonicalizePrivateImages(draft.value.content) };
}

const dirty = computed(() => JSON.stringify(canonicalDraft()) !== baseline.value);
const hasPendingDraft = computed(() => dirty.value || clipPending.value);
const rendererClass = /^(?:md-editor-[a-z0-9_-]+|hljs(?:-[a-z0-9_-]+)?|language-[a-z0-9_-]+|katex(?:-[a-z0-9_-]+)?)$/i;
const sanitizeNoteHtml = (html: string) => xss(html, {
  stripIgnoreTag: true,
  stripIgnoreTagBody: ["script", "style"],
  onTagAttr: (tag, name, value) => {
    if (tag === "img" && name === "src" && [...privateImageBlobs.values()].includes(value)) {
      return `src="${value}"`;
    }
    if (name !== "class") return undefined;
    const classes = value.split(/\s+/).filter((token) => rendererClass.test(token)).slice(0, 24);
    return classes.length ? `class="${classes.join(" ")}"` : "";
  },
});

function syncNoteContent() {
  if (!noteEditorRef.value?.isReady()) return;
  const content = noteEditorRef.value.getValue();
  draft.value.content = content.trim() ? content : "";
}

function noteSnippet(note: PrivateNote): string {
  const text = (note.content || note.quote)
    .replace(/!\[[^\]]*\]\([^)]+\)/g, "[图片]")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[#>*_~|\x60]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > 90 ? text.slice(0, 90) + "…" : text;
}

function freshDraft(article: BlogArticle | null, quote: string): NoteDraft {
  return {
    title: article ? `《${article.title}》阅读笔记` : "",
    content: "",
    quote,
    source_article: article?.id ?? null,
    source_url: "",
    source_title: "",
  };
}

function startNew(article: BlogArticle | null = null, quote = "", opening = false) {
  // 有剪藏草稿待处理时不重置：避免刚带入的内容被清空。
  if (clipPending.value && opening) return;
  syncNoteContent();
  if (hasPendingDraft.value && !window.confirm("这条笔记还没有保存，确定重新开始吗？")) return;
  clipPending.value = false;
  selected.value = null;
  reading.value = false;
  releasePrivateImages();
  pendingImageIds.value = [];
  draft.value = freshDraft(article, quote);
  baseline.value = JSON.stringify(draft.value);
  error.value = "";
}

async function requestNote(url: string, options: RequestInit = {}) {
  const response = await fetch(url, options);
  if (response.status === 204) return null;
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail ?? `请求失败 (${response.status})`);
  return payload;
}

async function loadNotes() {
  const sequence = ++requestSequence;
  loading.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: "20" });
    if (query.value.trim()) params.set("q", query.value.trim());
    if (deleted.value) params.set("deleted", "1");
    const result = await requestNote(`/api/agent/blog/notes/?${params.toString()}`);
    if (sequence !== requestSequence) return;
    notes.value = result.items;
    pages.value = result.pages;
    total.value = result.total;
  } catch (cause) {
    if (sequence === requestSequence) error.value = cause instanceof Error ? cause.message : "笔记加载失败";
  } finally {
    if (sequence === requestSequence) loading.value = false;
  }
}

function searchNotes() {
  page.value = 1;
  void loadNotes();
}

async function openNote(note: PrivateNote) {
  syncNoteContent();
  if (hasPendingDraft.value && !window.confirm("这条笔记还没有保存，确定切换吗？")) return;
  try {
    const full: PrivateNote = await requestNote(`/api/agent/blog/notes/${note.id}/`);
    const displayContent = await displayPrivateImages(full.content);
    selected.value = full;
    reading.value = true;
    draft.value = {
      title: full.title,
      content: displayContent,
      quote: full.quote,
      source_article: full.source_article,
      source_url: full.source_url ?? "",
      source_title: full.source_title ?? "",
    };
    baseline.value = JSON.stringify(canonicalDraft());
    clipPending.value = false;
    pendingImageIds.value = [];
    error.value = "";
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "笔记读取失败";
  }
}

async function saveNote() {
  syncNoteContent();
  if (!draft.value.title.trim()) {
    error.value = "请填写笔记标题";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const isUpdate = selected.value !== null;
    const result: PrivateNote = await requestNote(
      isUpdate ? `/api/agent/blog/notes/${selected.value!.id}/` : "/api/agent/blog/notes/",
      {
        method: isUpdate ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...canonicalDraft(), ...(isUpdate ? { version: selected.value!.version } : {}) })
      }
    );
    selected.value = result;
    reading.value = true;
    draft.value.content = await displayPrivateImages(result.content);
    baseline.value = JSON.stringify(canonicalDraft());
    if (pendingImageIds.value.length) {
      await requestNote(`/api/agent/blog/notes/${result.id}/images/bind/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_ids: pendingImageIds.value }),
      });
      pendingImageIds.value = [];
    }
    deleted.value = false;
    clipPending.value = false;
    page.value = 1;
    await loadNotes();
    ElMessage.success("笔记已私密保存");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

async function deleteNote(note: PrivateNote) {
  try {
    await ElMessageBox.confirm("删除后可在回收站恢复。", "删除笔记", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消"
    });
  } catch {
    return;
  }
  try {
    await requestNote(`/api/agent/blog/notes/${note.id}/`, { method: "DELETE" });
    summaryIds.value = summaryIds.value.filter((id) => id !== note.id);
    if (selected.value?.id === note.id) {
      selected.value = null;
      reading.value = false;
      draft.value = freshDraft(null, "");
      baseline.value = JSON.stringify(draft.value);
    }
    await loadNotes();
    ElMessage.success("已移入回收站");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "删除失败";
  }
}

function toggleSummaryNote(noteId: number, checked: boolean) {
  if (!checked) {
    summaryIds.value = summaryIds.value.filter((id) => id !== noteId);
    return;
  }
  if (summaryIds.value.length >= 10) {
    summaryError.value = "一次最多选择 10 条笔记";
    return;
  }
  if (!summaryIds.value.includes(noteId)) summaryIds.value = [...summaryIds.value, noteId];
  summaryError.value = "";
}

async function generateSummary() {
  if (!summaryIds.value.length) {
    summaryError.value = "请先选择至少一条笔记";
    return;
  }
  summaryLoading.value = true;
  summaryError.value = "";
  try {
    const result = await requestNote("/api/agent/blog/writing-agent/generate/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: "note_summary",
        note_ids: summaryIds.value,
        instruction: summaryInstruction.value.trim()
      })
    });
    summaryResult.value = result;
    summaryMarkdown.value = result.markdown;
  } catch (cause) {
    summaryError.value = cause instanceof Error ? cause.message : "汇总失败，请检查模型配置后重试";
  } finally {
    summaryLoading.value = false;
  }
}

function currentSummary(): string {
  return summaryEditorRef.value?.getValue() ?? summaryMarkdown.value;
}

async function saveSummaryAsNote() {
  const content = currentSummary().trim();
  if (!content) {
    summaryError.value = "汇总内容为空";
    return;
  }
  summarySaving.value = true;
  summaryError.value = "";
  try {
    await requestNote("/api/agent/blog/notes/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: `笔记汇总 ${new Date().toLocaleDateString("zh-CN")}`, content })
    });
    query.value = "";
    deleted.value = false;
    page.value = 1;
    await loadNotes();
    ElMessage.success("汇总已保存为私有笔记，可继续修改");
  } catch (cause) {
    summaryError.value = cause instanceof Error ? cause.message : "汇总保存失败";
  } finally {
    summarySaving.value = false;
  }
}

async function copySummary() {
  try {
    await navigator.clipboard.writeText(currentSummary());
    ElMessage.success("已复制，可粘贴到文章编辑器");
  } catch {
    summaryError.value = "复制失败，请检查浏览器剪贴板权限";
  }
}

async function restoreNote(note: PrivateNote) {
  try {
    await requestNote(`/api/agent/blog/notes/${note.id}/restore/`, { method: "POST" });
    await loadNotes();
    ElMessage.success("笔记已恢复");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "恢复失败";
  }
}

function beforeClose(done: () => void) {
  syncNoteContent();
  if (!hasPendingDraft.value || window.confirm("这条笔记还没有保存，确定关闭吗？")) {
    baseline.value = JSON.stringify(canonicalDraft());
    clipPending.value = false;
    done();
  }
}

function hasUnsavedChanges(): boolean {
  if (!props.modelValue) return false;
  syncNoteContent();
  return hasPendingDraft.value;
}

function confirmPageLeave(): boolean {
  return !hasUnsavedChanges() || window.confirm("这条笔记还没有保存，确定离开此页吗？");
}

defineExpose({ hasUnsavedChanges, confirmPageLeave });

function openSource(slug: string) {
  if (hasPendingDraft.value && !window.confirm("这条笔记还没有保存，确定查看原文吗？")) return;
  emit("openSource", slug);
}

watch(() => props.modelValue, async (open) => {
  if (!open) return;
  await nextTick();
  startNew(props.sourceArticle, props.selectedQuote, true);
  query.value = "";
  deleted.value = false;
  page.value = 1;
  summaryIds.value = [];
  summaryResult.value = null;
  summaryMarkdown.value = "";
  summaryError.value = "";
  void loadNotes();
});

/**
 * B-043：接收浏览器扩展的网页剪藏草稿。只在内存中形成未保存笔记；
 * 抽屉里已有未保存内容时先确认，绝不静默覆盖。
 */
watch(
  () => props.webClipDraft,
  async (clip) => {
    if (!clip) return;
    if (hasPendingDraft.value) {
      try {
        await ElMessageBox.confirm(
          "当前笔记还有未保存的修改，接收网页剪藏会替换它。是否继续？",
          "接收网页剪藏",
          { type: "warning", confirmButtonText: "继续接收", cancelButtonText: "取消" }
        );
      } catch {
        emit("clipDraftApplied");
        return;
      }
    }
    draft.value = {
      title: clip.title,
      content: await displayPrivateImages(clip.content),
      quote: "",
      source_article: null,
      source_url: clip.source_url,
      source_title: clip.source_title,
    };
    selected.value = null;
    reading.value = false;
    baseline.value = JSON.stringify(canonicalDraft());
    pendingImageIds.value = [...(clip.imageIds ?? [])];
    clipPending.value = true;
    error.value = "";
    await nextTick();
    // 等编辑器就绪后再写入：刚挂载时 Vditor 还没初始化完成。
    const applyContent = () => {
      if (noteEditorRef.value?.isReady()) {
        noteEditorRef.value.getInstance()?.setValue(draft.value.content);
        return true;
      }
      return false;
    };
    if (!applyContent()) {
      const timer = window.setInterval(() => {
        if (applyContent()) window.clearInterval(timer);
      }, 120);
      window.setTimeout(() => window.clearInterval(timer), 5000);
    }
    emit("clipDraftApplied");
    ElMessage.success("已带入网页剪藏：请核对后点击“保存私有笔记”。");
  },
);

function dismissClipPending() {
  clipPending.value = false;
}

onBeforeUnmount(releasePrivateImages);
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :before-close="beforeClose"
    title="我的私有笔记"
    direction="rtl"
    size="min(1120px, 100vw)"
    append-to-body
    class="private-notes-drawer"
  >
    <div class="private-notes-layout">
      <el-alert
        v-if="clipPending"
        class="private-notes-clip-alert"
        type="info"
        :closable="false"
        title="来自网页剪藏的未保存笔记"
      >
        <template #default>
          <p>内容来自浏览器扩展交接的当前网页，只在内存中，尚未保存。</p>
          <p v-if="draft.source_title || draft.source_url">
            来源：{{ draft.source_title || draft.source_url }}
            <a v-if="draft.source_url" :href="draft.source_url" target="_blank" rel="noopener noreferrer nofollow">打开原文</a>
          </p>
          <p>请逐段核对是你本人有权保存的内容，再点击“保存私有笔记”。</p>
        </template>
      </el-alert>
      <div class="private-notes-intro">
        <span class="private-notes-eyebrow">PRIVATE LIBRARY</span>
        <h2>把想法留给自己</h2>
        <p>仅自己可见，不会公开或进入文章知识库。保存后刷新也能找回。</p>
      </div>
      <div class="private-notes-workspace">
      <aside class="private-notes-sidebar" aria-label="笔记列表">
      <div class="private-notes-toolbar">
        <el-input v-model="query" clearable aria-label="搜索私有笔记" placeholder="搜索标题或内容" @keyup.enter="searchNotes" @clear="searchNotes" />
        <el-button @click="searchNotes">查找</el-button>
      </div>
      <div class="private-notes-toolbar private-notes-create">
        <el-button type="primary" @click="startNew()">新建笔记</el-button>
        <el-button @click="emit('importScreenshot')">导入截图</el-button>
      </div>
      <el-checkbox v-model="deleted" @change="searchNotes">查看回收站</el-checkbox>
      <p v-if="error" class="private-notes-error" role="alert">{{ error }}</p>
      <p v-if="imageWarning" class="private-notes-error" role="alert">{{ imageWarning }}</p>
      <div v-if="loading" class="private-notes-hint">正在读取笔记…</div>
      <div v-else class="private-notes-list">
        <p v-if="!notes.length" class="private-notes-hint">{{ deleted ? "回收站为空" : "暂无笔记，可以从文章阅读页随时记录。" }}</p>
        <article v-for="note in notes" :key="note.id" class="private-note-row" :class="{ 'is-selected': selected?.id === note.id && !deleted }">
          <el-checkbox
            v-if="!deleted"
            :model-value="summaryIds.includes(note.id)"
            :aria-label="`选择笔记 ${note.title}`"
            @change="toggleSummaryNote(note.id, Boolean($event))"
          />
          <button type="button" :aria-pressed="selected?.id === note.id && !deleted" @click="deleted ? undefined : openNote(note)">
            <strong>{{ note.title }}</strong>
            <span v-if="noteSnippet(note)" class="private-note-snippet">{{ noteSnippet(note) }}</span>
            <small>{{ new Date(note.updated_at).toLocaleString('zh-CN') }}</small>
          </button>
          <el-button v-if="deleted" size="small" @click="restoreNote(note)">恢复</el-button>
          <el-button v-else size="small" text type="danger" @click="deleteNote(note)">删除</el-button>
        </article>
      </div>
      <div v-if="pages > 1" class="private-notes-pager">
        <el-button :disabled="page <= 1" @click="page--; loadNotes()">上一页</el-button>
        <span>{{ page }} / {{ pages }} · {{ total }} 条</span>
        <el-button :disabled="page >= pages" @click="page++; loadNotes()">下一页</el-button>
      </div>
      </aside>
      <main class="private-notes-main">
      <section v-if="deleted" class="private-notes-empty" aria-label="回收站提示">
        <h3>回收站</h3>
        <p>在左侧选择要恢复的笔记。恢复后可继续阅读和编辑。</p>
      </section>
      <section v-else-if="reading && selected" class="private-notes-reading" aria-label="阅读私有笔记">
        <div class="private-notes-reading-top">
          <span class="private-notes-eyebrow">仅自己可见 · 阅读模式</span>
          <el-button type="primary" @click="reading = false">编辑笔记</el-button>
        </div>
        <h1>{{ selected.title }}</h1>
        <p class="private-notes-reading-meta">更新于 {{ new Date(selected.updated_at).toLocaleString('zh-CN') }}</p>
        <div v-if="selected.source_article_slug || selected.source_url" class="private-notes-reading-source">
          <span>来源 · {{ selected.source_title || (selected.source_article_slug ? '站内文章' : selected.source_url) }}</span>
          <el-button v-if="selected.source_article_slug" text @click="openSource(selected.source_article_slug)">查看原文</el-button>
          <a v-else-if="selected.source_url" :href="selected.source_url" target="_blank" rel="noopener noreferrer nofollow">打开原文</a>
        </div>
        <blockquote v-if="selected.quote" class="private-notes-reading-quote">{{ selected.quote }}</blockquote>
        <MdPreview
          v-if="draft.content.trim()"
          :model-value="draft.content"
          :sanitize="sanitizeNoteHtml"
          language="zh-CN"
          preview-theme="github"
          code-theme="github"
          class="private-notes-markdown"
        />
        <p v-else class="private-notes-hint">这条笔记还没有正文。</p>
      </section>
      <section v-else class="private-notes-editor" aria-label="编辑私有笔记">
        <h3>{{ selected ? "编辑笔记" : "新笔记" }}</h3>
        <el-input v-model="draft.title" aria-label="笔记标题" maxlength="180" show-word-limit placeholder="笔记标题" />
        <div v-if="draft.source_article" class="private-notes-source">
          <span>关联当前文章</span>
          <el-button v-if="selected?.source_article_slug" text @click="openSource(selected.source_article_slug)">查看原文</el-button>
        </div>
        <div v-if="draft.quote" class="private-note-quote">
          <strong>文章摘录</strong>
          <el-input v-model="draft.quote" type="textarea" :rows="2" maxlength="2000" aria-label="摘录" placeholder="文章摘录" />
        </div>
        <div class="private-note-body-label">笔记正文 · 所见即所得</div>
        <VditorEditor
          ref="noteEditorRef"
          v-model="draft.content"
          cache-id="private-note-visual-editor"
          visual-only
          :height="420"
        />
        <div class="private-notes-actions">
          <span class="private-notes-hint">{{ hasPendingDraft ? "尚未保存" : selected ? "已保存" : "填写后保存" }}</span>
          <el-button v-if="clipPending" type="primary" :loading="saving" @click="saveNote">保存私有笔记</el-button>
          <el-button v-else type="primary" :loading="saving" @click="saveNote">保存笔记</el-button>
        </div>
      </section>
      <details v-if="!deleted" class="private-notes-summary" aria-label="AI 汇总私有笔记" :open="summaryIds.length > 0 || Boolean(summaryResult)">
        <summary>AI 汇总笔记 <span>已选 {{ summaryIds.length }} 条</span></summary>
        <p class="private-notes-hint">仅在点击汇总时，将所选笔记发送给现有写作模型；生成内容需你核对，不会自动发布。</p>
        <el-input v-model="summaryInstruction" aria-label="汇总要求" type="textarea" :rows="2" maxlength="2000" placeholder="可选：例如按问题、实践和待验证结论整理" />
        <el-button type="primary" :disabled="!summaryIds.length" :loading="summaryLoading" @click="generateSummary">汇总已选笔记</el-button>
        <p v-if="summaryError" class="private-notes-error" role="alert">{{ summaryError }}</p>
        <template v-if="summaryResult">
          <p class="private-notes-hint">{{ summaryResult.model }} · {{ new Date(summaryResult.generated_at).toLocaleString('zh-CN') }} · 来源：{{ summaryResult.sources.map((source) => `#${source.note_id} ${source.title}`).join('、') }}</p>
          <p v-if="summaryResult.truncated" class="private-notes-error">部分笔记超出输入上限，已截取。请对照原笔记核查遗漏。</p>
          <VditorEditor
            ref="summaryEditorRef"
            :key="summaryResult.generated_at"
            v-model="summaryMarkdown"
            cache-id="private-note-summary"
            visual-only
            :height="300"
          />
          <div class="private-notes-actions">
            <el-button @click="copySummary">复制到文章</el-button>
            <el-button type="primary" :loading="summarySaving" @click="saveSummaryAsNote">存为私有笔记</el-button>
          </div>
        </template>
      </details>
      </main>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.private-notes-layout { display: flex; flex-direction: column; height: 100%; min-height: 0; background: #f8f8f5; color: #22302b; }
.private-notes-intro { padding: 22px 30px 20px; border-bottom: 1px solid #e4e8e2; background: linear-gradient(110deg, #f1f6ef, #fcfcf9 72%); }
.private-notes-eyebrow { color: #477863; font-size: 11px; font-weight: 700; letter-spacing: .13em; text-transform: uppercase; }
.private-notes-intro h2 { margin: 5px 0 3px; font-size: 25px; line-height: 1.3; letter-spacing: -.02em; }
.private-notes-intro p { margin: 0; color: #64716a; font-size: 13px; }
.private-notes-workspace { display: grid; grid-template-columns: minmax(260px, 310px) minmax(0, 1fr); flex: 1; min-height: 0; }
.private-notes-sidebar { display: flex; flex-direction: column; gap: 12px; min-width: 0; min-height: 0; padding: 20px 16px; border-right: 1px solid #e4e8e2; background: #fff; }
.private-notes-toolbar, .private-notes-pager, .private-notes-actions { display: flex; align-items: center; gap: 8px; }
.private-notes-toolbar .el-input { min-width: 0; }
.private-notes-create .el-button { flex: 1; margin: 0; }
.private-notes-list { flex: 1; min-height: 100px; overflow-y: auto; }
.private-note-row { display: flex; align-items: flex-start; gap: 6px; margin-bottom: 7px; padding: 11px 8px; border: 1px solid transparent; border-radius: 11px; background: #f7f8f5; }
.private-note-row.is-selected { border-color: #accdb9; background: #edf5ef; }
.private-note-row button:first-of-type { min-width: 0; flex: 1; display: grid; gap: 5px; padding: 0; text-align: left; border: 0; background: transparent; color: inherit; cursor: pointer; }
.private-note-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.private-note-row small { color: #829087; font-size: 11px; }
.private-note-snippet { color: #68766e; font-size: 12px; line-height: 1.5; overflow: hidden; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.private-notes-pager { justify-content: center; font-size: 12px; }
.private-notes-main { min-width: 0; overflow-y: auto; padding: 30px clamp(20px, 5vw, 68px) 50px; }
.private-notes-editor, .private-notes-reading { max-width: 750px; margin: 0 auto; }
.private-notes-editor { display: grid; gap: 15px; }
.private-notes-editor h3 { margin: 0 0 2px; font-size: 23px; }
.private-notes-reading-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.private-notes-reading h1 { margin: 26px 0 8px; font-size: clamp(28px, 3vw, 38px); line-height: 1.35; overflow-wrap: anywhere; }
.private-notes-reading-meta { margin: 0 0 26px; color: #77857b; font-size: 13px; }
.private-notes-reading-source { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 25px; padding: 11px 14px; border-radius: 10px; background: #edf4ee; color: #466a54; font-size: 13px; overflow-wrap: anywhere; }
.private-notes-reading-source a { color: #286c4e; white-space: nowrap; }
.private-notes-reading-quote { margin: 0 0 25px; padding: 12px 18px; border-left: 3px solid #bc9c52; border-radius: 0 8px 8px 0; background: #faf5e8; color: #63563e; white-space: pre-wrap; }
.private-notes-markdown { font-size: 15px; line-height: 1.8; overflow-wrap: anywhere; }
.private-notes-markdown :deep(.md-editor-preview-wrapper) { padding: 0; }
.private-notes-hint { color: #758178; font-size: 13px; margin: 0; }
.private-note-quote { display: grid; gap: 7px; padding: 12px; border-left: 3px solid #bc9c52; border-radius: 6px; background: #faf5e8; }
.private-note-quote strong, .private-note-body-label { font-size: 13px; font-weight: 700; }
.private-notes-source { display: flex; align-items: center; justify-content: space-between; color: #68766e; font-size: 13px; }
.private-notes-actions { justify-content: space-between; }
.private-notes-summary { display: grid; gap: 12px; max-width: 750px; margin: 38px auto 0; padding: 17px 0; border-top: 1px solid #dfe7df; }
.private-notes-summary summary { cursor: pointer; font-weight: 700; }
.private-notes-summary summary span { margin-left: 8px; color: #77857b; font-size: 12px; font-weight: 400; }
.private-notes-summary[open] { display: grid; }
.private-notes-empty { max-width: 650px; margin: 60px auto; text-align: center; color: #68766e; }
.private-notes-error { color: var(--el-color-danger); margin: 0; }
.private-notes-clip-alert { margin: 14px 20px 0; }
.private-notes-clip-alert p { margin: 4px 0 0; font-size: 13px; }
.private-notes-clip-alert a { color: #1f6f54; }
@media (max-width: 720px) {
  .private-notes-intro { padding: 16px 18px; }
  .private-notes-intro h2 { font-size: 20px; }
  .private-notes-workspace { display: block; overflow-y: auto; }
  .private-notes-sidebar { height: auto; max-height: 38vh; padding: 12px; border-right: 0; border-bottom: 1px solid #e4e8e2; }
  .private-notes-list { min-height: 70px; }
  .private-notes-main { overflow: visible; padding: 22px 16px 40px; }
}
</style>

<style>
.private-notes-drawer .el-drawer__header { margin: 0; padding: 14px 24px; border-bottom: 1px solid #e4e8e2; }
.private-notes-drawer .el-drawer__body { padding: 0; overflow: hidden; }
</style>
