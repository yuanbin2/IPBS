const { contextBridge, ipcRenderer } = require('electron')

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
    notification: (title, body) =>
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
    save: (content) => ipcRenderer.invoke('dialog:saveFile', content)
  },

  // Platform info
  platform: process.platform,

  // App version
  version: '1.0.0'
}

// Expose APIs to renderer
contextBridge.exposeInMainWorld('electronAPI', {
  minimize: () => ipcRenderer.invoke('window:minimize'),
  maximize: () => ipcRenderer.invoke('window:maximize'),
  close: () => ipcRenderer.invoke('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:isMaximized')
})

contextBridge.exposeInMainWorld('api', api)
