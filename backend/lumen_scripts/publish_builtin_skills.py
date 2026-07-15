#!/usr/bin/env python3
"""
内置技能写入 SkillMarketplace（中文名，provider=lumen-platform）。
直接在 DB 里插记录，不走 GitHub 导入逻辑。
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lumen_core.database import SessionLocal
from lumen_models.skill_marketplace import SkillMarketplace


def upsert(name, category, skill_type, description, content, meta_data=None):
    db = SessionLocal()
    existing = db.query(SkillMarketplace).filter(
        SkillMarketplace.name == name,
        SkillMarketplace.provider == "lumen-platform",
    ).first()
    if existing:
        existing.description = description
        existing.content = content
        existing.category = category
        existing.type = skill_type
        existing.meta_data = meta_data or {}
        print(f"  [UPDATED] {name}")
    else:
        s = SkillMarketplace(
            name=name,
            category=category,
            type=skill_type,
            description=description,
            content=content,
            provider="lumen-platform",
            meta_data=meta_data or {},
            downloads=0,
        )
        db.add(s)
        print(f"  [INSERT] {name} (id=will be {db.query(SkillMarketplace).count()+1})")
    db.commit()
    db.close()


def main():
    print("Writing lumen-platform builtin skills...")

    # ── 1. 代码审查助手 ──────────────────────────────────────────────
    upsert(
        name="代码审查助手",
        category="engineering",
        skill_type="prompt",
        description="对提交的代码进行多维度审查：逻辑正确性、安全漏洞（SQL注入/XSS/敏感信息暴露）、性能问题（循环/查询N+1）、可读性与代码规范。输出结构化审查报告，列出严重/警告/建议三级问题并给出修复建议。",
        content="""你是一位资深代码审查专家。请审查以下代码，从多个维度进行分析：

1. **逻辑正确性** — 是否有边界条件未处理、状态机遗漏、空指针等
2. **安全漏洞** — SQL注入、XSS、敏感信息明文、日志脱敏、权限校验缺失
3. **性能问题** — 循环内查询、O(N²)算法、重复计算、大数据量未分页
4. **可读性与规范** — 命名规范、注释完整性、函数长度（建议<50行）、重复代码

代码如下：
---
{code}
---

请按以下 JSON 格式输出（只用中文）：
```json
{
  "summary": "整体评价（1-2句话）",
  "issues": [
    {
      "severity": "严重|警告|建议",
      "file": "文件名（未知则写'通用'）",
      "line": "行号（未知写'?'）",
      "type": "逻辑|安全|性能|可读性",
      "title": "问题简述",
      "detail": "详细说明",
      "fix": "修复建议"
    }
  ]
}
```""",
        meta_data={"author": "lumen-platform", "lang": "zh"},
    )

    # ── 2. API设计评审 ──────────────────────────────────────────────
    upsert(
        name="API设计评审",
        category="engineering",
        skill_type="prompt",
        description="对 REST API 设计进行标准化审查，检查资源命名、HTTP方法使用、状态码规范、版本策略、错误响应格式、分页设计等是否符合业界最佳实践。",
        content="""你是一位 API 架构专家。请对以下 OpenAPI / REST API 设计进行评审：

标准检查项：
1. **资源命名** — 路径使用 kebab-case 名词复数（/user-profiles 而非 /getUser）
2. **HTTP 方法** — GET（查）/ POST（创）/ PUT（全量改）/ PATCH（部分改）/ DELETE（删）
3. **状态码** — 200成功 / 201创建 / 400客户端错 / 401未认证 / 403禁止 / 404不存在 / 500服务端错
4. **错误响应** — 统一 {code, message, detail} 结构，包含纠错指引
5. **版本策略** — URL版（/v1/）/ Header版（Accept-Version），避免路径污染
6. **分页** — cursor-based 或 page-based，避免 limit/offset 大偏移量陷阱
7. **认证** — Bearer Token / API Key 说明，敏感操作有额外校验

API 设计内容：
---
{api_spec}
---

