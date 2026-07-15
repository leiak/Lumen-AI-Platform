// electron-desktop/src/main.cjs
const { app, Menu, ipcMain, safeStorage, dialog } = require('electron')
const path = require('path')
const fs = require('fs')
const fsPromises = require('fs/promises')
const { startIPCServer } = require('./ipc-server.cjs')
const { createMainWindow, reloadMainWindow, focusMainWindow } = require('./window-manager.cjs')
const {
    connect: connectRemoteTool,
    disconnect: disconnectRemoteTool,
    onMessage,
} = require('./remote-tool-client.cjs')
const notifications = require('./notifications.cjs')
const eventRouter = require('./event-router.cjs')
const { buildMenu, registerShortcuts } = require('./menu-shortcuts.cjs')

// 单实例锁
const gotTheLock = app.requestSingleInstanceLock()
let mainWindow = null
let unregisterShortcuts = () => {}

if (!gotTheLock) {
    console.log('[主进程] 已有实例运行中,退出当前进程')
    app.quit()
} else {
    app.on('second-instance', () => {
        console.log('[主进程] 检测到第二个实例启动,聚焦已有窗口')
        focusMainWindow()
    })

    app.whenReady().then(() => {
        // 1. 应用菜单(替代 setApplicationMenu(null))
        Menu.setApplicationMenu(buildMenu())

        // 2. 主窗口
        mainWindow = createMainWindow()

        // 3. 托盘 + 通知
        notifications.create(mainWindow)
        notifications.onTrayClick(() => {
            if (!mainWindow) return
            if (mainWindow.isMinimized()) mainWindow.restore()
            if (!mainWindow.isVisible()) mainWindow.show()
            mainWindow.focus()
        })

        // 4. WS 事件路由
        eventRouter.init({
            onMessage,
            showNotification: (title, body, onClick) =>
                notifications.throttledNotify('generic', title, body),
            setUnreadCount: notifications.setUnreadCount,
            getCurrentUnread: notifications.getUnreadCount,
        })

        // 5. 全局快捷键
        unregisterShortcuts = registerShortcuts({
            onShowWindow: () => {
                if (!mainWindow) return
                if (mainWindow.isMinimized()) mainWindow.restore()
                mainWindow.show()
                mainWindow.focus()
            },
            onNavigateAgents:    () => navigateInRenderer('/dashboard/agents'),
            onNavigateKnowledge: () => navigateInRenderer('/dashboard/knowledge'),
        })

        // 6. 本地 IPC HTTP(健康/重载)
        startIPCServer({
            onReload: () => {
                reloadMainWindow()
            },
        })

        // 7. 凭据存取 IPC(保留旧)
        ipcMain.on('save-credentials', (_event, account, password) => {
            saveCredentials(account, password)
        })
        ipcMain.handle('load-credentials', async () => {
            return loadCredentials()
        })

        // 8. 新增 IPC:token 安全存储
        ipcMain.handle('save-token', async (_e, token) => {
            try {
                if (!safeStorage.isEncryptionAvailable()) {
                    console.warn('[Token] safeStorage 不可用,降级跳过')
                    return { ok: false, reason: 'unavailable' }
                }
                const filePath = getTokenPath()
                const encrypted = safeStorage.encryptString(token)
                // NOTE: 0o600 is honored on Linux/macOS but silently ignored on Windows
                // (Windows uses ACLs; consider explicit ACL helper in V2 if multi-user Windows is in scope)
                fs.writeFileSync(filePath, encrypted, { mode: 0o600 })
                return { ok: true }
            } catch (e) {
                console.error('[Token] save-token 失败:', e.message)
                return { ok: false, reason: e.message }
            }
        })

        ipcMain.handle('load-token', async () => {
            try {
                const filePath = getTokenPath()
                if (!fs.existsSync(filePath)) return null
                if (!safeStorage.isEncryptionAvailable()) {
                    console.warn('[Token] safeStorage 不可用,降级到 localStorage')
                    return null
                }
                const encrypted = fs.readFileSync(filePath)
                return safeStorage.decryptString(encrypted)
            } catch (e) {
                console.error('[Token] load-token 失败,删除损坏文件:', e.message)
                try { fs.unlinkSync(getTokenPath()) } catch {}
                return null
            }
        })

        ipcMain.handle('clear-token', async () => {
            try {
                const filePath = getTokenPath()
                if (fs.existsSync(filePath)) fs.unlinkSync(filePath)
                notifications.setUnreadCount(0)
                return { ok: true }
            } catch (e) {
                console.error('[Token] clear-token 失败:', e.message)
                return { ok: false, reason: e.message }
            }
        })

        // 9. 新增 IPC:pick-files(走法 B:V1 暂不连线,通道暴露)
        ipcMain.handle('pick-files', async (_e, opts = {}) => {
            try {
                const result = await dialog.showOpenDialog(mainWindow, {
                    properties: ['openFile', ...(opts.multiSelections ? ['multiSelections'] : [])],
                    filters: opts.filters || [],
                })
                return result.canceled ? [] : result.filePaths
            } catch (e) {
                console.error('[PickFiles] 失败:', e.message)
                return []
            }
        })

        // 9b. 新增 IPC:save-file(把渲染进程生成的 .docx buffer 写到用户选的路径)
        ipcMain.handle('save-file', async (_e, opts = {}) => {
            const { defaultName, filters, buffer } = opts
            if (!defaultName || !Array.isArray(buffer)) {
                return { ok: false, error: 'defaultName and buffer are required' }
            }
            try {
                const result = await dialog.showSaveDialog(mainWindow, {
                    defaultPath: defaultName,
                    filters: filters || [],
                })
                if (result.canceled || !result.filePath) {
                    return { ok: false, canceled: true }
                }
                // ``buffer`` arrives as a plain number[] over IPC.
                // Wrap in Uint8Array first, then build a Node Buffer
                // so fs.writeFile writes the raw bytes, not a JSON
                // stringification of the array.
                await fsPromises.writeFile(result.filePath, Buffer.from(Uint8Array.from(buffer)))
                return { ok: true, path: result.filePath }
            } catch (e) {
                console.error('[SaveFile] 失败:', e.message)
                return { ok: false, error: e.message }
            }
        })

        // 10. 远程工具连接(已有)
        ipcMain.on('user-logged-in', (_event, token) => {
            console.log('[主进程] 收到用户登录通知,启动远程工具连接')
            connectRemoteTool(token)
        })
        ipcMain.on('user-logged-out', () => {
            console.log('[主进程] 收到用户登出通知,断开远程工具连接')
            disconnectRemoteTool()
            notifications.setUnreadCount(0)
        })
    })

    app.on('before-quit', () => {
        unregisterShortcuts()
        disconnectRemoteTool()
        notifications.destroy()
    })

    app.on('activate', () => {
        const { BrowserWindow } = require('electron')
        if (BrowserWindow.getAllWindows().length === 0) {
            mainWindow = createMainWindow()
        }
    })

    app.on('window-all-closed', () => {
        if (process.platform !== 'darwin') {
            app.quit()
        }
    })
}

