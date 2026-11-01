<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { EditPen, UploadFilled, ArrowDown } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { BlogDraft, EditorStats } from "../types";
import type { WritingAssistantRequest, WritingAssistantResult } from "../types";
import { parseMarkdownFile, type ParsedMarkdown } from "../utils/parseMarkdownFile";
import { findMarkdownImages } from "../utils/imageFileMatching";
import MarkdownImportDialog from "./MarkdownImportDialog.vue";
import VditorEditor from "./VditorEditor.vue";
import HtmlImportDialog from "./HtmlImportDialog.vue";
import WritingAssistantPanel from "./WritingAssistantPanel.vue";
import ThemeSwitcher from "./ThemeSwitcher.vue";
import ThemeCreator from "./ThemeCreator.vue";
import { mergeTagNames, normalizeTagList } from "../utils/tagInput";

const props = defineProps<{
  draft: BlogDraft;
  editorCacheId: string;
  draftSaveStatus: string;
  draftConflict: boolean;
  templates: Array<{ name: string; content: string }>;
  categories: Array<{ id: number; name: string }>;
  /** 站点已有标签名，供标签下拉点选复用。 */
  tagOptions: string[];
  stats: EditorStats;
  publishing: boolean;
  uploadingImage: boolean;
  error: string;
  uploadHandler: (files: File[]) => Promise<Array<{ url: string; alt?: string; title?: string }>>;
  editingArticle?: { title: string } | null;
  updating?: boolean;
  authenticated: boolean;
  writingAssistantLoading: boolean;
  writingAssistantError: string;
  writingAssistantResult: WritingAssistantResult | null;
  htmlClipFile?: File | null;
  htmlClipSourceUrl?: string;
  htmlClipTitle?: string;
  htmlClipOwnNote?: string;
}>();

const emit = defineEmits<{
  publish: [addToKnowledgeBase: boolean];
  update: [];
  cancelEdit: [];
  applyTemplate: [content: string];
  insertSnippet: [content: string];
  clearDraft: [];
  importMarkdown: [data: ParsedMarkdown, confirmed?: boolean];
  uploadCoverImage: [file: File];
  generateWithAssistant: [request: WritingAssistantRequest];
  applyAssistantResult: [strategy: "append" | "replace"];
  clearAssistantResult: [];
  resolveDraftConflict: [];
  reloadConflictingDraft: [];
  "update:htmlClipFile": [file: File | null];
  openScreenshotOcr: [];
}>();

const fileInputRef = ref<HTMLInputElement | null>(null);
const htmlInputRef = ref<HTMLInputElement | null>(null);
const htmlFile = ref<File | null>(null);
const applyingImport = ref(false);
const mdImportParsed = ref<ParsedMarkdown | null>(null);
const mdImportFilename = ref("");
const coverInputRef = ref<HTMLInputElement | null>(null);

// 标签：多选 + 可创建。写入前统一走 normalizeTagList，
// 这样粘贴「甲，乙」这类中文逗号内容也会被拆成两个标签。
const tagModel = computed<string[]>({
  get: () => normalizeTagList(props.draft.tags),
  set: (value) => {
    props.draft.tags = normalizeTagList(value);
  },
});

// 下拉候选 = 站点已有标签 + 当前草稿标签（保证已选值能正确显示为选项）。
const tagCandidates = computed(() => mergeTagNames(props.tagOptions, props.draft.tags));

// 通用网页剪藏：外部传入的 HTML File 驱动 HTML 导入弹窗。
watch(
  [() => props.htmlClipFile, () => props.htmlClipSourceUrl],
  ([file, sourceUrl]) => {
    if (file) htmlFile.value = file;
  },
  { immediate: true },
);
function consumeHtmlClip() {
  htmlFile.value = null;
  emit("update:htmlClipFile", null);
}


const ALLOWED_EXTENSIONS = [".md", ".markdown", ".txt"];
const MAX_FILE_SIZE = 1024 * 1024; // 1MB

function triggerCoverInput() {
  coverInputRef.value?.click();
}

function handleCoverSelect(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    ElMessage.error("仅支持图片文件");
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.error("图片大小不能超过 5MB");
    return;
  }
  emit("uploadCoverImage", file);
}

function triggerFileInput() {
  fileInputRef.value?.click();
}

function triggerHtmlInput() {
  if (props.editingArticle) return;
  htmlInputRef.value?.click();
}

