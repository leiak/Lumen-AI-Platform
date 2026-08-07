# 错误处理基础设施

> Lumen AI Platform 工作流节点的**统一错误处理 / 重试 / 超时**机制。
> M9 ship 的共享基础设施,所有 22 节点默认支持。

---

## 1. 三大配置

每个工作流节点都有 3 个错误相关配置:

| 字段 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `error_strategy` | enum | `fail_fast` | 失败时怎么办 |
| `retry_config` | object | `{max_attempts: 1, backoff: "none"}` | 重试策略 |
| `timeout_seconds` | int | 30 | 单次执行超时 |

### 1.1 `error_strategy` 取值
- **`fail_fast`** (默认):失败立即抛错,工作流终止
- **`ignore`**:失败忽略,节点标记 `skipped`,继续后续
- **`fallback`**:失败用 `fallback_output` 替代输出,继续后续

### 1.2 `retry_config`
```json
{
  "max_attempts": 3,             // 总尝试次数(含首次)
  "backoff": "exponential",      // none / fixed / exponential
  "initial_delay_seconds": 1,    // 首次重试延迟
  "max_delay_seconds": 60        // 最大延迟
}
```

### 1.3 `timeout_seconds`
- 单次执行(包括重试的每次)超时
- 超时抛 `asyncio.TimeoutError`,触发重试

---

## 2. 节点级 vs 工作流级

### 2.1 节点级
- 在节点的 `config` JSON 里设
- 例:LLM 节点 `error_strategy="ignore"` + `retry_config={max_attempts: 3}`

### 2.2 工作流级(默认值)
- `workflows.default_error_strategy` = "fail_fast"
- `workflows.default_retry_config` = {max_attempts: 1}
- `workflows.default_timeout_seconds` = 30

### 2.3 优先级
- 节点配置 > 工作流默认

---

## 3. 执行流程

```
节点 start
  │
  ▼
for attempt in 1..max_attempts:
  │
  ▼
  try:
    start_node_run(node_key, attempt)
    output = await asyncio.wait_for(
        invoke_node(state, config),
        timeout=timeout_seconds
    )
    finish_node_run(status="success", outputs=output)
    return output
  │
  ├─ TimeoutError:
  │   if attempt < max_attempts:
  │     sleep(backoff(attempt))
  │     continue
  │   else:
  │     handle_final_error(TimeoutError)
  │
  └─ Exception as e:
      if attempt < max_attempts:
        sleep(backoff(attempt))
        continue
      else:
        handle_final_error(e)
```

### 3.1 `handle_final_error`
```python
def handle_final_error(error):
    if error_strategy == "ignore":
        finish_node_run(status="skipped", error=str(error))
        return None  # 后续节点用 None
    elif error_strategy == "fallback":
        finish_node_run(status="failed_fallback", outputs=fallback_output, error=str(error))
        return fallback_output
    else:  # fail_fast
        finish_node_run(status="failed", error=str(error))
        raise
```

---

## 4. Backoff 算法

### 4.1 `none`
- 不等待,立即重试

### 4.2 `fixed`
- 每次重试前等固定时间
- 例: `initial_delay_seconds=2` → 等 2 秒 → 重试 → 等 2 秒 → 重试

### 4.3 `exponential`
- 指数退避
- 公式: `delay = min(initial * 2^(attempt-1), max_delay)`
- 例:initial=1, max=60
  - 第 1 次重试: 1 秒
  - 第 2 次重试: 2 秒
  - 第 3 次重试: 4 秒
  - 第 4 次重试: 8 秒
  - ...
  - 第 7 次重试: 60 秒(封顶)

### 4.4 抖动
- 加 ± 20% 随机抖动,避免雪崩
- 例:第 1 次重试等 0.8~1.2 秒

---

## 5. UI 实现

### 5.1 配置面板
- 文件: `frontend/components/workflow/_base/error/{ErrorStrategyPicker,RetryConfigForm,TimeoutInput,AdvancedOptions}.tsx`
- 在每个节点的属性面板里展开"高级选项"

### 5.2 截图(伪 UI)
```
┌─ 错误处理 ─────────────────────┐
│ 错误策略:  [失败停止 ▼]        │
│                                │
│ ☑ 失败时重试                   │
│   最大尝试次数: [3]             │
│   退避策略:    [指数退避 ▼]     │
│   初始延迟:    [1] 秒           │
│   最大延迟:    [60] 秒          │
│                                │
│ 超时:        [30] 秒           │
└────────────────────────────────┘
```