// 渲染层跳转
function navigateInRenderer(targetPath) {
    if (mainWindow && mainWindow.webContents) {
        mainWindow.webContents.send('navigate', targetPath)
    }
}

// 凭据存取(保留旧实现)
function getCredentialsPath() {
    return path.join(app.getPath('userData'), 'credentials.json')
}

function saveCredentials(account, password) {
    try {
        const filePath = getCredentialsPath()
        const encrypted = safeStorage.isEncryptionAvailable()
            ? safeStorage.encryptString(password).toString('base64')
            : Buffer.from(password).toString('base64')
        fs.writeFileSync(filePath, JSON.stringify({ account, password: encrypted, encrypted: safeStorage.isEncryptionAvailable() }), 'utf-8')
    } catch (e) {
        console.error('[主进程] 保存凭据失败:', e.message)
    }
}

function loadCredentials() {
    try {
        const filePath = getCredentialsPath()
        if (!fs.existsSync(filePath)) return null
        const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'))
        const password = data.encrypted && safeStorage.isEncryptionAvailable()
            ? safeStorage.decryptString(Buffer.from(data.password, 'base64'))
            : Buffer.from(data.password, 'base64').toString('utf-8')
        return { account: data.account, password }
    } catch (e) {
        console.error('[主进程] 读取凭据失败:', e.message)
        return null
    }
}

// 新增:token 文件路径
function getTokenPath() {
    return path.join(app.getPath('userData'), 'token.bin')
}
