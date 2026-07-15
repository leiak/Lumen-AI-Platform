// electron-desktop/src/menu-shortcuts.cjs
// 应用菜单 + 全局快捷键
const { Menu, globalShortcut, dialog, app } = require('electron')

function buildMenu() {
    const isMac = process.platform === 'darwin'
    const template = [
        {
            label: '文件',
            submenu: [
                { label: '刷新', accelerator: 'CmdOrCtrl+R', role: 'reload' },
                { label: '强制重载', accelerator: 'CmdOrCtrl+Shift+R', role: 'forceReload' },
                { type: 'separator' },
                isMac ? { role: 'close' } : { role: 'quit' },
            ],
        },
        {
            label: '视图',
            submenu: [
                { label: '开发者工具', accelerator: 'F12', role: 'toggleDevTools' },
                { type: 'separator' },
                { label: '实际大小', accelerator: 'CmdOrCtrl+0', role: 'resetZoom' },
                { label: '放大', accelerator: 'CmdOrCtrl+=', role: 'zoomIn' },
                { label: '缩小', accelerator: 'CmdOrCtrl+-', role: 'zoomOut' },
                { type: 'separator' },
                { role: 'togglefullscreen' },
            ],
        },
        {
            label: '窗口',
            submenu: [
                { role: 'minimize' },
                ...(isMac ? [{ role: 'zoom' }] : []),
                { role: 'close' },
            ],
        },
        {
            label: '帮助',
            submenu: [
                {
                    label: '关于',
                    click: () => {
                        dialog.showMessageBox({
                            type: 'info',
                            title: '关于 AIPlatform Desktop',
                            message: `AIPlatform Desktop\n版本: ${app.getVersion()}\nElectron: ${process.versions.electron}\nNode: ${process.versions.node}`,
                            buttons: ['确定'],
                        })
                    },
                },
            ],
        },
    ]
    return Menu.buildFromTemplate(template)
}

function registerShortcuts(handlers = {}) {
    const bindings = [
        { accel: 'CommandOrControl+Shift+L', name: '显示/聚焦主窗口', handler: handlers.onShowWindow },
        { accel: 'CommandOrControl+Shift+A', name: 'agent 面板',       handler: handlers.onNavigateAgents },
        { accel: 'CommandOrControl+Shift+K', name: 'knowledge 面板',   handler: handlers.onNavigateKnowledge },
    ]

    const failed = []
    for (const { accel, name, handler } of bindings) {
        if (typeof handler !== 'function') {
            console.warn(`[Shortcuts] ${name}(${accel}) 跳过:handler 未注入`)
            continue
        }
        try {
            const ok = globalShortcut.register(accel, handler)
            if (!ok) failed.push(`${name}(${accel})`)
        } catch (e) {
            failed.push(`${name}(${accel}): ${e.message}`)
        }
    }
    if (failed.length > 0) {
        console.warn('[Shortcuts] 以下快捷键注册失败:', failed.join('; '))
    }

    return () => globalShortcut.unregisterAll()
}

module.exports = { buildMenu, registerShortcuts }