function handleHtmlSelect(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (!/\.html?$/i.test(file.name)) {
    ElMessage.error("仅支持 .html 或 .htm 文件");
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.error("HTML 文件不能超过 5 MiB");
    return;
  }
  htmlFile.value = file;
}

async function confirmImportOverwrite(dialogTitle: string): Promise<boolean> {
  if (props.draftConflict) {
    ElMessage.warning("请先处理另一个标签页的草稿冲突");
    return false;
  }
  if (props.draft.title.trim() || props.draft.content.trim()) {
    try {
      await ElMessageBox.confirm("导入会覆盖当前草稿内容，是否继续？", dialogTitle, {
        confirmButtonText: "继续导入", cancelButtonText: "取消", type: "warning"
      });
    } catch {
      return false;
    }
  }
  return true;
}

/** Shared import application: uploads matched local images, localizes remote
 * images via the B-040 endpoint, and only then touches the draft. Any failure
 * leaves the draft unchanged. */
async function applyImportWithAssets(
  data: ParsedMarkdown,
  images: Array<{ reference: string; remote: boolean; alt: string; file: File; token?: string }>,
  remoteImages: Array<{ reference: string; alt: string; token?: string }>,
  dialogTitle: string,
): Promise<boolean> {
  if (applyingImport.value) return false;
  if (!(await confirmImportOverwrite(dialogTitle))) return false;
  applyingImport.value = true;
  try {
    let content = data.content;
    for (const image of remoteImages) {
      const alt = image.alt.replace(/[\[\]\\\r\n]/g, " ");
      if (!content.includes(`![${alt}](${image.reference})`)) {
        throw new Error("图片位置校验失败，请重新预览后导入");
      }
    }
    if (images.some((image) => !content.includes(image.reference))) {
      throw new Error("图片位置校验失败，请重新预览后导入");
    }
    if (new Set(remoteImages.map((image) => image.reference)).size > 20) {
      ElMessage.error("单次最多自动下载 20 张图片，请减少选中内容或改用本地图片文件。");
      return false;
    }
    const downloaded = new Map<string, string>();
    for (const image of remoteImages) {
      if (downloaded.has(image.reference)) continue;
      const response = await fetch("/api/agent/blog/imports/html/images/fetch/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: image.reference }),
      });
      const payload = await response.json();
      if (!response.ok || typeof payload.url !== "string" || !/^\/media\/blog\/[0-9a-f]{32}\.(?:png|jpg|gif|webp)$/.test(payload.url)) {
        throw new Error(typeof payload.detail === "string" ? payload.detail : "图片下载或存储失败");
      }
      downloaded.set(image.reference, payload.url);
    }
    if (images.length) {
      const uploaded = await props.uploadHandler(images.map((image) => image.file));
      if (uploaded.length !== images.length || uploaded.some((image) => !image.url)) {
        ElMessage.error("配套图片上传失败，草稿没有更改。请检查图片格式后重试。");
        return false;
      }
      for (let index = 0; index < images.length; index++) {
        const alt = images[index].alt.replace(/[\[\]\\\r\n]/g, " ");
        const token = images[index].token;
        if (token) {
          content = content.split(token).join(`![${alt}](${uploaded[index].url})`);
        } else if (images[index].remote) {
          const oldImage = `![${alt}](${images[index].reference})`;
          content = content.split(oldImage).join(`![${alt}](${uploaded[index].url})`);
        } else {
          content = content.split(images[index].reference).join(`![${alt}](${uploaded[index].url})`);
        }
      }
    }
    for (const image of remoteImages) {
      const alt = image.alt.replace(/[\[\]\\\r\n]/g, " ");
      const oldImage = image.token ?? `![${alt}](${image.reference})`;
      content = content.split(oldImage).join(`![${alt}](${downloaded.get(image.reference)})`);
    }
    emit("importMarkdown", { ...data, content }, true);
    htmlFile.value = null;
    return true;
  } catch (error) {
    ElMessage.error(error instanceof Error ? `${error.message}；草稿没有更改。` : "远程图片导入失败；草稿没有更改。");
    return false;
  } finally {
    applyingImport.value = false;
  }
}

