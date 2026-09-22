<script setup lang="ts">
import { ref, watch } from "vue";
import { EditPen, UploadFilled, ArrowDown } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { MdEditor, type UploadImgEvent, type HeadList } from "md-editor-v3";
import { EditorView } from "@codemirror/view";
import type { BlogDraft, EditorStats } from "../types";
import { parseMarkdownFile, type ParsedMarkdown } from "../utils/parseMarkdownFile";

const props = defineProps<{
  draft: BlogDraft;
  templates: Array<{ name: string; content: string }>;
  stats: EditorStats;
  publishing: boolean;
  uploadingImage: boolean;
  error: string;
  uploadHandler: UploadImgEvent;
  editingArticle?: { title: string } | null;
  updating?: boolean;
}>();

const emit = defineEmits<{
  publish: [];
  update: [];
  cancelEdit: [];
  applyTemplate: [content: string];
  insertSnippet: [content: string];
  clearDraft: [];
  importMarkdown: [data: ParsedMarkdown];
}>();

const fileInputRef = ref<HTMLInputElement | null>(null);
const editorRef = ref<InstanceType<typeof MdEditor>>();
const headings = ref<HeadList[]>([]);
const activeHeadingIndex = ref(0);

const ALLOWED_EXTENSIONS = [".md", ".markdown", ".txt"];
const MAX_FILE_SIZE = 1024 * 1024; // 1MB

function triggerFileInput() {
  fileInputRef.value?.click();
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

// 获取目录
function handleGetCatalog(list: HeadList[]) {
  headings.value = list;
}

// 跳转到标题
function scrollToHeading(item: HeadList, index: number) {
  const editorView = editorRef.value?.getEditorView();
  if (!editorView) return;

  activeHeadingIndex.value = index;

  // 获取标题所在的行
  const line = item.line;
  const lineObj = editorView.state.doc.line(line);

  // 滚动到该行并聚焦
  editorView.dispatch({
    selection: { anchor: lineObj.from },
    effects: EditorView.scrollIntoView(lineObj.from, { y: 'start' })
  });

  // 聚焦编辑器
  editorView.focus();
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
        <el-button v-if="editingArticle" @click="emit('cancelEdit')">取消编辑</el-button>
        <el-button
          type="primary"
          :loading="editingArticle ? updating : publishing"
          @click="editingArticle ? emit('update') : emit('publish')"
        >
          {{ editingArticle ? '更新并重新提交' : '发布并加入知识库' }}
        </el-button>
      </div>
    </header>

    <!-- 元信息栏 -->
    <div class="writer-fields">
      <el-input v-model="draft.title" size="large" placeholder="文章标题" />
      <el-input v-model="draft.summary" placeholder="摘要，会显示在文章卡片里" />
      <div class="writer-meta">
        <el-input v-model="draft.category" placeholder="分类" />
        <el-input v-model="draft.tags" placeholder="标签，逗号分隔" />
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

    <!-- 编辑器区域（左侧大纲 + 右侧编辑器） -->
    <div class="editor-container">
      <!-- 左侧大纲 -->
      <aside class="editor-outline" v-if="headings.length">
        <div class="outline-header">大纲</div>
        <nav class="outline-nav">
          <a
            v-for="(item, index) in headings"
            :key="index"
            :class="['outline-item', `level-${item.level}`, { active: activeHeadingIndex === index }]"
            @click="scrollToHeading(item, index)"
          >
            {{ item.text }}
          </a>
        </nav>
      </aside>

      <!-- 右侧编辑器 -->
      <div class="editor-main">
        <MdEditor
          ref="editorRef"
          v-model="draft.content"
          language="zh-CN"
          preview-theme="github"
          code-theme="github"
          :toolbars-exclude="['github']"
          :show-code-row-number="true"
          :footers="['markdownTotal', 'scrollSwitch']"
          :on-upload-img="uploadHandler"
          @onGetCatalog="handleGetCatalog"
          placeholder="用 Markdown 写正文，可插入标题、列表、代码块、表格、链接、图片、流程图和公式。"
          class="blog-md-editor"
        />
      </div>
    </div>

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
        @click="editingArticle ? emit('update') : emit('publish')"
      >
        {{ editingArticle ? '更新并重新提交' : '发布文章' }}
      </el-button>
    </div>
  </section>
</template>
