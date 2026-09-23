<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useThemeStore } from '../stores/themeStore';
import { THEME_PROPERTIES, FONT_OPTIONS } from '../themes/themeTypes';
import type { BlogTheme } from '../themes/themeTypes';
import { applyThemeToElement } from '../themes/applyTheme';

const themeStore = useThemeStore();

const localTheme = ref<BlogTheme | null>(null);
const previewRef = ref<HTMLElement>();

// Watch for editing theme changes
watch(() => themeStore.editingTheme, (theme) => {
  if (theme) {
    localTheme.value = { ...theme };
  }
}, { immediate: true });

// Live preview
watch(localTheme, (theme) => {
  if (theme && previewRef.value) {
    applyThemeToElement(previewRef.value, theme);
  }
}, { deep: true });

const groupedProperties = computed(() => {
  const groups: Record<string, typeof THEME_PROPERTIES> = {
    colors: [],
    typography: [],
    spacing: [],
  };
  THEME_PROPERTIES.forEach(prop => {
    groups[prop.group].push(prop);
  });
  return groups;
});

function handleSave() {
  if (!localTheme.value) return;
  if (!localTheme.value.name.trim()) {
    ElMessage.error('请输入主题名称');
    return;
  }
  themeStore.saveCustomTheme(localTheme.value);
  themeStore.setTheme(localTheme.value.id);
  themeStore.closeCreator();
  ElMessage.success('主题已保存');
}

function handleCancel() {
  themeStore.closeCreator();
}
</script>

<template>
  <el-dialog
    v-model="themeStore.creatorOpen"
    title="自定义主题"
    width="900px"
    align-center
    :close-on-click-modal="false"
    @close="handleCancel"
  >
    <div v-if="localTheme" class="theme-creator">
      <!-- Left: Form -->
      <div class="creator-form">
        <!-- Basic Info -->
        <div class="form-section">
          <h4>基本信息</h4>
          <div class="form-row">
            <label>主题名称</label>
            <el-input v-model="localTheme.name" placeholder="我的主题" />
          </div>
          <div class="form-row">
            <label>描述</label>
            <el-input v-model="localTheme.description" placeholder="主题描述" />
          </div>
        </div>

        <!-- Colors -->
        <div class="form-section">
          <h4>颜色</h4>
          <div class="color-grid">
            <div v-for="prop in groupedProperties.colors" :key="prop.key" class="color-item">
              <label>{{ prop.label }}</label>
              <div class="color-input-wrapper">
                <input
                  type="color"
                  :value="localTheme[prop.key]"
                  @input="localTheme[prop.key] = ($event.target as HTMLInputElement).value"
                  class="color-picker"
                />
                <el-input
                  v-model="localTheme[prop.key]"
                  size="small"
                  class="color-text"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Typography -->
        <div class="form-section">
          <h4>排版</h4>
          <div class="form-row">
            <label>正文字体</label>
            <el-select v-model="localTheme.fontFamily" filterable allow-create>
              <el-option
                v-for="font in FONT_OPTIONS"
                :key="font.value"
                :label="font.label"
                :value="font.value"
              />
            </el-select>
          </div>
          <div class="form-row">
            <label>标题字体</label>
            <el-select v-model="localTheme.headingFont" filterable allow-create>
              <el-option
                v-for="font in FONT_OPTIONS"
                :key="font.value"
                :label="font.label"
                :value="font.value"
              />
            </el-select>
          </div>
          <div class="form-row-inline">
            <div class="form-row">
              <label>字号</label>
              <el-input v-model="localTheme.fontSize" />
            </div>
            <div class="form-row">
              <label>行高</label>
              <el-input v-model="localTheme.lineHeight" />
            </div>
            <div class="form-row">
              <label>内容宽度</label>
              <el-input v-model="localTheme.contentWidth" />
            </div>
          </div>
        </div>

        <!-- Spacing -->
        <div class="form-section">
          <h4>间距</h4>
          <div class="form-row-inline">
            <div class="form-row">
              <label>段落间距</label>
              <el-input v-model="localTheme.paragraphSpacing" />
            </div>
            <div class="form-row">
              <label>标题间距</label>
              <el-input v-model="localTheme.headingSpacing" />
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Preview -->
      <div class="creator-preview">
        <h4>预览</h4>
        <div ref="previewRef" class="preview-content theme-preview-container">
          <h1 style="margin-bottom: 12px;">文章标题示例</h1>
          <p style="margin-bottom: 12px;">这是一段正文内容，用于预览主题效果。Markdown 是一种轻量级标记语言，允许你使用易于阅读和编写的纯文本格式编写文档。</p>
          <h2 style="margin: 20px 0 12px;">二级标题</h2>
          <p style="margin-bottom: 12px;">支持 <a href="#">链接样式</a>、<strong>粗体</strong>、<em>斜体</em> 等基本格式。</p>
          <blockquote style="margin: 12px 0; padding: 12px 16px;">
            这是一段引用文字，用于展示引用块的样式效果。
          </blockquote>
          <pre style="margin: 12px 0; padding: 12px; border-radius: 6px;"><code>console.log('Hello, World!');</code></pre>
          <h3 style="margin: 16px 0 8px;">三级标题</h3>
          <ul style="margin: 0 0 12px; padding-left: 24px;">
            <li>列表项一</li>
            <li>列表项二</li>
            <li>列表项三</li>
          </ul>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button type="primary" @click="handleSave">保存主题</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.theme-creator {
  display: flex;
  gap: 24px;
  max-height: 70vh;
}

.creator-form {
  flex: 1;
  overflow-y: auto;
  padding-right: 12px;
}

.creator-preview {
  width: 360px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}

.creator-preview h4 {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.form-section {
  margin-bottom: 20px;
}

.form-section h4 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
  border-bottom: 1px solid var(--color-divider);
  padding-bottom: 8px;
}

.form-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}

.form-row label {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.form-row-inline {
  display: flex;
  gap: 12px;
}

.form-row-inline .form-row {
  flex: 1;
}

.color-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.color-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.color-item label {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.color-input-wrapper {
  display: flex;
  align-items: center;
  gap: 8px;
}

.color-picker {
  width: 32px;
  height: 32px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  cursor: pointer;
  padding: 2px;
}

.color-text {
  flex: 1;
}

.preview-content {
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 20px;
  overflow-y: auto;
  flex: 1;
  transition: all 0.3s;
}

.theme-preview-container {
  color: var(--theme-text, var(--color-text-primary));
  background: var(--theme-bg, var(--color-bg-surface));
  font-family: var(--theme-font, var(--font-family));
  font-size: var(--theme-font-size, 15px);
  line-height: var(--theme-line-height, 1.8);
}

.theme-preview-container h1,
.theme-preview-container h2,
.theme-preview-container h3 {
  color: var(--theme-heading, var(--color-text-primary));
  font-family: var(--theme-heading-font, var(--font-family));
}

.theme-preview-container a {
  color: var(--theme-link, var(--color-primary));
}

.theme-preview-container blockquote {
  background: var(--theme-quote-bg, var(--color-bg-page));
  border-left: 4px solid var(--theme-quote-border, var(--color-primary));
}

.theme-preview-container pre {
  background: var(--theme-code-bg, #1a2332);
  color: var(--theme-code-text, #e0e8ec);
}

.theme-preview-container pre code {
  color: inherit;
}
</style>