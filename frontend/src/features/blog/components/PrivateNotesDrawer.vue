<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { BlogArticle, PrivateNote } from "../types";
import VditorEditor from "./VditorEditor.vue";

const props = defineProps<{
  modelValue: boolean;
  sourceArticle: BlogArticle | null;
  selectedQuote: string;
}>();
const emit = defineEmits<{
  "update:modelValue": [value: boolean];
  openSource: [slug: string];
}>();

interface NoteDraft {
  title: string;
  content: string;
  quote: string;
  source_article: number | null;
}

const notes = ref<PrivateNote[]>([]);
const selected = ref<PrivateNote | null>(null);
const draft = ref<NoteDraft>({ title: "", content: "", quote: "", source_article: null });
const baseline = ref(JSON.stringify(draft.value));
const loading = ref(false);
const saving = ref(false);
const query = ref("");
const deleted = ref(false);
const page = ref(1);
const pages = ref(0);
const total = ref(0);
const error = ref("");
const summaryIds = ref<number[]>([]);
const summaryInstruction = ref("");
const summaryLoading = ref(false);
const summarySaving = ref(false);
const summaryError = ref("");
const summaryMarkdown = ref("");
const summaryEditorRef = ref<InstanceType<typeof VditorEditor> | null>(null);
const noteEditorRef = ref<InstanceType<typeof VditorEditor> | null>(null);
const summaryResult = ref<{
  model: string;
  api_key_source: "dedicated" | "shared";
  generated_at: string;
  truncated: boolean;
  sources: Array<{ note_id: number; title: string; included_chars: number; truncated: boolean }>;
} | null>(null);
let requestSequence = 0;

const dirty = computed(() => JSON.stringify(draft.value) !== baseline.value);

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
    source_article: article?.id ?? null
  };
}

function startNew(article: BlogArticle | null = null, quote = "") {
  syncNoteContent();
  if (dirty.value && !window.confirm("这条笔记还没有保存，确定重新开始吗？")) return;
  selected.value = null;
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
  if (dirty.value && !window.confirm("这条笔记还没有保存，确定切换吗？")) return;
  try {
    const full: PrivateNote = await requestNote(`/api/agent/blog/notes/${note.id}/`);
    selected.value = full;
    draft.value = {
      title: full.title,
      content: full.content,
      quote: full.quote,
      source_article: full.source_article
    };
    baseline.value = JSON.stringify(draft.value);
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
        body: JSON.stringify({ ...draft.value, ...(isUpdate ? { version: selected.value!.version } : {}) })
      }
    );
    selected.value = result;
    baseline.value = JSON.stringify(draft.value);
    deleted.value = false;
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
  if (!dirty.value || window.confirm("这条笔记还没有保存，确定关闭吗？")) {
    baseline.value = JSON.stringify(draft.value);
    done();
  }
}

function openSource(slug: string) {
  if (dirty.value && !window.confirm("这条笔记还没有保存，确定查看原文吗？")) return;
  emit("openSource", slug);
}

watch(() => props.modelValue, async (open) => {
  if (!open) return;
  await nextTick();
  startNew(props.sourceArticle, props.selectedQuote);
  query.value = "";
  deleted.value = false;
  page.value = 1;
  summaryIds.value = [];
  summaryResult.value = null;
  summaryMarkdown.value = "";
  summaryError.value = "";
  void loadNotes();
});
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :before-close="beforeClose"
    title="我的私有笔记"
    direction="rtl"
    size="min(540px, 100vw)"
    :modal="false"
    append-to-body
    class="private-notes-drawer"
  >
    <div class="private-notes-layout">
      <p class="private-notes-hint">仅自己可见，不会公开或进入文章知识库。保存后刷新也能找回。</p>
      <div class="private-notes-toolbar">
        <el-input v-model="query" clearable aria-label="搜索私有笔记" placeholder="搜索标题或内容" @keyup.enter="searchNotes" @clear="searchNotes" />
        <el-button @click="searchNotes">查找</el-button>
        <el-button @click="startNew()">新建</el-button>
      </div>
      <el-checkbox v-model="deleted" @change="searchNotes">查看回收站</el-checkbox>
      <p v-if="error" class="private-notes-error" role="alert">{{ error }}</p>
      <div v-if="loading" class="private-notes-hint">正在读取笔记…</div>
      <div v-else class="private-notes-list">
        <p v-if="!notes.length" class="private-notes-hint">{{ deleted ? "回收站为空" : "暂无笔记，可以从文章阅读页随时记录。" }}</p>
        <article v-for="note in notes" :key="note.id" class="private-note-row">
          <el-checkbox
            v-if="!deleted"
            :model-value="summaryIds.includes(note.id)"
            :aria-label="`选择笔记 ${note.title}`"
            @change="toggleSummaryNote(note.id, Boolean($event))"
          />
          <button type="button" @click="deleted ? undefined : openNote(note)">
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
      <section v-if="!deleted" class="private-notes-editor" aria-label="编辑私有笔记">
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
          :height="280"
        />
        <div class="private-notes-actions">
          <span class="private-notes-hint">{{ dirty ? "尚未保存" : selected ? "已保存" : "填写后保存" }}</span>
          <el-button type="primary" :loading="saving" @click="saveNote">保存笔记</el-button>
        </div>
      </section>
      <section v-if="!deleted" class="private-notes-summary" aria-label="AI 汇总私有笔记">
        <h3>AI 汇总笔记</h3>
        <p class="private-notes-hint">已选 {{ summaryIds.length }} 条。仅在点击汇总时，将所选笔记发送给现有写作模型；生成内容需你核对，不会自动发布。</p>
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
      </section>
    </div>
  </el-drawer>
</template>

<style scoped>
.private-notes-layout { display: grid; gap: 12px; }
.private-notes-hint { color: var(--el-text-color-secondary); font-size: 13px; margin: 0; }
.private-notes-toolbar, .private-notes-pager, .private-notes-actions { display: flex; align-items: center; gap: 8px; }
.private-notes-toolbar .el-input { min-width: 0; }
.private-notes-list { max-height: 28vh; overflow-y: auto; border-block: 1px solid var(--el-border-color); }
.private-note-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 9px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.private-note-row button:first-child { min-width: 0; flex: 1; display: grid; gap: 2px; text-align: left; border: 0; background: transparent; color: inherit; cursor: pointer; }
.private-note-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.private-note-row small { color: var(--el-text-color-secondary); }
.private-note-snippet { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.4; overflow: hidden; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.private-notes-editor { display: grid; gap: 10px; }
.private-notes-editor h3 { margin: 0; }
.private-note-quote { display: grid; gap: 7px; padding: 10px; border-left: 3px solid #dfa717; border-radius: 6px; background: #fffbed; }
.private-note-quote strong, .private-note-body-label { font-size: 13px; font-weight: 700; color: var(--el-text-color-primary); }
.private-notes-summary { display: grid; gap: 10px; border-top: 1px solid var(--el-border-color); padding-top: 12px; }
.private-notes-summary h3 { margin: 0; }
.private-notes-source { display: flex; align-items: center; justify-content: space-between; color: var(--el-text-color-secondary); font-size: 13px; }
.private-notes-actions { justify-content: space-between; }
.private-notes-error { color: var(--el-color-danger); margin: 0; }
</style>
