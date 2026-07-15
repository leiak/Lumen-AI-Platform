// electron-desktop/src/event-router.cjs
// WS 事件白名单路由
const EVENTS = Object.freeze({
    WORKFLOW_RUN_COMPLETED: 'workflow_run_completed',
    CHAT_MESSAGE_RECEIVED:  'chat_message_received',
    KNOWLEDGE_PARSE_DONE:   'knowledge_parse_completed',
})

// 路由表:[event_type, payload -> {title, body}, shouldNotify]
const ROUTES = [
    [
        EVENTS.WORKFLOW_RUN_COMPLETED,
        (p) => ({
            title: '工作流完成',
            body:  `${String(p.workflow_name ?? '未知')} #${String(p.run_id ?? '?')} → ${String(p.status ?? '未知')}`,
        }),
        true,
    ],
    [
        EVENTS.CHAT_MESSAGE_RECEIVED,
        (p) => ({
            title: `新消息 · ${String(p.conversation_title ?? '对话')}`,
            body:  String(p.preview ?? '点击查看'),
        }),
        true,
    ],
    [
        EVENTS.KNOWLEDGE_PARSE_DONE,
        (p) => ({
            title: '知识库解析',
            body:  `${String(p.filename ?? '文件')} → ${String(p.status ?? '未知')}`,
        }),
        // 仅失败时通知,成功静默
        (p) => p.status === 'failed',
    ],
]

let externalHandlers = new Map()  // event_type -> [handler, ...]

function init({ onMessage, showNotification, setUnreadCount, getCurrentUnread }) {
    if (typeof onMessage !== 'function') {
        throw new Error('event-router.init: onMessage is required')
    }

    for (const [eventType, payloadToNotif, shouldNotify] of ROUTES) {
        onMessage(eventType, (msg) => {
            // 后端把 payload 放在 msg.payload(msg 整体是 {type, event, payload, ...})
            const payload = msg.payload || {}
            const notify = typeof shouldNotify === 'function' ? shouldNotify(payload) : shouldNotify
            if (!notify) return
            const { title, body } = payloadToNotif(payload)
            showNotification(title, body)
            // 未读 +1(简单策略:每次通知 +1;调用方可用 setUnreadCount(0) 重置)
            if (typeof setUnreadCount === 'function') {
                const current = typeof getCurrentUnread === 'function' ? getCurrentUnread() : 0
                setUnreadCount(current + 1)
            }
        })
    }
}

function on(eventType, handler) {
    if (!externalHandlers.has(eventType)) externalHandlers.set(eventType, [])
    externalHandlers.get(eventType).push(handler)
}

module.exports = {
    EVENTS,
    ROUTES,
    init,
    on,
}
