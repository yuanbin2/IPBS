import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface DesktopState {
  isElectron: boolean
  isMaximized: boolean
  isFullscreen: boolean
  backendConnected: boolean
  backendUrl: string
  appVersion: string
  platform: string
}

export const useDesktopStore = defineStore('desktop', () => {
  // State
  const isElectron = ref(false)
  const isMaximized = ref(false)
  const isFullscreen = ref(false)
  const backendConnected = ref(false)
  const backendUrl = ref('http://127.0.0.1:8000')
  const appVersion = ref('1.0.0')
  const platform = ref('')

  // Getters
  const isDesktop = computed(() => isElectron.value)
  const connectionStatus = computed(() => backendConnected.value ? 'connected' : 'disconnected')

  // Actions
  function initialize(electronAPI?: any) {
    if (electronAPI) {
      isElectron.value = true
      platform.value = electronAPI.platform || ''
      appVersion.value = electronAPI.version || '1.0.0'
    }
  }

  async function checkBackendStatus(electronAPI?: any) {
    if (!electronAPI) return

    try {
      const status = await electronAPI.backend.status()
      backendConnected.value = status.connected
      backendUrl.value = status.url
    } catch {
      backendConnected.value = false
    }
  }

  async function restartBackend(electronAPI?: any) {
    if (!electronAPI) return false

    try {
      await electronAPI.backend.restart()
      await checkBackendStatus(electronAPI)
      return true
    } catch {
      return false
    }
  }

  function updateMaximizedState(maximized: boolean) {
    isMaximized.value = maximized
  }

  function updateFullscreenState(fullscreen: boolean) {
    isFullscreen.value = fullscreen
  }

  return {
    // State
    isElectron,
    isMaximized,
    isFullscreen,
    backendConnected,
    backendUrl,
    appVersion,
    platform,

    // Getters
    isDesktop,
    connectionStatus,

    // Actions
    initialize,
    checkBackendStatus,
    restartBackend,
    updateMaximizedState,
    updateFullscreenState
  }
})
