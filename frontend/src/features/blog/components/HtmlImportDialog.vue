<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { MdPreview } from "md-editor-v3";
import xss from "xss";
import type { ParsedMarkdown } from "../utils/parseMarkdownFile";
import { matchImageFile } from "../utils/imageFileMatching";
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
  assets: Array<{ kind: string; original: string; status: string; placeholder?: string; alt?: string }>;
  warnings: Array<{ code: string; count: number }>;
  converter_version: string;
}

const props = defineProps<{
  file: File | null;
  visible: boolean;
  applying: boolean;
  /** 剪藏交接来源：外部构造的 HTML File（来自浏览器扩展的一次性交接）。 */
  clipFile?: File | null;
  clipSourceUrl?: string;
  clipTitle?: string;
  clipOwnNote?: string;
  clipOrigin?: "web-clip" | "user-file";
  destination?: "article_draft" | "private_note";
}>();
const emit = defineEmits<{
  close: [];
  apply: [
    data: ParsedMarkdown,
    images: Array<{ reference: string; remote: boolean; alt: string; file: File }>,
    remoteImages: Array<{ reference: string; alt: string }>,
  ];
  applyNote: [
    data: { title: string; content: string; source_url: string },
    images: Array<{ reference: string; alt: string; file: File }>,
    remoteImages: Array<{ reference: string; alt: string }>,
  ];
}>();
const sourceUrl = ref("");
const mode = ref<"article" | "full">("article");
const result = ref<HtmlImportResult | null>(null);
const selectedIds = ref<string[]>([]);
const title = ref("");
const summary = ref("");
const includeSource = ref(false);
const loading = ref(false);
const error = ref("");
const localFiles = ref<File[]>([]);
const skipMissingImages = ref(false);
const skipRemoteImages = ref(false);
let activeRequest = 0;
let controller: AbortController | null = null;

const selectedMarkdown = computed(() => {
  const selected = new Set(selectedIds.value);
  const blocks = result.value?.blocks.filter((block) => selected.has(block.id)) ?? [];
  return blocks.map((block) => block.markdown).join("\n\n").trim();
});
const finalMarkdown = computed(() => {
  if (!selectedMarkdown.value) return "";
  const ownNote = props.destination !== "private_note" ? props.clipOwnNote?.trim() : "";
  const content = ownNote ? `${selectedMarkdown.value}\n\n> 来源说明：${ownNote}` : selectedMarkdown.value;
  const url = result.value?.source_url;
  if (!includeSource.value || !url) return content;
  return `${content}\n\n---\n\n原文：[${new URL(url).hostname}](${url})`;
});
const requiredImages = computed(() => result.value?.assets.filter((asset) =>
  asset.status === "local_file_required" && asset.placeholder && selectedMarkdown.value.includes(asset.placeholder)
) ?? []);
const externalImages = computed(() => result.value?.assets.filter((asset) =>
  asset.status === "external_image" && selectedMarkdown.value.includes(asset.original)
) ?? []);

function matchingFile(original: string): File | null {
  return matchImageFile(original, localFiles.value);
}

const matchedImages = computed(() => requiredImages.value.map((asset) => ({
  asset,
  file: matchingFile(asset.original),
})));
const matchedExternalImages = computed(() => externalImages.value.map((asset) => ({
  asset,
  file: matchingFile(asset.original),
})).filter((item) => item.file));
const remoteImagesToFetch = computed(() => externalImages.value.filter((asset) => !matchingFile(asset.original)));
const missingImages = computed(() => matchedImages.value.filter((item) => !item.file));

function selectLocalFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  const next = [...(input.files ?? [])].filter((file) => /\.(png|jpe?g|gif|webp)$/i.test(file.name));
  input.value = "";
  if (next.length > 100 || next.some((file) => file.size > 5 * 1024 * 1024)) {
    error.value = "最多选择 100 张图片，每张不能超过 5 MiB";
    return;
  }
  localFiles.value = next;
  error.value = "";
}

function replaceMissing(markdown: string): string {
  let content = markdown;
  for (const { asset, file } of matchedImages.value) {
    if (!file && asset.placeholder) {
      content = content.split(asset.placeholder).join(`图片：${asset.alt || "未命名图片"}（未导入）`);
    }
  }
  return content;
}

function withoutLocalImages(markdown: string): string {
  let content = markdown;
  for (const asset of requiredImages.value) {
    if (asset.placeholder) {
      content = content.split(asset.placeholder).join(`图片：${asset.alt || "未命名图片"}（请在编辑器中上传）`);
    }
  }
  return content;
}

