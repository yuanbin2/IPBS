<script setup lang="ts">
import { EditPen } from "@element-plus/icons-vue";
import { MdEditor, type UploadImgEvent } from "md-editor-v3";
import type { BlogDraft, EditorStats } from "../types";

defineProps<{
  draft: BlogDraft;
  templates: Array<{ name: string; content: string }>;
  stats: EditorStats;
  publishing: boolean;
  uploadingImage: boolean;
  error: string;
  uploadHandler: UploadImgEvent;
}>();

const emit = defineEmits<{
  publish: [];
  applyTemplate: [content: string];
  insertSnippet: [content: string];
  clearDraft: [];
}>();
</script>

<template>
  <section class="write-box markdown-writer">
    <header class="writer-heading">
      <h2><el-icon><EditPen /></el-icon> Markdown 写作台</h2>
      <el-button type="primary" :loading="publishing" @click="emit('publish')">发布并加入知识库</el-button>
    </header>

    <div class="writer-fields">
      <el-input v-model="draft.title" size="large" placeholder="文章标题" />
      <el-input v-model="draft.summary" placeholder="摘要，会显示在文章卡片里" />
      <div class="writer-meta">
        <el-input v-model="draft.category" placeholder="分类" />
        <el-input v-model="draft.tags" placeholder="标签，逗号分隔" />
      </div>
    </div>

    <section class="editor-workspace">
      <section class="note-workbench">
        <div class="note-tool-group">
          <strong class="note-tool-label">写作模板</strong>
          <div class="note-actions">
            <el-button v-for="item in templates" :key="item.name" @click="emit('applyTemplate', item.content)">
              {{ item.name }}
            </el-button>
          </div>
        </div>
        <div class="note-tool-group">
          <strong class="note-tool-label">快捷格式</strong>
          <div class="note-actions">
            <el-button @click="emit('insertSnippet', '## 新标题')">二级标题</el-button>
            <el-button @click="emit('insertSnippet', '> 这里记录一个关键观察。')">引用</el-button>
            <el-button @click="emit('insertSnippet', '- 列表项一\n- 列表项二')">列表</el-button>
            <el-button @click="emit('insertSnippet', '```python\n# code here\n```')">代码块</el-button>
            <el-button @click="emit('insertSnippet', '[链接文字](https://example.com)')">链接</el-button>
          </div>
        </div>
      </section>

      <section class="note-context">
        <div class="note-draft-actions">
          <span>草稿会自动保存在当前浏览器</span>
          <el-button plain type="danger" @click="emit('clearDraft')">清理本地草稿</el-button>
        </div>
        <div class="note-stats">
          <span>{{ stats.words }} 字</span><span>约 {{ stats.readingMinutes }} 分钟阅读</span><span>自动保存</span>
        </div>
        <div v-if="stats.headings.length" class="note-outline">
          <strong>大纲</strong><span v-for="heading in stats.headings" :key="heading">{{ heading }}</span>
        </div>
      </section>

      <MdEditor
        v-model="draft.content"
        language="zh-CN"
        preview-theme="github"
        code-theme="github"
        :toolbars-exclude="['github']"
        :show-code-row-number="true"
        :footers="['markdownTotal', 'scrollSwitch']"
        :on-upload-img="uploadHandler"
        placeholder="用 Markdown 写正文，可插入标题、列表、代码块、表格、链接、图片、流程图和公式。"
        class="blog-md-editor"
      />
    </section>

    <p v-if="error" class="editor-error">{{ error }}</p>
    <div class="writer-footer">
      <span>{{ uploadingImage ? "图片上传中..." : "支持工具栏、预览、全屏、代码块、表格、链接和图片上传" }}</span>
      <el-button type="primary" :loading="publishing" @click="emit('publish')">发布文章</el-button>
    </div>
  </section>
</template>
