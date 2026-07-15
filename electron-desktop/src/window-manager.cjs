// electron-desktop/src/window-manager.cjs
const { BrowserWindow } = require('electron')
const path = require('path')

let mainWindow = null

function createMainWindow() {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        webPreferences: {
            preload: path.join(__dirname, 'preload.cjs'),
            contextIsolation: true,
            nodeIntegration: false,
        },
    })

    // 加载前端 URL
    const frontendURL = process.env.FRONTEND_URL || 'http://localhost:11334'
    mainWindow.loadURL(frontendURL)

    mainWindow.on('closed', () => {
        mainWindow = null
    })

    return mainWindow
}

function reloadMainWindow() {
    if (mainWindow) {
        mainWindow.reload()
    }
}

function focusMainWindow() {
    if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore()
        mainWindow.focus()
    }
}

module.exports = {
    createMainWindow,
    reloadMainWindow,
    focusMainWindow,
}