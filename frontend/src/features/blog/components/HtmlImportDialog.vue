<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { MdPreview } from "md-editor-v3";
import xss from "xss";
import type { ParsedMarkdown } from "../utils/parseMarkdownFile";

interface ImportBlock {
  id: string;
  heading: string;
  excerpt: string;
  markdown: string;
  recommended: boolean;
  reason: string;
}

interface HtmlImportResult {
  title: string;
  summary: string;
  content_markdown: string;
  source_url: string;
  mode: "article" | "full";
  stats: { text_chars: number; headings: number; tables: number; code_blocks: number };
  blocks: ImportBlock[];
  assets: Array<{ kind: string; original: string; status: string }>;
  warnings: Array<{ code: string; count: number }>;
  converter_version: string;
}

const props = defineProps<{ file: File | null; visible: boolean }>();
const emit = defineEmits<{ close: []; apply: [data: ParsedMarkdown] }>();
const sourceUrl = ref("");
const mode = ref<"article" | "full">("article");
const result = ref<HtmlImportResult | null>(null);
const selectedIds = ref<string[]>([]);
const title = ref("");
const summary = ref("");
const includeSource = ref(false);
const loading = ref(false);
const error = ref("");
let activeRequest = 0;
let controller: AbortController | null = null;

const selectedMarkdown = computed(() => {
  const selected = new Set(selectedIds.value);
  const blocks = result.value?.blocks.filter((block) => selected.has(block.id)) ?? [];
  return blocks.map((block) => block.markdown).join("\n\n").trim();
});
const finalMarkdown = computed(() => {
  if (!selectedMarkdown.value) return "";
  const url = result.value?.source_url;
  if (!includeSource.value || !url) return selectedMarkdown.value;
  return `${selectedMarkdown.value}\n\n---\n\n原文：[${new URL(url).hostname}](${url})`;
});

const warningLabels: Record<string, string> = {
  EXTERNAL_IMAGE_LINK: "外部图片只保留为链接，请检查版权和长期可用性",
  LOCAL_IMAGE_MISSING: "本地图片未包含在 HTML 中，请在编辑器中手动上传",
  UNSAFE_OR_RELATIVE_LINK: "部分不安全或无法确定地址的链接已改为普通文字",
  UNSUPPORTED_BLOCK: "复杂表格、数学或嵌入内容可能无法等价转换",
  REVIEW_SELECTION: "正文选择不确定，请逐块检查后再应用",
  NO_SEMANTIC_ARTICLE: "未发现明确的正文容器，建议检查是否混入导航"
};