function applyMarkdownImport(
  data: ParsedMarkdown,
  images: Array<{ reference: string; remote: boolean; alt: string; file: File; token?: string }>,
  remoteImages: Array<{ reference: string; alt: string; token?: string }>,
) {
  void applyImportWithAssets(data, images, remoteImages, "导入 Markdown").then((ok) => {
    if (ok) mdImportParsed.value = null;
  });
}

function applyHtmlImport(
  data: ParsedMarkdown,
  images: Array<{ reference: string; remote: boolean; alt: string; file: File }>,
  remoteImages: Array<{ reference: string; alt: string }>,
) {
  void applyImportWithAssets(data, images, remoteImages, "导入 HTML");
}


function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";

  if (!file) return;

  const ext = "." + file.name.split(".").pop()?.toLowerCase();
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    ElMessage.error("仅支持 .md、.markdown、.txt 文件");
    return;
  }

  if (file.size > MAX_FILE_SIZE) {
    ElMessage.error("文件大小不能超过 1MB");
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    try {
      const raw = reader.result as string;
      if (!raw.trim()) {
        ElMessage.error("文件内容为空");
        return;
      }
      const parsed = parseMarkdownFile(raw, file.name);
      if (findMarkdownImages(parsed.content).length) {
        // 正文引用了图片：本机路径/防外链地址博客无法显示，先让用户配套图片文件
        mdImportFilename.value = file.name;
        mdImportParsed.value = parsed;
        return;
      }
      emit("importMarkdown", parsed);
    } catch {
      ElMessage.error("解析 Markdown 文件失败");
    }
  };
  reader.onerror = () => {
    ElMessage.error("读取文件失败");
  };
  reader.readAsText(file, "UTF-8");
}

// Image upload adapter for Vditor
async function vditorUploadHandler(files: File[]): Promise<Array<{ url: string; alt?: string; title?: string }>> {
  return props.uploadHandler(files);
}
</script>