请按以下 JSON 格式输出（只用中文）：
```json
{
  "summary": "整体评价",
  "score": 0-100,
  "issues": [
    {
      "severity": "严重|警告|建议",
      "category": "命名|方法|状态码|错误响应|版本|分页|认证|其他",
      "title": "问题标题",
      "detail": "详细说明",
      "recommendation": "修改建议"
    }
  ]
}
```""",
        meta_data={"author": "lumen-platform", "lang": "zh"},
    )

    # ── 3. 技术文档生成器 ──────────────────────────────────────────
    upsert(
        name="技术文档生成器",
        category="engineering",
        skill_type="prompt",
        description="根据代码或接口设计自动生成 Markdown 格式的技术文档，包括：功能说明、参数定义、请求/响应示例、错误码表格、注意事项。支持 API 文档和函数库文档两种模式。",
        content="""你是一位技术文档工程师。请根据以下输入，生成结构完整的中文 Markdown 技术文档。

支持两种模式，自动识别：
- **API模式**：输入 OpenAPI/JSON 描述
- **函数库模式**：输入函数签名 + 实现逻辑

输入内容：
---
{input}
---

请生成以下结构的 Markdown 文档：

```markdown
# 标题

## 功能说明
简要描述功能定位和使用场景。

## 基础信息
- 版本号
- 作者
- 最后更新

## API 接口（或函数签名）
### 接口名称（或函数名）

#### 请求参数
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| ...    | ...  | 是/否 | ...  |

#### 响应示例
```json
// 成功
{ }

// 失败
{ }
```

## 错误码
| 错误码 | 说明 | 处理建议 |
|--------|------|----------|
| ...    | ...  | ...      |

## 使用示例
\`\`\`python
// 或 curl / JavaScript
\`\`\`

## 注意事项
- ...
```

请只输出 Markdown 内容，不要有其他说明文字。""",
        meta_data={"author": "lumen-platform", "lang": "zh"},
    )

    # ── 4. 周报生成器 ──────────────────────────────────────────────
    upsert(
        name="周报生成器",
        category="productivity",
        skill_type="prompt",
        description="根据一周的工作记录（commit消息、会议纪要、工时记录），自动生成结构化周报。包含：本周完成、进行中、风险与阻塞、下周计划、量化指标（完成率/工时）。",
        content="""你是一位项目助理。请根据以下工作记录，生成结构化中文周报。

工作记录：
---
{work_records}
---

请生成以下结构的 Markdown 周报：

```markdown
# 周报 — {姓名} — {年份}-{月份}-{第N周}

## 📊 本周概览
- 总工时：Xh
- 完成任务：X 项
- 计划完成率：X%

## ✅ 本周完成
| 任务 | 类型 | 耗时 | 状态 |
|------|------|------|------|
| ...  | ...  | ...  | 已完成 |

## 🔄 进行中
| 任务 | 进度 | 预计完成 |
|------|------|----------|
| ...  | 60% | 周四     |

## ⚠️ 风险与阻塞
| 风险/阻塞 | 影响 | 应对措施 |
|-----------|------|----------|
| 缺少API文档 | 影响联调进度 | 已催促后端补充 |

## 📅 下周计划
- [ ] 任务1
- [ ] 任务2

## 📝 备注（如有）
...
```

只输出 Markdown，不要有其他说明文字。""",
        meta_data={"author": "lumen-platform", "lang": "zh"},
    )

    # ── 5. Python ↔ JavaScript 代码翻译 ──────────────────────────
    upsert(
        name="代码语言翻译",
        category="engineering",
        skill_type="prompt",
        description="在 Python 和 JavaScript/TypeScript 之间进行代码互译，保留原逻辑和注释，处理语言特性差异（如异步/同步、类型系统、包管理器对应）。输出含注释说明翻译中需要注意的差异点。",
        content="""你是一位全栈工程师。请将以下 {source_lang} 代码翻译为 {target_lang}，保持功能完全一致，添加行内注释说明翻译差异点。

