<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Minus, FullScreen, Close, CopyDocument } from '@element-plus/icons-vue'
import AppShell from '../../components/AppShell.vue'

const isMaximized = ref(false)

const props = defineProps<{
  electronAPI?: any
}>()

const emit = defineEmits<{
  minimize: []
  maximize: []
  close: []
}>()

onMounted(async () => {
  if (props.electronAPI) {
    isMaximized.value = await props.electronAPI.window.isMaximized()
  }
})

function handleMinimize() {
  if (props.electronAPI) {
    props.electronAPI.window.minimize()
  }
  emit('minimize')
}

function handleMaximize() {
  if (props.electronAPI) {
    props.electronAPI.window.maximize()
    isMaximized.value = !isMaximized.value
  }
  emit('maximize')
}

function handleClose() {
  if (props.electronAPI) {
    props.electronAPI.window.close()
  }
  emit('close')
}

function handleDoubleClick() {
  handleMaximize()
}
</script>

<template>
  <div class="desktop-shell">
    <!-- Custom Title Bar -->
    <div class="titlebar" @dblclick="handleDoubleClick">
      <div class="titlebar-content">
        <div class="titlebar-brand">
          <div class="titlebar-logo">K</div>
          <span class="titlebar-title">Knowledge Agent</span>
        </div>

        <div class="titlebar-controls">
          <button
            class="titlebar-btn"
            title="最小化"
            @click="handleMinimize"
          >
            <el-icon><Minus /></el-icon>
          </button>
          <button
            class="titlebar-btn"
            :title="isMaximized ? '还原' : '最大化'"
            @click="handleMaximize"
          >
            <el-icon>
              <CopyDocument v-if="isMaximized" />
              <FullScreen v-else />
            </el-icon>
          </button>
          <button
            class="titlebar-btn close"
            title="关闭"
            @click="handleClose"
          >
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </div>

    <!-- App Content -->
    <div class="desktop-content">
      <AppShell>
        <slot />
      </AppShell>
    </div>
  </div>
</template>

<style scoped>
.desktop-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--color-bg-page);
}

.titlebar {
  height: 32px;
  background: var(--color-bg-sidebar);
  display: flex;
  align-items: center;
  padding: 0 8px;
  -webkit-app-region: drag;
  user-select: none;
  flex-shrink: 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.titlebar-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.titlebar-brand {
  display: flex;
  align-items: center;
  gap: 8px;
}

.titlebar-logo {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  background: var(--color-primary);
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.titlebar-title {
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  opacity: 0.9;
}

.titlebar-controls {
  display: flex;
  align-items: center;
  gap: 0;
  -webkit-app-region: no-drag;
}

.titlebar-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: #a9bfc8;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: background-color 0.15s, color 0.15s;
}

.titlebar-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.titlebar-btn.close:hover {
  background: #b64b4b;
  color: #ffffff;
}

.desktop-content {
  flex: 1;
  overflow: hidden;
}
</style>
