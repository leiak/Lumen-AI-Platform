// electron-desktop/src/notifications.cjs
// 托盘 + 桌面通知 + 未读计数 + 1 秒节流
const { Tray, Menu, Notification, nativeImage, app } = require('electron')

let tray = null
let mainWindow = null
let unreadCount = 0
let trayClickHandler = () => {}
let flushTimer = null
let pendingNotifications = new Map()  // event_type -> { title, body, count }

function create(window) {
    mainWindow = window

    // 尝试创建托盘(Linux 某些环境可能失败)
    try {
        const icon = nativeImage.createEmpty()  // V1 占位,后续可换 PNG
        tray = new Tray(icon)
        tray.setToolTip('AIPlatform Desktop')
        rebuildTrayMenu()
        tray.on('click', () => trayClickHandler())
        tray.on('double-click', () => trayClickHandler())
    } catch (e) {
        console.error('[Notifications] Tray 创建失败(降级为 no-op):', e.message)
        tray = null
    }
}

function rebuildTrayMenu() {
    if (!tray) return
    const menu = Menu.buildFromTemplate([
        { label: '显示主窗口', click: () => trayClickHandler() },
        { type: 'separator' },
        { label: `未读 ${unreadCount}`, enabled: false },
        { label: '清空未读', click: () => setUnreadCount(0) },
        { type: 'separator' },
        { label: '退出', click: () => { app.quit() } },
    ])
    tray.setContextMenu(menu)
}

function showNotification(title, body, onClick) {
    if (!Notification.isSupported()) {
        console.warn('[Notifications] 系统不支持原生通知')
        return
    }
    const n = new Notification({ title, body, silent: false })
    n.on('click', () => {
        if (typeof onClick === 'function') onClick()
        else if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore()
            mainWindow.show()
            mainWindow.focus()
        }
    })
    n.show()
}

function setUnreadCount(n) {
    unreadCount = Math.max(0, n | 0)
    if (tray) {
        tray.setToolTip(`AIPlatform Desktop · 未读 ${unreadCount}`)
        rebuildTrayMenu()
    }
    // macOS dock badge
    if (process.platform === 'darwin' && app.dock) {
        app.dock.setBadge(unreadCount > 0 ? String(unreadCount) : '')
    }
}

function getUnreadCount() {
    return unreadCount
}

function onTrayClick(cb) {
    trayClickHandler = cb
}

// 1 秒节流:同 type 在 1 秒内的多次调用合并为 1 条
// 保留首次调用的 title/body(在 flush 时使用)
// 未读数按累计 count 增加(每条消息 +1)
function throttledNotify(eventType, title, body) {
    // 如果已有 pending 条目,累加并推迟 flush
    if (pendingNotifications.has(eventType)) {
        const entry = pendingNotifications.get(eventType)
        entry.count = (entry.count || 0) + 1
        // 重新排 flush 定时器(若已存在)
        if (flushTimer) clearTimeout(flushTimer)
        flushTimer = setTimeout(flushPending, 1000)
        return
    }

    // 首次进入节流窗口:保留 title/body,排 flush
    pendingNotifications.set(eventType, { title, body, count: 1 })
    if (flushTimer) clearTimeout(flushTimer)
    flushTimer = setTimeout(flushPending, 1000)
}

function flushPending() {
    flushTimer = null
    if (pendingNotifications.size === 0) return
    for (const [type, entry] of pendingNotifications) {
        const { title, body, count } = entry
        const finalTitle = count > 1 ? `你有 ${count} 条新消息` : title
        showNotification(finalTitle, body)
        setUnreadCount(getUnreadCount() + count)  // 每条 +1,不是每批 +1
    }
    pendingNotifications.clear()
}

function destroy() {
    if (flushTimer) {
        clearTimeout(flushTimer)
        flushTimer = null
    }
    if (tray) {
        tray.destroy()
        tray = null
    }
    pendingNotifications.clear()
}

module.exports = {
    create,
    showNotification,
    throttledNotify,
    setUnreadCount,
    getUnreadCount,
    onTrayClick,
    destroy,
}
