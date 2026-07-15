// electron-desktop/src/remote-tool-client.cjs
// Electron Desktop Remote Tool Client - WebSocket communication with backend

const WebSocket = require('ws')

let ws = null
let reconnectTimer = null
let currentToken = null
let connectionId = null

const MAX_RECONNECT_ATTEMPTS = 10
const BASE_RECONNECT_DELAY = 1000
let reconnectAttempts = 0

// Message handlers
const messageHandlers = new Map()
// Pending requests
const pendingRequests = new Map()

function generateId() {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

function connect(token) {
    currentToken = token
    const wsURL = process.env.WS_URL || 'ws://localhost:11335/api/v1/ws/electron'

    ws = new WebSocket(wsURL, {
        headers: { 'Authorization': `Bearer ${token}` }
    })

    ws.on('open', () => {
        console.log('[WebSocket] Connection established')
        reconnectAttempts = 0
        if (reconnectTimer) {
            clearTimeout(reconnectTimer)
            reconnectTimer = null
        }
    })

    ws.on('message', (data) => {
        try {
            const msg = JSON.parse(data)
            console.log('[WebSocket] Received:', msg.type || msg.id)

            // Handle connection established message
            if (msg.type === 'connection_established') {
                connectionId = msg.connection_id
                console.log('[WebSocket] Connection ID:', connectionId)
            }

            // Handle response to a request
            if (msg.id) {
                const pending = pendingRequests.get(msg.id)
                if (pending) {
                    pendingRequests.delete(msg.id)
                    if (pending.timeout) {
                        clearTimeout(pending.timeout)
                    }
                    pending.resolve(msg)
                }
            }

            // Handle broadcast messages
            if (msg.type === 'broadcast') {
                broadcastToHandlers('broadcast', msg)
            }

            // Handle errors
            if (msg.type === 'error' || msg.error) {
                console.error('[WebSocket] Error:', msg.error || msg.message)
            }

            // Call registered handlers
            const handler = messageHandlers.get(msg.type || msg.action)
            if (handler) {
                handler(msg)
            }

        } catch (e) {
            console.error('[WebSocket] Failed to parse message:', e)
        }
    })

    ws.on('close', (code, reason) => {
        console.log('[WebSocket] Connection closed:', code, reason?.toString())
        connectionId = null

        // Auto-reconnect with backoff
        if (currentToken && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttempts), 30000)
            reconnectAttempts++
            console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`)
            reconnectTimer = setTimeout(() => {
                connect(currentToken)
            }, delay)
        }
    })

    ws.on('error', (error) => {
        console.error('[WebSocket] Error:', error.message)
    })
}

function disconnect() {
    currentToken = null
    connectionId = null
    reconnectAttempts = MAX_RECONNECT_ATTEMPTS // Prevent reconnection

    if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
    }

    if (ws) {
        ws.close(1000, 'Client disconnecting')
        ws = null
    }

    // Clear pending requests
    for (const [id, pending] of pendingRequests) {
        clearTimeout(pending.timeout)
        pending.reject(new Error('Disconnected'))
    }
    pendingRequests.clear()
}

async function sendMessage(action, params = {}, timeout = 30000) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        throw new Error('WebSocket not connected')
    }

    const id = generateId()

    const message = {
        id,
        action,
        params: {
            ...params,
            connection_id: connectionId
        }
    }

    console.log('[WebSocket] Sending:', action, id)

    return new Promise((resolve, reject) => {
        // Set timeout
        const timeoutHandle = setTimeout(() => {
            pendingRequests.delete(id)
            reject(new Error(`Request ${id} timed out after ${timeout}ms`))
        }, timeout)

        pendingRequests.set(id, { resolve, reject, timeout: timeoutHandle })

        ws.send(JSON.stringify(message))
    })
}

// Convenience methods
async function executeCommand(command, cwd = null, timeout = 30000) {
    return sendMessage('execute', { command, cwd }, timeout)
}

async function readFile(path, encoding = 'utf-8') {
    return sendMessage('read_file', { path, encoding })
}

async function writeFile(path, content, encoding = 'utf-8') {
    return sendMessage('write_file', { path, content, encoding })
}

async function listDir(path = '.', maxItems = 1000) {
    return sendMessage('list_dir', { path, max_items: maxItems })
}

async function toolCall(toolName, params = {}) {
    return sendMessage('tool_call', { tool_name: toolName, params })
}

async function healthCheck() {
    return sendMessage('health', {})
}

async function getStatus() {
    return sendMessage('status', {})
}

// Handler registration
function onMessage(type, handler) {
    messageHandlers.set(type, handler)
}

function onBroadcast(handler) {
    messageHandlers.set('broadcast', handler)
}

function broadcastToHandlers(type, msg) {
    const handler = messageHandlers.get(type)
    if (handler) {
        handler(msg)
    }
}

// Connection state
function isConnected() {
    return ws !== null && ws.readyState === WebSocket.OPEN
}

function getConnectionId() {
    return connectionId
}

module.exports = {
    connect,
    disconnect,
    sendMessage,
    executeCommand,
    readFile,
    writeFile,
    listDir,
    toolCall,
    healthCheck,
    getStatus,
    onMessage,
    onBroadcast,
    isConnected,
    getConnectionId
}