翻译原则：
- 保留原变量名和函数结构的可读性
- 异步语法正确对应（Python asyncio ↔ JS async/await）
- 类型声明对应（Python type hints → JS/TS types）
- 包对应（如 Python requests → JS axios，Python datetime → JS date-fns）
- 异常处理对应（Python try/except → JS try/catch）

{source_lang} 源码：
---
{code}
---

目标语言：{target_lang}

请输出：
1. 翻译后的完整代码（Markdown 代码块）
2. **翻译说明**（列表形式，说明每个关键差异点）
3. 如遇语言特性无法对应，说明原因并给出等效方案

只输出上述内容，不要有其他说明。""",
        meta_data={"author": "lumen-platform", "lang": "zh"},
    )

    # ── 6. 数据库Schema审查 ────────────────────────────────────────
    upsert(
        name="数据库Schema审查",
        category="engineering",
        skill_type="prompt",
        description="对 SQL DDL 或数据库 Schema 进行审查，检查表设计规范性、字段类型合理性、索引覆盖、关联外键完整性、命名规范、潜在数据质量问题（如 NULL 处理、默认值、软删除）。",
        content="""你是一位 DBA 专家。请审查以下数据库 Schema 设计：

审查维度：
1. **命名规范** — 表名 kebab-case 或 snake_case、字段语义清晰、避免保留字
2. **字段设计** — 类型选择合理（VARCHAR vs TEXT vs ENUM）、长度恰当、NOT NULL 有默认值
3. **主键策略** — 自增ID / UUID / 复合主键，适合业务场景
4. **索引设计** — 查询列有索引、联合索引顺序正确、无冗余重复索引
5. **外键完整性** — 关联关系清晰、ON DELETE/UPDATE 策略明确
6. **软删除** — 敏感数据用软删除而非硬删除
7. **审计字段** — created_at / updated_at / deleted_at / created_by

Schema 内容：
---
{schema}
---

请按以下 JSON 输出（只用中文）：
```json
{
  "summary": "整体评价",
  "issues": [
    {
      "severity": "严重|警告|建议",
      "type": "命名|类型|索引|外键|规范|其他",
      "target": "表名.字段名 或 '通用'",
      "title": "问题",
      "detail": "详细说明",
      "fix": "修复方案"
    }
  ],
  "recommendations": ["优化建议1", "优化建议2"]
}
```""",
        meta_data={"author": "lumen-platform", "lang": "zh"},
    )

    # ── 7. Slack/飞书日报摘要 ────────────────────────────────────
    upsert(
        name="团队日报摘要",
        category="productivity",
        skill_type="prompt",
        description="将团队成员的日报内容汇总，提取关键进展、风险、决策，生成一目了然的团队日报汇总。适用于 5-20 人团队的日常同步。",
        content="""你是一位工程运营助理。请将以下团队成员的日报汇总成一份团队日报。

汇总规则：
- 合并重复事项（同一任务多人参与只出现一次）
- 提取共性风险（多人提到同一风险要合并强调）
- 突出今日关键决策
- 量化输出（完成率、工时统计）

成员日报（按人分隔）：
---
{daily_reports}
---

请生成以下格式的 Markdown（只用中文）：

```markdown
# 团队日报 — {日期}

## 📈 今日概况
- 在编人员：X 人
- 提交日报：X 人
- 完成任务：X 项
- 进行中：X 项

## 🚀 关键进展
- [进展1描述] — 负责人
- [进展2描述] — 负责人

## ⚠️ 风险与阻塞
| 风险 | 影响 | 负责人 | 应对 |
|------|------|--------|------|
| ...  | ...  | ...    | ...  |

## 💬 今日决策
- 决策1描述
- 决策2描述

## 📋 明日计划
- [ ] 任务（负责人）

## 📊 工时统计
| 人员 | 今日工时 | 本周累计 |
|------|----------|----------|
| ...  | ...      | ...      |
```

只输出 Markdown，不要有其他说明文字。""",
        meta_data={"author": "lumen-platform", "lang": "zh"},
    )

    print("\nDone. All builtin skills written.")


if __name__ == "__main__":
    main()