function withoutRemoteImages(markdown: string): string {
  if (!skipRemoteImages.value) return markdown;
  let content = markdown;
  for (const asset of remoteImagesToFetch.value) {
    const escaped = asset.original.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    content = content.replace(new RegExp(`!\\[([^\\]]*)\\]\\(${escaped}\\)`, "g"), "图片：$1（未导入）");
  }
  return content;
}

const warningLabels: Record<string, string> = {
  EXTERNAL_IMAGE_DEPENDENCY: "确认导入时会下载外部图片到本站；原站拒绝下载时需选择同名图片文件",
  LOCAL_IMAGE_MISSING: "HTML 引用了本地图片，请选择网页保存时附带的图片文件",
  UNSAFE_IMAGE_SOURCE: "部分图片地址不安全或缺失，已改为文字提示",
  UNSAFE_OR_RELATIVE_LINK: "部分不安全或无法确定地址的链接已改为普通文字",
  UNSUPPORTED_BLOCK: "复杂表格、数学或嵌入内容可能无法等价转换",
  REVIEW_SELECTION: "正文选择不确定，请逐块检查后再应用",
  NO_SEMANTIC_ARTICLE: "未发现明确的正文容器，建议检查是否混入导航"
};

const titleInputTouched = ref(false);

async function loadPreviewWith(targetFile: File, source: string, nextMode = mode.value) {
  const requestId = ++activeRequest;
  controller?.abort();
  controller = new AbortController();
  loading.value = true;
  error.value = "";
  const form = new FormData();
  form.append("file", targetFile);
  form.append("mode", nextMode);
  form.append("source_url", source.trim());
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
    titleInputTouched.value = false;
    title.value = props.clipTitle || result.value.title;
    summary.value = result.value.summary;
    mode.value = nextMode;
  } catch (cause) {
    if (requestId !== activeRequest || (cause instanceof DOMException && cause.name === "AbortError")) return;
    error.value = cause instanceof Error ? cause.message : "HTML 转换失败";
  } finally {
    if (requestId === activeRequest) loading.value = false;
  }
}

/** 手动“重新提取”按钮：用户文件或剪藏 File 都走同一条预览管线。 */
function loadPreview(nextMode = mode.value) {
  const targetFile = props.clipFile ?? props.file;
  if (!targetFile) return;
  void loadPreviewWith(targetFile, sourceUrl.value, nextMode);
}

function handleTitleInput() {
  titleInputTouched.value = true;
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
  if (missingImages.value.length && !skipMissingImages.value) {
    error.value = "还有本地图片未匹配。请选择配套图片，或勾选忽略缺失图片。";
    return;
  }
  const content = withoutRemoteImages(replaceMissing(finalMarkdown.value));
  const selectedRemoteImages = skipRemoteImages.value ? [] : remoteImagesToFetch.value;
  if (props.destination === "private_note") {
    if (content.length > 50_000) {
      error.value = `当前选中内容 ${content.length} 字，私有笔记上限 50,000 字；请减少所选区块或分批剪藏。`;
      return;
    }
    emit("applyNote", {
      title: title.value.trim().slice(0, 180),
      content,
      source_url: result.value?.source_url ?? "",
    }, [
      ...matchedImages.value.flatMap(({ asset, file }) => file && asset.placeholder ? [{
        reference: asset.placeholder, alt: asset.alt || "图片", file,
      }] : []),
      ...matchedExternalImages.value.flatMap(({ asset, file }) => file ? [{
        reference: asset.original, alt: asset.alt || "图片", file,
      }] : []),
    ], selectedRemoteImages.map((asset) => ({ reference: asset.original, alt: asset.alt || "图片" })));
    return;
  }
  emit("apply", {
    title: title.value.trim(),
    summary: summary.value.trim(),
    category: "",
    tags: "",
    content,
  }, [
    ...matchedImages.value.flatMap(({ asset, file }) => file && asset.placeholder ? [{
      reference: asset.placeholder, remote: false, alt: asset.alt || "图片", file,
    }] : []),
    ...matchedExternalImages.value.flatMap(({ asset, file }) => file ? [{
      reference: asset.original, remote: true, alt: asset.alt || "图片", file,
    }] : []),
  ], selectedRemoteImages.map((asset) => ({ reference: asset.original, alt: asset.alt || "图片" })));
}