<template>
  <section class="write-box markdown-writer">
    <!-- 标题栏 -->
    <header class="writer-heading">
      <h2>
        <el-icon><EditPen /></el-icon>
        {{ editingArticle ? `编辑笔记: ${editingArticle.title}` : 'Markdown 写作台' }}
      </h2>
      <div class="writer-heading-actions">
        <input
          ref="fileInputRef"
          type="file"
          :accept="ALLOWED_EXTENSIONS.join(',')"
          style="display: none"
          @change="handleFileSelect"
        />
        <input ref="htmlInputRef" type="file" accept=".html,.htm" style="display: none" @change="handleHtmlSelect" />
        <ThemeSwitcher />
        <el-button v-if="editingArticle" @click="emit('cancelEdit')">取消编辑</el-button>
        <el-button
          type="primary"
          :loading="editingArticle ? updating : publishing"
          @click="editingArticle ? emit('update') : emit('publish', true)"
        >
          {{ editingArticle ? '更新并重新提交' : '发布并加入知识库' }}
        </el-button>
      </div>
    </header>

    <!-- 元信息栏 -->
    <div class="writer-fields">
      <el-input v-model="draft.title" size="large" placeholder="文章标题" />
      <el-input v-model="draft.summary" placeholder="摘要，会显示在文章卡片里" />

      <!-- 封面图 -->
      <div class="writer-cover-image">
        <el-input v-model="draft.cover_image" placeholder="封面图片 URL（可粘贴地址或点击上传）">
          <template #prepend>封面图</template>
          <template #append>
            <input
              ref="coverInputRef"
              type="file"
              accept="image/*"
              style="display: none"
              @change="handleCoverSelect"
            />
            <el-button @click="triggerCoverInput">上传</el-button>
          </template>
        </el-input>
        <div v-if="draft.cover_image" class="cover-preview">
          <img :src="draft.cover_image" alt="封面预览" />
          <el-button size="small" type="danger" plain @click="draft.cover_image = ''">移除</el-button>
        </div>
      </div>

      <div class="writer-meta">
        <el-select
          v-model="draft.category"
          filterable
          allow-create
          default-first-option
          placeholder="选择已有分类或输入新分类"
        >
          <el-option v-for="item in categories" :key="item.id" :label="item.name" :value="item.name" />
        </el-select>
        <el-select
          v-model="tagModel"
          multiple
          filterable
          allow-create
          default-first-option
          collapse-tags
          :max-collapse-tags="3"
          placeholder="选择或输入标签，回车确认"
          aria-label="文章标签"
          class="writer-tags"
        >
          <el-option v-for="name in tagCandidates" :key="name" :label="name" :value="name" />
        </el-select>
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="writer-toolbar">
      <div class="toolbar-group">
        <el-dropdown trigger="click">
          <el-button>
            写作模板
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="item in templates"
                :key="item.name"
                @click="emit('applyTemplate', item.content)"
              >
                {{ item.name }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <div class="toolbar-group">
        <el-button :icon="UploadFilled" @click="triggerFileInput">导入</el-button>
        <el-button v-if="!editingArticle" @click="triggerHtmlInput">导入 HTML</el-button>
        <el-button v-if="!editingArticle" @click="emit('openScreenshotOcr')">截图识别</el-button>
        <el-button plain type="danger" @click="emit('clearDraft')">清空草稿</el-button>
      </div>
      <div class="toolbar-divider" />
      <div class="toolbar-group">
        <el-button @click="emit('insertSnippet', '## 新标题')" title="二级标题">H2</el-button>
        <el-button @click="emit('insertSnippet', '### 新标题')" title="三级标题">H3</el-button>
        <el-button @click="emit('insertSnippet', '> 这里记录一个关键观察。')" title="引用">引用</el-button>
        <el-button @click="emit('insertSnippet', '- 列表项一\n- 列表项二')" title="列表">列表</el-button>
        <el-button @click="emit('insertSnippet', '```python\n# code here\n```')" title="代码块">代码</el-button>
        <el-button @click="emit('insertSnippet', '[链接文字](https://example.com)')" title="链接">链接</el-button>
      </div>
    </div>

    <WritingAssistantPanel
      :authenticated="authenticated"
      :has-content="Boolean(draft.content.trim())"
      :loading="writingAssistantLoading"
      :error="writingAssistantError"
      :result="writingAssistantResult"
      @generate="emit('generateWithAssistant', $event)"
      @apply="emit('applyAssistantResult', $event)"
      @clear="emit('clearAssistantResult')"
    />

    <!-- 编辑器区域（Vditor WYSIWYG 编辑器） -->
    <div class="editor-container">
      <VditorEditor
        :key="editorCacheId"
        v-model="draft.content"
        :cache-id="editorCacheId"
        mode="wysiwyg"
        :height="600"
        :upload-handler="vditorUploadHandler"
        class="blog-vditor-editor"
      />
    </div>

    <el-alert
      v-if="draftConflict"
      class="draft-conflict-alert"
      type="warning"
      :closable="false"
      title="检测到另一个标签页修改了这篇草稿，自动保存已暂停。请选择保留当前内容或载入另一标签页的版本。"
    >
      <template #default>
        <el-button size="small" @click="emit('reloadConflictingDraft')">载入另一标签页版本</el-button>
        <el-button size="small" type="warning" @click="emit('resolveDraftConflict')">保留当前版本并覆盖</el-button>
      </template>
    </el-alert>
    <p class="draft-save-status" role="status" aria-live="polite">{{ draftSaveStatus }}</p>

    <!-- 错误提示 -->
    <p v-if="error" class="editor-error">{{ error }}</p>

    <!-- 状态栏 -->
    <div class="writer-footer">
      <div class="writer-stats">
        <span>{{ stats.words }} 字</span>
        <span>约 {{ stats.readingMinutes }} 分钟阅读</span>
        <span>自动保存</span>
      </div>
      <el-button
        type="primary"
        :loading="editingArticle ? updating : publishing"
        @click="editingArticle ? emit('update') : emit('publish', false)"
      >
        {{ editingArticle ? '更新并重新提交' : '发布文章' }}
      </el-button>
    </div>
  </section>

  <ThemeCreator />
  <HtmlImportDialog
    :file="htmlFile"
    :visible="Boolean(htmlFile)"
    :applying="applyingImport"
    :clip-file="htmlFile"
    :clip-source-url="props.htmlClipSourceUrl"
    :clip-title="props.htmlClipTitle"
    :clip-own-note="props.htmlClipOwnNote"
    @close="htmlFile = null"
    @apply="applyHtmlImport"
  />
  <MarkdownImportDialog
    :visible="Boolean(mdImportParsed)"
    :applying="applyingImport"
    :parsed="mdImportParsed"
    :filename="mdImportFilename"
    @close="mdImportParsed = null"
    @apply="applyMarkdownImport"
  />
</template>
