// electron-desktop/test/smoke.cjs
// 烟测:验证 3 个新模块可加载、路由表完整、菜单不空
// 注意:plain node 跑这个脚本;`require('electron')` 在 node 进程里返回的是 electron.exe
// 路径字符串(不是 API),所以需要一个最小 mock 让 menu-shortcuts.cjs 在 node 里能加载。
// 真实运行仍由 electron 进程负责,见 `npm start`。
const Module = require('module')
const electronStub = {
    Menu: {
        buildFromTemplate: (template) => ({ items: template }),
    },
    globalShortcut: {
        register: () => true,
        unregisterAll: () => {},
    },
    dialog: {
        showMessageBox: () => Promise.resolve(),
    },
    app: {
        getVersion: () => '0.0.0-test',
    },
}
const originalResolve = Module._resolveFilename
Module._resolveFilename = function (request, ...rest) {
    if (request === 'electron') return 'electron-stub'
    return originalResolve.call(this, request, ...rest)
}
const originalLoad = Module._load
Module._load = function (request, ...rest) {
    if (request === 'electron') return electronStub
    return originalLoad.call(this, request, ...rest)
}

const assert = require('assert')
const path = require('path')

const SRC = path.join(__dirname, '..', 'src')

console.log('[Smoke] 加载新模块...')
assert.doesNotThrow(() => require(path.join(SRC, 'notifications.cjs')),    'notifications.cjs 加载失败')
assert.doesNotThrow(() => require(path.join(SRC, 'event-router.cjs')),      'event-router.cjs 加载失败')
assert.doesNotThrow(() => require(path.join(SRC, 'menu-shortcuts.cjs')),    'menu-shortcuts.cjs 加载失败')

console.log('[Smoke] 检查路由表...')
const eventRouter = require(path.join(SRC, 'event-router.cjs'))
assert.ok(Array.isArray(eventRouter.ROUTES),                    'ROUTES 必须是数组')
assert.ok(eventRouter.ROUTES.length >= 3,                       `期望至少 3 条路由,实际 ${eventRouter.ROUTES.length}`)
const types = new Set(eventRouter.ROUTES.map(r => r[0]))
assert.ok(types.has('workflow_run_completed'),                  '缺少 workflow_run_completed 路由')
assert.ok(types.has('chat_message_received'),                   '缺少 chat_message_received 路由')
assert.ok(types.has('knowledge_parse_completed'),               '缺少 knowledge_parse_completed 路由')

console.log('[Smoke] 验证未读计数累加...')
// 用假 onMessage 模拟 3 次 chat 事件
let fakeSetCalls = 0
let fakeGetReturns = [0, 1, 2]
let fakeGetIdx = 0
let capturedShowCount = 0
const fakeOnMessage = (type, handler) => {
    if (type === 'chat_message_received') {
        for (let i = 0; i < 3; i++) {
            handler({ payload: { conversation_title: 't', preview: 'p' } })
        }
    }
}
eventRouter.init({
    onMessage: fakeOnMessage,
    showNotification: () => { capturedShowCount++ },
    setUnreadCount: (n) => { fakeSetCalls++ },
    getCurrentUnread: () => fakeGetReturns[fakeGetIdx++],
})
assert.strictEqual(capturedShowCount, 3, `期望 3 次通知,实际 ${capturedShowCount}`)
// 关键:如果 getCurrentUnread 不在闭包内,getUnreadCount 永远是 0,setUnreadCount 永远收到 1(累加失效)
// 上面 fakeGetReturns=[0,1,2] + fakeGetIdx 自增,getCurrentUnread() 返回 0, 1, 2,对应累加成 1, 2, 3
// fakeGetIdx === 3 是最严格的断言:闭包内确实传了 getCurrentUnread,且每次事件都调用一次
assert.strictEqual(fakeGetIdx, 3, `getCurrentUnread 应被调用 3 次(每次事件 +1),实际 ${fakeGetIdx} —— 0 表示闭包内未传参`)
assert.ok(fakeSetCalls >= 3, `期望 setUnreadCount 至少被调用 3 次,实际 ${fakeSetCalls}`)

console.log('[Smoke] 检查事件常量...')
assert.strictEqual(eventRouter.EVENTS.WORKFLOW_RUN_COMPLETED, 'workflow_run_completed')

console.log('[Smoke] 检查菜单构建...')
const { buildMenu } = require(path.join(SRC, 'menu-shortcuts.cjs'))
const menu = buildMenu()
assert.ok(menu && Array.isArray(menu.items) && menu.items.length > 0, '菜单为空')
const labels = menu.items.map(i => i.label)
assert.ok(labels.includes('文件'),                                '缺少「文件」菜单')
assert.ok(labels.includes('视图'),                                '缺少「视图」菜单')
assert.ok(labels.includes('帮助'),                                '缺少「帮助」菜单')

console.log('[Smoke] 验证 remote-tool.conf 端口已修正...')
const conf = require(path.join(SRC, 'remote-tool.conf.cjs'))
assert.ok(conf.serverURL.includes('11335'),                       `期望端口 11335,实际 ${conf.serverURL}`)

console.log('[Smoke] ALL PASSED ✓')
