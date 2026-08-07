# 模块:MCP 协议

> Lumen AI Platform 的 MCP(Model Context Protocol)协议集成。
> 文档讲透 MCP 是什么、怎么用、跟 Lumen 怎么集成。

---

## 1. 产品定位

**MCP 是什么?**
- Anthropic 提出的"AI ↔ 工具"标准协议
- 跟 USB-C 一样: 标准化 AI 用工具的方式
- Lumen 同时是 **MCP Client** 和 **MCP Server**

**为什么 Lumen 支持 MCP?**
- 接外部工具(用户的 ERP / 飞书 / GitHub)
- 不用每个工具都重写
- 跟 Coze / Dify 等生态互通

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| MCP Server 注册 | 配置外部 MCP server |
| 工具发现 | 拉 MCP server 工具列表 |
| 工具执行 | JSON-RPC over HTTP/WS |
| Marketplace | 浏览/装 MCP server |
| 本地 demo | 自研 demo(6 工具) |
| 远程工具 | 供 Electron 调用 |

---

## 3. 数据模型

### 3.1 mcp_servers
```python
class MCPServer(Base):
    id: int
    name: str
    description: str
    transport: str                # stdio / http / ws
    endpoint: str                # URL
    command: str                 # stdio 启动命令
    args: list
    env: dict
    is_active: bool
    tenant_id: int
```

### 3.2 mcp_tools
```python
class MCPTool(Base):
    id: int
    server_id: int
    name: str
    description: str
    input_schema: dict
    cached_at: datetime
```

### 3.3 文件
- ORM: `backend/lumen_models/mcp.py`
- Schema: `backend/lumen_schemas/mcp.py`
- 服务: `backend/lumen_services/mcp_service.py`
- 客户端: `backend/lumen_tools/mcp_client.py`
- 路由: `backend/lumen_api/v1/mcp.py`
- 本地 demo: `backend/lumen_mcp_servers/local_demo_server.py`

---

## 4. UI

### 4.1 列表
- 路径: `frontend/app/dashboard/mcp/page.tsx`
- 表格:名字 / 协议 / 端点 / 状态 / 工具数 / 操作
- 操作:测试 / 启停 / 删

### 4.2 创建
- 表单:名字 / 描述 / 传输协议 / 端点 / 命令(选 stdio)
- 保存 → 自动拉工具列表 → 缓存

### 4.3 工具测试
- 点"测试" → 选 tool → 填入参 → 调
- 展示响应

---

## 5. 关键能力详解

### 5.1 3 种传输协议
- **stdio**: 本地进程(stdin/stdout 通信)
- **http**: HTTP + JSON-RPC 2.0
- **ws**: WebSocket + JSON-RPC 2.0

### 5.2 工具发现
- 调 `tools/list` JSON-RPC 方法
- 缓存到 `mcp_tools` 表
- 24 小时刷新一次(可配)

### 5.3 工具执行
- 调 `tools/call` JSON-RPC 方法
- 入参 + 上下文
- 返回: `[{type: "text", text: "..."}]`

### 5.4 与 Lumen Agent 集成
- Agent 的 `allowed_tools` 加 `<server_name>__<tool_name>`
- 工具名格式: `mcp_<server>_<tool>`

---

## 6. 本地 demo server

### 6.1 用途
- 测试 MCP 协议
- 演示用
- 6 个工具

### 6.2 启动
```bash
cd backend
python run_mcp_server.py
# → 127.0.0.1:8765
```

### 6.3 6 个工具
1. `get_current_time` — 返回当前时间
2. `echo` — 回显输入
3. `calculate` — 简单数学
4. `random_number` — 随机数
5. `query_database` — 查 dev DB
6. `get_weather` — mock 天气

### 6.4 文件
- `backend/lumen_mcp_servers/local_demo_server.py`
- 端口: 8765(硬编码,见 [port-alloc](../architecture/06-port-alloc.md))

---

## 7. 远程工具(供 Electron)

### 7.1 场景
- 桌面端需要执行"本地工具"(打开文件、调本地程序)
- 但 Lumen 后端是远程,不能直接执行
- 解决方案: 桌面端作为 MCP server,后端通过 WS 调

### 7.2 流程
```
后端 Agent 决定调远程工具
   │
   ▼
后端通过 WS 推到桌面端
   │
   ▼
桌面端执行(主进程,不在 renderer 沙箱)
   │
   ▼
返回结果到后端
```

详见 [electron-desktop](../architecture/02-module-topology.md#electron-桌面端) 和 `electron-desktop/src/remote-tool-client.cjs`。

---

## 8. Marketplace

### 8.1 平台预置
- `seed_mcp_servers` 装 5 个示例 server
- 公开 / 免费

### 8.2 租户私有
- 租户自己注册的
- 私有不分享

### 8.3 跨租户(计划中)
- 公共 marketplace
- 订阅 / 计费

---

## 9. 关键代码

### 9.1 客户端
```python
# backend/lumen_tools/mcp_client.py
class MCPClient:
    def __init__(self, server: MCPServer):
        self.server = server
        self.transport = build_transport(server)  # stdio/http/ws

    async def list_tools(self) -> list[MCPTool]:
        response = await self.transport.request("tools/list", {})
        return [parse_tool(t) for t in response["tools"]]

    async def call_tool(self, name: str, args: dict) -> list[dict]:
        response = await self.transport.request("tools/call", {
            "name": name,
            "arguments": args,
        })
        return response["content"]
```

### 9.2 集成到 Agent
```python
# backend/lumen_services/agent_service.py
async def load_agent_tools(agent, current_user, tenant_id):
    tools = []

    for name in agent.allowed_tools or []:
        if name.startswith("mcp_"):
            server_id, tool_name = parse_mcp_name(name)
            server = get_mcp_server(server_id, tenant_id)
            client = MCPClient(server)
            tools.append(MCPToolAdapter(client, tool_name))
        else:
            tools.append(BUILTIN_TOOLS[name])

    return tools
```

---

## 10. 边界与不做

### 10.1 当前
- ✅ stdio / http / ws 三协议
- ✅ 工具发现 + 缓存
- ✅ 工具执行
- ✅ 本地 demo
- ✅ 远程工具(供 Electron)
- ✅ 平台预置

### 10.2 不做
- ❌ MCP Server Marketplace(计划中)
- ❌ 跨租户分享
- ❌ MCP 鉴权(只配白名单)

---

## 11. 升级路径

### 短期
- 📋 工具执行失败重试
- 📋 工具调用限流

### 中期
- 📋 MCP Marketplace
- 📋 MCP Server 沙箱

### 长期
- 📋 MCP 联邦(跨实例)
- 📋 MCP 商业市场

---

## 12. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| MCP 连不上 | 端点错 / 服务挂 | 测端点 |
| 工具发现失败 | JSON-RPC 版本错 | 调协议 |
| 工具调用 401 | MCP server 鉴权 | 改 MCP server 配置 |
| 工具调用 timeout | server 慢 | 调 timeout |
| 桌面端 WS 断 | 网络 | 重连 |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
