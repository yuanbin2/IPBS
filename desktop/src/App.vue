<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useDesktopStore } from './desktop/stores/desktop'
import DesktopShell from './desktop/components/DesktopShell.vue'
import AppShell from './components/AppShell.vue'

const route = useRoute()
const desktopStore = useDesktopStore()

const isPublicPage = computed(() => Boolean(route.meta.public))
const isDesktop = computed(() => desktopStore.isDesktop)

// Get electronAPI from window if available
const electronAPI = (window as any).electronAPI

onMounted(() => {
  // Initialize desktop store
  desktopStore.initialize(electronAPI)

  // Start backend status checks if in desktop mode
  if (electronAPI) {
    desktopStore.checkBackendStatus(electronAPI)
  }
})
</script>

<template>
  <!-- Desktop mode with custom shell -->
  <DesktopShell
    v-if="isDesktop && !isPublicPage"
    :electron-api="electronAPI"
  >
    <RouterView />
  </DesktopShell>

  <!-- Web mode or public pages -->
  <template v-else>
    <RouterView v-if="isPublicPage" />
    <AppShell v-else>
      <RouterView />
    </AppShell>
  </template>
</template>

<style>
/* Desktop-specific global styles */
.desktop-shell {
  --titlebar-height: 32px;
}

.desktop-content {
  height: calc(100vh - var(--titlebar-height));
}
</style>
