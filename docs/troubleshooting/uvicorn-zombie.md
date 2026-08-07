# 排错:Uvicorn 僵尸进程(Windows 专属)

> Windows 上 `uvicorn --reload` 最坑的一个问题。
> 症状隐蔽、误判率高,专门开一篇。

---

## 1. 一句话

**Windows 上 `uvicorn --reload` 会静默失败不重启 worker。代码改了但没生效,接口返回旧行为或空数据,日志里没有任何报错。**

---

## 2. 为什么会这样

`uvicorn --reload` 的进程结构是**两层**:

```
reloader 进程 (PID_A)              ← 你在终端看到的那个
   └── worker 进程 (PID_B)         ← 真正 serve HTTP 的那个
       (multiprocessing.spawn 派生)
```

- **Linux/macOS**:reloader 检测到文件变化 → SIGTERM worker → worker 干净退出 → 派新 worker。
- **Windows**:没有真正的 SIGTERM。reloader 用 `TerminateProcess` 或干脆放弃。worker 可能:
  - 卡在 socket accept 上不响应
  - 已经"死"了但句柄还持有端口
  - 继续用**旧代码**服务请求

**结果**:端口还在 LISTENING,`/docs` 还能打开,但**跑的是几十分钟前的代码**。

---

## 3. 典型症状(按迷惑程度排序)

| 症状 | 你的第一反应(通常是错的) | 真相 |
|------|--------------------------|------|
| 新写的接口返 **404 / 405** | "路由没注册对" | worker 没加载新代码 |
| 列表接口返 **`[]`** 空数组 | "数据库没数据" | 缓存的 ES client 挂了 → 异常 → fallback 返空 |
| 检索返回空 | "embedding 模型没起来" | 陈旧 worker 里 Ollama client 被限流 |
| 改了 schema 但响应没变 | "Pydantic 缓存" | worker 是旧的 |
| 启动卡在 `Waiting for application startup.` | "DB 连不上" | 见 §6 MySQL MDL 孤儿连接 |

---

## 4. 诊断三步

### 步骤 1:OpenAPI 是最快的判据

**核心思路**:如果你新加的路由**在 `/openapi.json` 里根本不存在**,那就是 worker 没加载新代码 —— 100% 是 zombie,不用再猜别的。

```bash
curl -s http://localhost:11335/openapi.json \
  | python -c "import sys,json; d=json.load(sys.stdin); [print(' ',m,p) for p in d['paths'] if 'models' in p.lower() for m in d['paths'][p]]"
```

把 `'models'` 换成你要查的路径关键字。

> **实战案例(2026-06-06)**:M13 合并后 `POST /models/import-from-ollama` 返 405。
> 查 openapi.json → 这条路由**完全不存在** → 确诊 zombie,不是路由写错。

### 步骤 2:看谁在占端口

```bash
netstat -ano | grep :11335 | grep LISTENING
```

拿到 PID 后**必须验证进程真的存在**:

```powershell
Get-Process -Id <pid>
```

- 进程不存在 → netstat 状态过期,真凶是别的 PID,重查。
- 进程存在 → 进步骤 3。

### 步骤 3:确认它是不是 worker

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId=<pid>" | Select CommandLine
```

命令行里看到 **`--multiprocessing-fork`** + **`parent_pid=<reloader_pid>`** → 这就是 worker。

---

## 5. 处理方案

### 方案 A(推荐):杀 worker,不是杀 reloader

**关键点:杀 reloader 不顶用。**

worker 是用 `spawn_main` 启动的,它**继承了 socket 句柄**。杀掉 reloader 后,worker 会接管端口继续 serve —— `netstat` 仍 LISTENING、`curl /docs` 仍 200,等于没杀。

```powershell
# 优先不带 -Force,走 SIGTERM-equivalent,让 SQLAlchemy 连接池干净关闭
powershell -NoProfile -Command "Stop-Process -Id <worker_pid>"

# 失败再强杀(会留 MySQL 孤儿连接,见 §6)
powershell -NoProfile -Command "Stop-Process -Id <worker_pid> -Force"
```

杀掉 worker 后,parent reloader 会自动派一个新的。

> **git-bash 副作用**:`taskkill /PID xxx /T` 在 MSYS bash 下,`/T` 会被翻译成 `C:/Program Files/Git/PID` 路径,GBK 编码乱码报"无效参数 / 选项"。
> **必须用 `powershell -NoProfile -Command "Stop-Process ..."` 绕开。**

### 方案 B(fallback):换端口

worker 杀不掉(持有 socket 句柄不放)时,直接在新端口起:

```bash
cd backend && uvicorn lumen_main:app --host 0.0.0.0 --port 11336
```

然后把前端 `NEXT_PUBLIC_API_URL` / API 测试脚本指向 11336。

### 方案 C(最干净):dev 模式别用 `--reload`

```bash
cd backend && uvicorn lumen_main:app --host 0.0.0.0 --port 11335
```

PID 1:1 对应,不需要追溯 worker。代价是改代码要手动重启 —— 但比每次花 10 分钟排查 zombie 划算得多。

---

## 6. 连带坑:强杀留下 MySQL MDL 孤儿连接

### 症状

新 uvicorn 启动时卡在:

```
workflow_v2 migration: scanned=N migrated=0 ...
Waiting for application startup.
   ← 卡这里几十秒到永远,不出 "Application startup complete."
