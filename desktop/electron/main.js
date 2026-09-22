const { app, BrowserWindow, shell, Menu, Tray, nativeImage, ipcMain } = require('electron')
const path = require('path')
const { setupAllHandlers } = require('./ipc-handlers')

let mainWindow = null
let tray = null

// Backend configuration
const BACKEND_PORT = 8000
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`

// Check if in development mode
const isDev = !app.isPackaged

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    show: false,
    frame: false,
    titleBarStyle: 'hidden',
    backgroundColor: '#17262e',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    if (mainWindow) {
      mainWindow.show()
      mainWindow.focus()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // Open external links in browser
  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  // Load app
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
  }
}

function createTray() {
  // Create a simple tray icon programmatically
  const icon = nativeImage.createEmpty()
  tray = new Tray(icon)

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        if (mainWindow) {
          mainWindow.show()
          mainWindow.focus()
        }
      }
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        app.quit()
      }
    }
  ])

  tray.setToolTip('Knowledge Agent Platform')
  tray.setContextMenu(contextMenu)

  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

async function startBackend() {
  // For now, we'll connect to external backend
  console.log(`Connecting to backend at ${BACKEND_URL}`)
}

// App lifecycle
app.whenReady().then(async () => {
  // Setup all IPC handlers
  setupAllHandlers(BACKEND_URL)

  await startBackend()
  createWindow()

  // Create tray only if icon exists
  try {
    createTray()
  } catch (e) {
    console.log('Tray creation skipped:', e.message)
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
