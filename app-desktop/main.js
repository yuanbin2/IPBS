const { app, BrowserWindow } = require('electron')

console.log('app type:', typeof app)
console.log('process.type:', process.type)
console.log('electron version:', process.versions.electron)

if (app) {
  app.whenReady().then(() => {
    const win = new BrowserWindow({ width: 800, height: 600 })
    win.loadURL('https://www.baidu.com')
    console.log('Window created!')
  })
} else {
  console.log('ERROR: app is undefined')
  app.quit()
}