```

端口 11335 没有 LISTENING。

### 根因

`taskkill /F` 强杀旧 uvicorn 时,SQLAlchemy 连接池没走 `close()`,旧连接在 MySQL 那边变成 `Sleep` 状态,但**仍然持有事务级 MDL(Metadata Lock)**。

新 uvicorn 启动时的 `ensure_*` 迁移要 `ALTER TABLE conversations ...`,ALTER 需要 EXCLUSIVE MDL,于是排在孤儿连接的 SHARED_READ 后面,永远等不到。

### 诊断 SQL

```sql
-- 1. 看谁在等 metadata lock
SELECT id, user, host, command, time, state, LEFT(info, 200) info
FROM information_schema.processlist
WHERE command != 'Sleep' OR time > 30
ORDER BY time DESC;

-- 2. 找 GRANTED 的 SHARED_READ / SHARED_UPGRADABLE
SELECT object_type, lock_type, lock_duration, lock_status, owner_thread_id
FROM performance_schema.metadata_locks
WHERE object_schema = 'ai_platform' AND object_name = 'conversations';

-- 3. thread_id 映射回 processlist_id
SELECT thread_id, processlist_id, processlist_command, processlist_time
FROM performance_schema.threads
WHERE thread_id IN (<上一步的 owner_thread_id>);
```

### 修法

MCP 工具不支持 `KILL`,用 Python 直连:

```python
# 凭据在 backend/.env: DATABASE_URL=mysql+pymysql://root:rootpassword@localhost:3307/ai_platform
import pymysql

conn = pymysql.connect(
    host="localhost", port=3307,
    user="root", password="rootpassword",
    database="ai_platform", connect_timeout=5,
)
cur = conn.cursor()
cur.execute("KILL <processlist_id>")
conn.close()
```

杀完 Sleep 中的孤儿连接 → GRANTED 的 SHARED_READ 释放 → ALTER 升级到 EXCLUSIVE → 几秒内 `Application startup complete.`

### 预防

- 长期:在 uvicorn 关闭时的 SIGTERM handler 里调 `engine.dispose()`。
- 短期:优先 `Stop-Process`(不带 `-Force`),别 `taskkill /F`。

---

## 7. 连带坑:后台任务启的 uvicorn 会被带走

**症状(2026-06-08,复现 3 次)**:

用后台任务跑 `cd backend && uvicorn ... --reload > log 2>&1`:

1. 启动 → 健康检查 200 ✅
2. 几分钟后 → 进程消失,11335 不再 listen
3. log 里**没有任何 shutdown 信息**,exit code 127

**根因**:wrapper bash 进程退出时会带走它的子进程树,uvicorn reloader 跟着死。

**修法**:

```bash
nohup uvicorn lumen_main:app --host 0.0.0.0 --port 11335 --reload > /tmp/uvicorn.log 2>&1 &
disown
```

`nohup` + `disown` 让 uvicorn 完全脱离 bash 控制。

**验证**:30 秒后 reloader + worker 两个 `python.exe` 都还活着。

---

## 8. 铁律

1. **不要反复戳同一个陈旧实例**。发现返回值不对 → 先确诊 zombie → 重启。别 poll,别加 retry,别怀疑数据库。
2. **openapi.json 里没有的路由 = 后端没加载**。这是最快的判据。
3. **杀 worker,不是杀 reloader**。
4. **优先 `Stop-Process`(不带 `-Force`)**,给连接池一个干净关闭的机会。
5. **别假设"缺模块"**。本机的 Anaconda Python 就是能用的那个 —— 报 ImportError 先怀疑陈旧 worker,再考虑装包。

---

## 9. 排查速查表

| 现象 | 命令 | 期望 |
|------|------|------|
| 路由存在吗 | `curl -s localhost:11335/openapi.json \| grep <path>` | 有 → 代码已加载 |
| 谁占端口 | `netstat -ano \| grep :11335 \| grep LISTENING` | 拿 PID |
| 进程还在吗 | `Get-Process -Id <pid>` | 不在 = netstat 过期 |
| 是 worker 吗 | `Get-CimInstance Win32_Process -Filter "ProcessId=<pid>" \| Select CommandLine` | 有 `--multiprocessing-fork` |
| DB 卡住了吗 | `SELECT ... FROM information_schema.processlist WHERE time > 30` | 有长 Sleep = 孤儿连接 |

---

**相关文档**
- [常见错误速查](common-errors.md)
- [开发环境搭建](../how-to/dev-env.md)
- [端口分配](../architecture/06-port-alloc.md)

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