async function loadPreview(nextMode = mode.value) {
  if (!props.file) return;
  const requestId = ++activeRequest;
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = "";
  const form = new FormData();
  form.append("file", props.file);
  form.append("mode", nextMode);
  form.append("source_url", sourceUrl.value.trim());
  try {
    const response = await fetch("/api/agent/blog/imports/html/preview/", {
      method: "POST",
      body: form,
      signal: controller.signal,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `导入失败 (${response.status})`);
    if (requestId !== activeRequest) return;
    result.value = payload as HtmlImportResult;
    selectedIds.value = result.value.blocks.filter((block) => block.recommended).map((block) => block.id);
    title.value = result.value.title;
    summary.value = result.value.summary;
    mode.value = nextMode;
  } catch (cause) {
    if (requestId !== activeRequest || (cause instanceof DOMException && cause.name === "AbortError")) return;
    error.value = cause instanceof Error ? cause.message : "HTML 转换失败";
  } finally {
    if (requestId === activeRequest) loading.value = false;
  }
}

function toggleBlock(id: string, checked: unknown) {
  const next = new Set(selectedIds.value);
  if (Boolean(checked)) next.add(id);
  else next.delete(id);
  selectedIds.value = [...next];
}

function apply() {
  if (!title.value.trim() || !finalMarkdown.value) {
    error.value = "请填写标题并至少选择一个有内容的区块";
    return;
  }
  emit("apply", {
    title: title.value.trim(),
    summary: summary.value.trim(),
    category: "",
    tags: "",
    content: finalMarkdown.value,
  });
}

function download() {
  if (!finalMarkdown.value) return;
  const name = (title.value.trim() || "网页文章").replace(/[\\/:*?"<>|]/g, "-").slice(0, 80);
  const markdown = `# ${title.value.trim() || name}\n\n${finalMarkdown.value}\n`;
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${name}.md`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

watch(() => props.file, (file) => {
  activeRequest++;
  controller?.abort();
  result.value = null;
  selectedIds.value = [];
  sourceUrl.value = "";
  mode.value = "article";
  includeSource.value = false;
  error.value = "";
  if (file) void loadPreview();
});
watch(() => props.visible, (visible) => {
  if (!visible) {
    activeRequest++;
    controller?.abort();
    loading.value = false;
  }
});
</script>

<template>
  <el-dialog :model-value="visible" title="从 HTML 导入文章" width="min(960px, 95vw)" append-to-body @close="emit('close')">
    <div class="html-import-dialog">
      <p class="html-import-note">{{ file?.name }} · 原始 HTML 仅发送到当前博客服务端转换；不会自动发布或保存原文件。</p>
      <div class="html-import-controls">
        <el-input v-model="sourceUrl" placeholder="原网页地址（可选，只用于补全相对链接，不会抓取网页）" clearable />
        <el-button :loading="loading" @click="loadPreview()">重新提取</el-button>
      </div>
      <div class="html-import-controls">
        <span>内容范围</span>
        <el-radio-group :model-value="mode" @change="loadPreview($event as 'article' | 'full')">
          <el-radio-button value="article">建议正文</el-radio-button>
          <el-radio-button value="full">整页内容</el-radio-button>
        </el-radio-group>
      </div>
      <p v-if="loading" role="status">正在提取网页正文…</p>
      <el-alert v-if="error" type="error" :title="error" :closable="false" />
      <template v-if="result">
        <div class="html-import-fields">
          <el-input v-model="title" placeholder="导入后的文章标题" aria-label="导入文章标题" />
          <el-input v-model="summary" placeholder="摘要" aria-label="导入文章摘要" />
        </div>
        <p class="html-import-stats">{{ result.stats.text_chars }} 字 · {{ result.stats.headings }} 个标题 · {{ result.stats.tables }} 张表 · {{ result.stats.code_blocks }} 段代码</p>
        <el-alert
          v-for="warning in result.warnings"
          :key="warning.code"
          class="html-import-warning"
          type="warning"
          :closable="false"
          :title="`${warningLabels[warning.code] || warning.code}（${warning.count}）`"
        />
        <div class="html-import-body">
          <section class="html-import-blocks" aria-label="导入内容区块">
            <h3>选择要导入的内容</h3>
            <div v-for="block in result.blocks" :key="block.id" class="html-import-block">
              <el-checkbox :model-value="selectedIds.includes(block.id)" @change="toggleBlock(block.id, $event)" />
              <span>
                <strong>{{ block.heading || block.excerpt.slice(0, 28) || '未命名区块' }}</strong>
                <small>{{ block.reason }} · {{ block.excerpt.slice(0, 95) }}</small>
              </span>
            </div>
          </section>
          <section class="html-import-preview" aria-label="Markdown 排版预览">
            <h3>导入预览</h3>
            <MdPreview v-if="finalMarkdown" :model-value="finalMarkdown" :sanitize="(html: string) => xss(html)" />
            <p v-else>请在左侧选择要导入的内容。</p>
          </section>
        </div>
        <el-checkbox v-if="result.source_url" v-model="includeSource">在正文末尾附上已确认的原文链接</el-checkbox>
        <p v-if="result.assets.length" class="html-import-assets">图片提示：{{ result.assets.length }} 项未作为本站图片导入，可在编辑文章时手动上传。</p>
      </template>
    </div>
    <template #footer>
      <el-button @click="emit('close')">取消</el-button>
      <el-button :disabled="!finalMarkdown" @click="download">下载 .md</el-button>
      <el-button type="primary" :disabled="!finalMarkdown || loading" @click="apply">应用到草稿</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.html-import-dialog { display: grid; gap: 12px; }
.html-import-note, .html-import-stats, .html-import-assets { margin: 0; color: #63716e; font-size: 13px; }
.html-import-controls { display: flex; align-items: center; gap: 10px; }
.html-import-controls .el-input { flex: 1; }
.html-import-fields { display: grid; gap: 8px; }
.html-import-warning { margin: 0; }
.html-import-body { display: grid; grid-template-columns: minmax(220px, 30%) minmax(0, 1fr); gap: 16px; min-height: 260px; }
.html-import-blocks, .html-import-preview { min-width: 0; max-height: 48vh; overflow: auto; border: 1px solid #dce4e1; border-radius: 10px; padding: 12px; }
.html-import-blocks h3, .html-import-preview h3 { margin: 0 0 10px; font-size: 15px; }
.html-import-block { display: flex; gap: 9px; align-items: flex-start; padding: 9px 0; border-top: 1px solid #edf1f0; cursor: pointer; }
.html-import-block span { min-width: 0; display: grid; gap: 4px; }
.html-import-block small { color: #687674; line-height: 1.45; overflow-wrap: anywhere; }
.html-import-preview :deep(.md-editor-preview) { padding: 0; }
@media (max-width: 720px) { .html-import-body { grid-template-columns: 1fr; } .html-import-blocks, .html-import-preview { max-height: 30vh; } }
</style>
