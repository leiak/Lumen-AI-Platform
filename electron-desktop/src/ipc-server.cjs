// electron-desktop/src/ipc-server.cjs
// 简化的 IPC HTTP 服务
const http = require('http')

function startIPCServer(handlers) {
    const server = http.createServer((req, res) => {
        if (req.url === '/health') {
            res.writeHead(200)
            res.end('OK')
        } else if (req.url === '/reload' && handlers.onReload) {
            handlers.onReload()
            res.writeHead(200)
            res.end('OK')
        } else {
            res.writeHead(404)
            res.end('Not Found')
        }
    })

    server.listen(17321, () => {
        console.log('[IPC] 服务已启动，端口 17321')
    })

    server.on('error', (err) => {
        if (err.code === 'EADDRINUSE') {
            console.error('[IPC] 端口 17321 已被占用')
        } else {
            console.error('[IPC] 服务器错误:', err)
        }
    })
}

module.exports = { startIPCServer }