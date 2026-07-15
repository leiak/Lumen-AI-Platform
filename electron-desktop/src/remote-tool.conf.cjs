// electron-desktop/src/remote-tool.conf.cjs
module.exports = {
    enabled: true,
    serverURL: process.env.WS_URL || 'ws://localhost:11335/api/v1/ws/electron',
}
