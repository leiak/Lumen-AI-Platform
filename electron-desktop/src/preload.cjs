// electron-desktop/src/preload.cjs
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
    // 已有:凭据
    saveCredentials:   (account, password) => ipcRenderer.send('save-credentials', account, password),
    loadCredentials:   () => ipcRenderer.invoke('load-credentials'),

    // 已有:用户登录态
    onUserLoggedIn:    (token) => ipcRenderer.send('user-logged-in', token),
    onUserLoggedOut:   () => ipcRenderer.send('user-logged-out'),

    // 新增:token 安全存储
    saveToken:         (token) => ipcRenderer.invoke('save-token', token),
    loadToken:         ()      => ipcRenderer.invoke('load-token'),
    clearToken:        ()      => ipcRenderer.invoke('clear-token'),

    // 新增:文件选择(V1 暴露但未连线)
    pickFiles:         (opts)  => ipcRenderer.invoke('pick-files', opts || {}),

    // 新增:保存文件(给 chat 消息导出 .docx 用)
    saveFile:         (opts)  => ipcRenderer.invoke('save-file', opts || {}),

    // 新增:主进程触发跳转
    // 返回 unsubscribe;务必在 useEffect 清理函数中调用,避免 StrictMode 双挂载泄漏
    onNavigate:        (cb)    => {
        const listener = (_event, targetPath) => cb(targetPath)
        ipcRenderer.on('navigate', listener)
        return () => ipcRenderer.removeListener('navigate', listener)
    },
})
