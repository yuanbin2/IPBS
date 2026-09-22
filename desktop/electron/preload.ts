import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'

// Custom APIs for renderer
const api = {
  // Window controls
  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    close: () => ipcRenderer.invoke('window:close'),
    isMaximized: () => ipcRenderer.invoke('window:isMaximized')
  },

  // System integration
  system: {
    notification: (title: string, body: string) =>
      ipcRenderer.invoke('system:notification', { title, body })
  },

  // Backend management
  backend: {
    status: () => ipcRenderer.invoke('backend:status'),
    restart: () => ipcRenderer.invoke('backend:restart')
  },

  // File operations
  file: {
    open: () => ipcRenderer.invoke('dialog:openFile'),
    save: (content: string) => ipcRenderer.invoke('dialog:saveFile', content)
  },

  // Platform info
  platform: process.platform,

  // App version
  version: process.env.npm_package_version || '1.0.0'
}

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI)
    contextBridge.exposeInMainWorld('api', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = electronAPI
  // @ts-ignore (define in dts)
  window.api = api
}