function download() {
  if (!finalMarkdown.value) return;
  const name = (title.value.trim() || "网页文章").replace(/[\\/:*?"<>|]/g, "-").slice(0, 80);
  const markdown = `# ${title.value.trim() || name}\n\n${withoutRemoteImages(withoutLocalImages(finalMarkdown.value))}\n`;
  const url = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${name}.md`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

watch(
  [() => props.file, () => props.clipFile],
  ([file, clipFile]) => {
    activeRequest++;
    controller?.abort();
    result.value = null;
    selectedIds.value = [];
    sourceUrl.value = clipFile ? props.clipSourceUrl ?? "" : "";
    mode.value = "article";
    includeSource.value = false;
    error.value = "";
    localFiles.value = [];
    skipMissingImages.value = false;
    skipRemoteImages.value = false;
    // 用户手选文件优先；剪藏 File 由扩展交接驱动。
    if (clipFile) void loadPreviewWith(clipFile, props.clipSourceUrl ?? "");
    else if (file) void loadPreviewWith(file, "");
  },
  { immediate: true },
);
watch(
  () => props.clipTitle,
  (clipTitle) => {
    if (clipTitle && !titleInputTouched.value) title.value = clipTitle;
  },
);
watch(() => props.visible, (visible) => {
  if (!visible) {
    activeRequest++;
    controller?.abort();
    loading.value = false;
  }
});
</script>

<template>
  <el-dialog :model-value="visible" :title="destination === 'private_note' ? '从网页剪藏创建私有笔记' : '从 HTML 导入文章'" width="min(960px, 95vw)" append-to-body @close="emit('close')">
    <div class="html-import-dialog">
      <p class="html-import-note">{{ (clipFile ?? file)?.name }} · 原始 HTML 仅发送到当前博客服务端转换；不会自动发布或保存原文件。</p>
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
          <el-input
            v-model="title"
            placeholder="导入后的文章标题"
            aria-label="导入文章标题"
            @input="handleTitleInput"
          />
          <el-input v-model="summary" placeholder="摘要" aria-label="导入文章摘要" />
        </div>
        <p class="html-import-stats">{{ result.stats.text_chars }} 字 · {{ result.stats.headings }} 个标题 · {{ result.stats.tables }} 张表 · {{ result.stats.code_blocks }} 段代码</p>
        <p v-if="destination === 'private_note'" class="html-import-stats">已选正文 {{ finalMarkdown.length }}/50,000 字；仅点击保存后才会写入你的私有笔记。</p>
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
        <div v-if="requiredImages.length || externalImages.length" class="html-import-assets">
          <p v-if="requiredImages.length">本地图片：已匹配 {{ requiredImages.length - missingImages.length }}/{{ requiredImages.length }}。选择网页保存时的配套图片，确认后会上传到本站并插入正文。</p>
          <p v-if="externalImages.length">外部图片 {{ externalImages.length }} 张：确认后将尝试下载 {{ remoteImagesToFetch.length }} 张到{{ destination === 'private_note' ? '私有附件' : '本站' }}；已选择本地替换 {{ matchedExternalImages.length }} 张。下载失败时草稿保持原样，可选择同名图片文件重试。</p>
          <input type="file" multiple accept=".png,.jpg,.jpeg,.gif,.webp" aria-label="选择配套图片文件" @change="selectLocalFiles" />
          <input type="file" multiple webkitdirectory aria-label="选择配套图片文件夹" @change="selectLocalFiles" />
          <p v-if="missingImages.length">待匹配：{{ missingImages.map((item) => item.asset.original).join("、") }}</p>
          <el-checkbox v-model="skipMissingImages">忽略未匹配图片，正文只保留文字提示</el-checkbox>
          <el-checkbox v-if="remoteImagesToFetch.length" v-model="skipRemoteImages">忽略远程图片，正文只保留文字提示</el-checkbox>
        </div>
        <p v-if="externalImages.length" class="html-import-assets">预览仍从原网站加载；确认导入后正文只使用成功保存到本站的图片。请确认图片允许使用。</p>
      </template>
    </div>
    <template #footer>
      <el-button :disabled="applying" @click="emit('close')">取消</el-button>
      <el-button :disabled="!finalMarkdown" @click="download">下载 .md</el-button>
      <el-button type="primary" :disabled="!finalMarkdown || loading || applying" :loading="applying" @click="apply">{{ destination === 'private_note' ? '放入私有笔记编辑器' : '应用到草稿' }}</el-button>
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
