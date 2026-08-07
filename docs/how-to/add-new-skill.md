# How-to:新增一个技能(Skill)

> 业务需要新能力 → 加一个技能(Agent 可以调用)。
> 4 种类型:Prompt / HTTP / Script / Text2SQL,各有套路。

---

## 1. 技能的类型

| 类型 | 适用 | 例子 |
|------|------|------|
| **Prompt** | 复用现有 LLM + 模板 | 生成营销文案、修改语气 |
| **HTTP** | 调外部 API(GET/POST) | 查天气、查订单 |
| **Script** | 跑 Python 脚本 | 复杂计算、数据转换 |
| **Text2SQL** | 查数据库 | 业务问数 |

详见 [skill-market.md](../modules/skill-market.md)。

---

## 2. 步骤(以 HTTP 技能为例)

### 2.1 设计

**目标**: 加一个「查股票价格」技能
- 输入:股票代码
- 输出:当前价格
- 调外部 API:某免费股票 API

### 2.2 后端

**文件**:`backend/lumen_services/skill_executors/my_stock.py`

```python
from lumen_services.skill_executors.base import BaseSkillExecutor


class MyStockExecutor(BaseSkillExecutor):
    """Brief description on one line."""

    skill_type = "http"  # reuse HTTP skill type

    async def execute(self, params: dict, config: dict) -> dict:
        """Execute the skill.

        Args:
            params:         参数(rawparams from LLM)
            config:         技能配置(domain/path/method/headers)

        Returns:
            dict: 技能输出(LLM 看的)
        """
        symbol = params.get("symbol", "").upper()
        if not symbol:
            raise ValueError("missing symbol")

        # 调外部 API
        url = f"https://api.example.com/stock/{symbol}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"API {resp.status}")
                data = await resp.json()

        return {
            "symbol": symbol,
            "price": data["price"],
            "currency": data.get("currency", "USD"),
        }
```

### 2.3 注册

**文件**:`backend/lumen_services/skill_executors/__init__.py`

```python
from lumen_services.skill_executors.my_stock import MyStockExecutor

# HTTP 技能共用一个 type
HTTP_EXECUTOR_REGISTRY = {
    # ... 默认
    "my_stock": MyStockExecutor,
}
```

### 2.4 写测试

**文件**:`backend/tests/unit/test_skill_my_stock.py`

```python
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_my_stock_executor():
    executor = MyStockExecutor()

    with patch("aiohttp.ClientSession.get") as mock_get:
        # mock 响应
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"price": 100.5})
        mock_get.return_value.__aenter__.return_value = mock_response

        result = await executor.execute(
            params={"symbol": "AAPL"},
            config={"domain": "api.example.com"},
        )

    assert result["symbol"] == "AAPL"
    assert result["price"] == 100.5


@pytest.mark.asyncio
async def test_my_stock_missing_symbol():
    executor = MyStockExecutor()
    with pytest.raises(ValueError):
        await executor.execute(params={}, config={})
```

### 2.5 上架 Skill Market

通过 admin 后台,或 seed 脚本:

```python
# lumen_scripts/seed_skills.py

SKILLS_TO_SEED = [
    {
        "name": "查股票价格",
        "description": "输入股票代码,返回当前价格",
        "category": "finance",
        "type": "http",
        "content_json": {
            "domain": "api.example.com",
            "path": "/stock/{symbol}",
            "method": "GET",
            "params_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码"}
                },
                "required": ["symbol"],
            },
        },
    },
    # ...
]
```

### 2.6 前端 UI

**文件**:`frontend/components/skill-market/MyStockCard.tsx`(可选)

```tsx
"use client";
import React from "react";
import { Card } from "antd";

export default function MyStockCard() {
  return (
    <Card title="查股票价格" extra={<span>📈</span>}>
      <p>输入股票代码,返回当前价格</p>
    </Card>
  );
}
```

---

## 3. Prompt 技能

```python
class MyPromptSkill(BaseSkillExecutor):
    skill_type = "prompt"

    async def execute(self, params: dict, config: dict) -> dict:
        prompt = config["prompt_template"].format(**params)
        response = await self.llm_call(prompt)
        return {"output": response}
```

**Seed**:
```python
{
    "name": "营销文案改写",
    "type": "prompt",
    "content_json": {
        "prompt_template": "请把以下文案改写成更吸引人的风格:\n\n{text}",
        "model_config_id": 1,  # → models 表
    },
}
```

---

## 4. Script 技能

```python
class MyScriptSkill(BaseSkillExecutor):
    skill_type = "script"

    async def execute(self, params: dict, config: dict) -> dict:
        script = config["script"]
        # ⚠️ 沙箱执行
        safe_globals = {"__builtins__": limited_builtins}
        safe_locals = dict(params)
        exec(script, safe_globals, safe_locals)
        return {"output": safe_locals.get("result")}
```

