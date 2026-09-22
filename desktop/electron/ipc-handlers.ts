import { ipcMain, dialog, BrowserWindow, clipboard, Notification } from 'electron'
import { readFileSync, writeFileSync, existsSync } from 'fs'
import { join } from 'path'

// Window management handlers
export function setupWindowHandlers(): void {
  ipcMain.handle('window:minimize', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    window?.minimize()
  })

  ipcMain.handle('window:maximize', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    if (window?.isMaximized()) {
      window.unmaximize()
    } else {
      window?.maximize()
    }
  })

  ipcMain.handle('window:close', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    window?.close()
  })

  ipcMain.handle('window:isMaximized', (event) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    return window?.isMaximized() ?? false
  })
}

// System notification handlers
export function setupSystemHandlers(): void {
  ipcMain.handle('system:notification', (_, { title, body }: { title: string; body: string }) => {
    new Notification({ title, body }).show()
  })
}

// File dialog handlers
export function setupFileHandlers(): void {
  ipcMain.handle('dialog:openFile', async (event) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    if (!window) return null

    const result = await dialog.showOpenDialog(window, {
      properties: ['openFile'],
      filters: [
        { name: 'Markdown', extensions: ['md'] },
        { name: 'Text', extensions: ['txt'] },
        { name: 'All Files', extensions: ['*'] }
      ]
    })

    if (result.canceled || result.filePaths.length === 0) {
      return null
    }

    const filePath = result.filePaths[0]
    try {
      const content = readFileSync(filePath, 'utf-8')
      return { filePath, content }
    } catch (error) {
      console.error('Failed to read file:', error)
      return null
    }
  })

  ipcMain.handle('dialog:saveFile', async (event, { content, defaultPath }: { content: string; defaultPath?: string }) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    if (!window) return null

    const result = await dialog.showSaveDialog(window, {
      defaultPath: defaultPath || 'untitled.md',
      filters: [
        { name: 'Markdown', extensions: ['md'] },
        { name: 'Text', extensions: ['txt'] }
      ]
    })

    if (result.canceled || !result.filePath) {
      return null
    }

    try {
      writeFileSync(result.filePath, content, 'utf-8')
      return { filePath: result.filePath, success: true }
    } catch (error) {
      console.error('Failed to save file:', error)
      return { filePath: result.filePath, success: false, error: String(error) }
    }
  })
}

// Clipboard handlers
export function setupClipboardHandlers(): void {
  ipcMain.handle('clipboard:read', () => {
    return clipboard.readText()
  })

  ipcMain.handle('clipboard:write', (_, text: string) => {
    clipboard.writeText(text)
    return true
  })
}

// Backend management handlers
export function setupBackendHandlers(backendUrl: string): void {
  ipcMain.handle('backend:status', async () => {
    try {
      const response = await fetch(`${backendUrl}/api/health/`)
      return { connected: response.ok, url: backendUrl }
    } catch {
      return { connected: false, url: backendUrl }
    }
  })

  ipcMain.handle('backend:url', () => {
    return backendUrl
  })
}

// Setup all IPC handlers
export function setupAllHandlers(backendUrl: string): void {
  setupWindowHandlers()
  setupSystemHandlers()
  setupFileHandlers()
  setupClipboardHandlers()
  setupBackendHandlers(backendUrl)
}