### 5.3 测试
- 文件: `frontend/__tests__/workflow/_base/error/{ErrorStrategyPicker,RetryConfigForm,TimeoutInput}.test.tsx`
- 覆盖:默认值、修改、边界

---

## 6. 业务场景配置示例

### 6.1 LLM 节点(可重试)
```json
{
  "error_strategy": "ignore",
  "retry_config": {
    "max_attempts": 3,
    "backoff": "exponential",
    "initial_delay_seconds": 1
  },
  "timeout_seconds": 60
}
```
理由:LLM 偶发超时,重试能恢复;失败不致命,继续后续

### 6.2 HTTP 节点(可 fallback)
```json
{
  "error_strategy": "fallback",
  "fallback_output": {"status": "down", "data": null},
  "retry_config": {"max_attempts": 2, "backoff": "fixed", "initial_delay_seconds": 2},
  "timeout_seconds": 10
}
```
理由:HTTP 外部服务可能挂,失败用默认数据兜底

### 6.3 Code 节点(快速失败)
```json
{
  "error_strategy": "fail_fast",
  "retry_config": {"max_attempts": 1, "backoff": "none"},
  "timeout_seconds": 5
}
```
理由:代码错就错,不应重试浪费资源

### 6.4 KB 检索节点(容错)
```json
{
  "error_strategy": "ignore",
  "retry_config": {"max_attempts": 2, "backoff": "fixed", "initial_delay_seconds": 1},
  "timeout_seconds": 15
}
```
理由:KB 失败不致命(只是没引用),重试 1 次

---

## 7. 错误传播

### 7.1 节点失败 vs 工作流失败
- 节点失败但 `error_strategy=ignore` → 工作流继续
- 节点失败且 `error_strategy=fail_fast` → 工作流终止,标 `failed`

### 7.2 工作流 Run 状态
- `running` → 跑中
- `success` → 全部节点成功
- `partial_success` → 部分节点 skipped/fallback(全部"完成")
- `failed` → 至少一个 fail_fast 失败
- `cancelled` → 用户取消

### 7.3 通知
- 工作流 Run 完成 → 通知
- 关键节点失败 → 通知(默认 LLM / HTTP 节点)

---

## 8. 与 Celery 重试的区别

### 8.1 Celery 重试
- 任务级重试
- 用于异步任务(parse_document / image_generate / 等)
- 配置: `task.apply_async(retry=True, retry_policy={...})`

### 8.2 工作流节点重试
- 节点级重试
- 用于工作流内部
- 实时跑(非异步任务)

### 8.3 关系
- 工作流 Run 自己跑(同步),不依赖 Celery
- 节点内部可能调 Celery 任务(如 HTTP 触发异步任务),那 Celery 任务失败不直接触发节点重试
- 若要"等 Celery 任务完成 + 失败重试",用 `lumen_tasks` 的 `apply_async` + 轮询结果

---

## 9. 监控

### 9.1 关键指标
- 节点成功率(per type)
- 节点平均重试次数
- 节点平均耗时(P50 / P95)
- 工作流 Run 状态分布

### 9.2 看板
- 当前: `frontend/app/dashboard/logs` + 节点 BFS 日志
- 计划: 工作流统计页面

### 9.3 告警
- 节点失败率 > 10% → 通知
- 工作流 Run 长期 running(> 1 小时) → 通知

---

## 10. 测试

### 10.1 单元测试
- 文件: `backend/tests/unit/test_workflow_error_handling.py`
- 覆盖:
  - 重试正确性
  - 退避算法
  - 各种 error_strategy
  - 超时

### 10.2 集成测试
- 文件: `backend/tests/integration/test_workflow_error_e2e.py`
- 跑实际 LangGraph,模拟各种错误

### 10.3 前端测试
- 文件: `frontend/__tests__/workflow/_base/error/*.test.tsx`
- 覆盖 UI 交互

---

## 11. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 节点一直重试不退出 | max_attempts 设太大 | 改小 |
| 节点不重试 | retry_config.max_attempts=1 | 改大 |
| 工作流挂死 | 节点 timeout 太大 + max_attempts 大 | 调小 |
| 节点失败但工作流继续 | error_strategy=ignore | 按业务改 fail_fast / fallback |
| 节点 fallback 输出不对 | fallback_output 没设 | 配 JSON |
| 通知太多 | 所有节点都"通知失败" | 关键节点才通知 |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