**警告**:`exec()` 危险,**必须**沙箱化(disable `os`, `sys`, `open` 等)。

**Seed**:
```python
{
    "name": "金额转中文",
    "type": "script",
    "content_json": {
        "script": """
amount = params['amount']
result = ''.join(['零一二三四五六七八九'[int(d)] for d in str(amount)])
        """,
    },
}
```

---

## 5. Text2SQL 技能

这个其实就是智能问数的 wrapper:

```python
class MyText2SqlSkill(BaseSkillExecutor):
    skill_type = "text2sql"

    async def execute(self, params: dict, config: dict) -> dict:
        data_source_id = config["data_source_id"]
        question = params["question"]

        response = await self.text2sql_ask(
            data_source_id=data_source_id,
            question=question,
        )

        return {
            "sql": response["sql"],
            "rows": response["rows"],
            "summary": response["natural_answer"],
        }
```

**Seed**:
```python
{
    "name": "查上个月销售",
    "type": "text2sql",
    "content_json": {
        "data_source_id": 1,
        "default_question": "上个月销售 TOP 10 产品",
    },
}
```

---

## 6. 技能命名 / 路由

**LLM 怎么知道调用哪个技能**?通过 `skill_recommender` 服务:

```python
# backend/lumen_services/skill_recommender.py

class SkillRecommender:
    """根据用户 query 选出 1~N 个相关技能。"""

    async def recommend(self, query: str, agent_id: int, limit: int = 5) -> list[Skill]:
        # 1. 拿该 Agent 已装的技能
        installed = self.get_installed(agent_id)

        # 2. Embedding 相似度
        query_emb = await embed(query)
        scored = []
        for skill in installed:
            sim = cosine(query_emb, skill.embedding)
            scored.append((skill, sim))

        # 3. 排序
        scored.sort(key=lambda x: -x[1])
        return [s for s, _ in scored[:limit]]
```

**为了 Skill Recommender 工作**,每个技能要有 `embedding` 字段(seed 时计算)。

---

## 7. 测试覆盖

### 7.1 单元测试

```python
# backend/tests/unit/test_skill_my_stock.py
def test_my_stock_executor():
    # 直接测 executor
    ...
```

### 7.2 集成测试

```python
# backend/tests/integration/test_skill_install.py
def test_install_my_skill(client, headers):
    # 测试 install → run → 卸载
    skill = client.get("/api/v1/skill-market", headers=headers).json()
    skill_id = find_skill(skill, "my_stock")

    # 安装
    client.post(f"/api/v1/skill-market/{skill_id}/install", headers=headers)

    # Agent 装上
    agent = client.post("/api/v1/agents", json={...}, headers=headers).json()
    # ...

    # 调
    response = client.post(f"/api/v1/agents/{agent['id']}/chat",
                            json={"message": "查 AAPL"}, headers=headers)
    # 验证
```

### 7.3 前端

```ts
// frontend/__tests__/skill/my-stock.test.tsx
test("my_stock_skill_card", () => {
  render(<MyStockCard />);
  expect(screen.getByText("查股票价格")).toBeInTheDocument();
});
```

---

## 8. 文档

- 更新 [skill-market.md](../modules/skill-market.md) — 加新技能段落
- 加 changelog / release notes

---

## 9. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 技能不出现 | 没 seed | 跑 `lumen_scripts/seed_skills.py` |
| Agent 不调用技能 | skill_recommender 没选到 | 改 description / 加更多用例 |
| 脚本技能报错 | 沙箱限制 | 改 allowed_builtins |
| HTTP 技能 403 | 域名不在白名单 | 加到 `system_configs.skill_http_allowed_domains` |
| LLM 调技能参数错 | params_schema 不清晰 | 改 description |
| 技能挂在 Skill Recommender | 没 embedding | reseed |

---

## 10. 安全

- **HTTP 技能**:白名单域名(`skill_http_allowed_domains`),不要 hardcoded 任意 domain
- **Script 技能**:沙箱执行,禁用 `os` / `sys` / `subprocess` / `open`
- **Prompt 技能**:LLM 注入风险 — 参数要 sanitize
- **Text2SQL 技能**:三道防线(SQLGuard + 只读账号 + LIMIT)

---

**相关文档**
- [skill-market.md](../modules/skill-market.md)
- [text2sql.md](../modules/text2sql.md)
- [system-config.md](../modules/system-config.md) — HTTP 白名单
- [tool-calling.md](../explanation/tool-calling.md) — 技能注入 / 工具调用循环

**维护者**:全栈架构师
**最近更新**:2026-08-06
