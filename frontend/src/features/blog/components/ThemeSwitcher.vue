<script setup lang="ts">
import { ref } from 'vue';
import { Setting } from '@element-plus/icons-vue';
import { useThemeStore } from '../stores/themeStore';
import type { BlogTheme } from '../themes/themeTypes';

const themeStore = useThemeStore();
const dropdownVisible = ref(false);

function selectTheme(id: string) {
  themeStore.setTheme(id);
  dropdownVisible.value = false;
}

function editTheme(theme: BlogTheme) {
  themeStore.openCreator(theme);
  dropdownVisible.value = false;
}

function createNew() {
  themeStore.openCreator();
  dropdownVisible.value = false;
}

function getPreviewColors(theme: BlogTheme) {
  return {
    bg: theme.bgColor,
    text: theme.textColor,
    accent: theme.linkColor,
    border: theme.borderColor,
  };
}
</script>

<template>
  <el-dropdown trigger="click" v-model:visible="dropdownVisible" placement="bottom-end">
    <el-button :icon="Setting" circle size="small" title="切换主题" />
    <template #dropdown>
      <el-dropdown-menu class="theme-dropdown">
        <div class="theme-dropdown-header">
          <span>选择主题</span>
          <el-button size="small" type="primary" link @click="createNew">新建主题</el-button>
        </div>
        <div class="theme-list">
          <div
            v-for="theme in themeStore.allThemes"
            :key="theme.id"
            :class="['theme-item', { active: theme.id === themeStore.currentThemeId }]"
            @click="selectTheme(theme.id)"
          >
            <div class="theme-preview">
              <div
                class="theme-preview-swatch"
                :style="{
                  background: getPreviewColors(theme).bg,
                  borderColor: getPreviewColors(theme).border,
                }"
              >
                <div
                  class="theme-preview-text"
                  :style="{ color: getPreviewColors(theme).text }"
                >
                  Aa
                </div>
                <div
                  class="theme-preview-accent"
                  :style="{ background: getPreviewColors(theme).accent }"
                />
              </div>
            </div>
            <div class="theme-info">
              <span class="theme-name">{{ theme.name }}</span>
              <span class="theme-desc">{{ theme.description }}</span>
            </div>
            <div class="theme-actions">
              <el-button
                v-if="!theme.id.startsWith('custom-') || true"
                size="small"
                type="primary"
                link
                @click.stop="editTheme(theme)"
              >
                编辑
              </el-button>
            </div>
          </div>
        </div>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.theme-dropdown {
  width: 320px;
  padding: 0;
}

.theme-dropdown-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-divider);
  font-weight: 600;
  font-size: 14px;
}

.theme-list {
  max-height: 400px;
  overflow-y: auto;
  padding: 8px;
}

.theme-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.theme-item:hover {
  background: var(--color-bg-page);
}

.theme-item.active {
  background: var(--color-primary-soft);
  border: 1px solid var(--color-primary-border);
}

.theme-preview {
  flex-shrink: 0;
}

.theme-preview-swatch {
  width: 48px;
  height: 36px;
  border-radius: 6px;
  border: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  position: relative;
}

.theme-preview-text {
  font-size: 14px;
  font-weight: 600;
  line-height: 1;
}

.theme-preview-accent {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 4px;
}

.theme-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.theme-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-primary);
}

.theme-desc {
  font-size: 12px;
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.theme-actions {
  flex-shrink: 0;
}
</style>