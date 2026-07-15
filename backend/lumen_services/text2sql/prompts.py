"""Prompt templates for the two-phase Text2Sql engine.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §5

Two distinct LLM calls:

- **Phase 1 — ``generate_sql``**: ask the LLM to translate the
  natural-language question into a single MySQL SELECT. The system
  prompt carries the schema (from ``SchemaInspector``) and 3
  few-shot examples. The user prompt carries the user's question.

- **Phase 1.5 — ``regenerate_sql_with_error``**: when SQLGuard
  rejected the SQL or the trial execution failed, feed the LLM the
  previous attempt + the error so it can self-correct. Caps at
  ``max_retries`` (default 3) attempts.

- **Phase 2 — ``explain``**: when Phase 1 succeeded, ask the LLM
  to produce a Chinese natural-language summary of the rows + a
  0-1 confidence score.

The few-shot examples are deliberately hand-picked from the
ai_platform schema (the actual business tables this project cares
about) so the LLM sees concrete real-world patterns:

- 查询用户总数
- 查近 7 天创建的客户
- 按状态分组的客户数
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# Phase 1 — generate_sql                                                      #
# --------------------------------------------------------------------------- #


SQL_GENERATION_SYSTEM = """你是一个专业的 MySQL SQL 生成助手,负责把业务人员的自然语言问题转成可在 ai_platform 库执行的 SELECT 查询。

**严格规则**:

1. **只生成 SELECT 或 WITH ... SELECT**。禁止 INSERT / UPDATE / DELETE / DROP / ALTER / TRUNCATE / CREATE / GRANT / REVOKE / SET / BEGIN / COMMIT / CALL / EXEC / LOCK / USE / SHOW / DESCRIBE。
2. **只引用下方 schema 列出的表和字段**。禁止猜测不存在的表 / 字段。如果需要的信息不在 schema 中,直接返回文字"无法回答:缺少必要字段 X",不要硬猜。
3. **不要生成 LIMIT 子句** — 系统会自动追加 LIMIT {max_rows}。
4. **使用反引号包裹表名和字段名**(避免和 MySQL 关键字冲突)。
5. **优先使用具体的字段**,不要用 SELECT *。如果要"全部字段",在字段列表里逐个列出。
6. **JOIN 时使用表别名**(u / a / c),并明确 ON 条件。
7. **WHERE 条件用参数化思维**:直接用字面值(如 ``status = 'active'``),不要写 SQL 注入式字符串拼接。

**输出格式**:只输出一行 SQL,**不要** markdown 代码块、注释、解释。例:

  SELECT `id`, `username` FROM `users` WHERE `is_active` = 1

**Schema** (ai_platform 库):
{schema_text}
"""

SQL_GENERATION_USER_TEMPLATE = """请把下面的业务问题转成 MySQL SELECT:

{question}
"""


# --------------------------------------------------------------------------- #
# Phase 1.5 — regenerate with error feedback                                  #
# --------------------------------------------------------------------------- #


SQL_REGENERATION_WITH_ERROR_USER_TEMPLATE = """上一次生成的 SQL 被系统拒绝或执行失败:

**上一次 SQL**:
{last_sql}

**错误信息**:
{error}

**业务问题(保持不变)**:
{question}

请根据错误信息修正 SQL,重新生成。同样只输出一行 SQL,不要解释。
"""


# --------------------------------------------------------------------------- #
# Phase 2 — explain                                                           #
# --------------------------------------------------------------------------- #


EXPLANATION_SYSTEM = """你是一个数据分析助理,负责把 SQL 查询结果用中文给业务人员讲解。

**严格要求**:

1. **基于事实**:只能用下面提供的 question / SQL / rows 三个字段作为输入,不要编造数据。
2. **简洁**:2-4 句话,直接讲"查出来什么 / 数字是多少 / 有什么规律"。
3. **数字具体**:百分比、绝对值、趋势都说清楚。
4. **不输出 JSON / 表格**:直接自然语言,用户能在聊天框直接读。
5. **结尾追加置信度**:在最后一行写 "置信度: 0.85",数值 0.0-1.0,根据 SQL 和数据匹配程度给。
"""

EXPLANATION_USER_TEMPLATE = """**问题**:
{question}

**执行的 SQL**:
{sql}

**结果(行数 = {row_count})**:
{rows_preview}

请用中文给业务人员讲解。
"""


# --------------------------------------------------------------------------- #
# Few-shot examples                                                           #
# --------------------------------------------------------------------------- #


FEW_SHOT_EXAMPLES: List[Dict[str, str]] = [
    {
        "question": "ai_platform 库里有几个用户?",
        "sql": "SELECT COUNT(*) AS user_count FROM `users`",
    },
    {
        "question": "近 7 天创建的客户有多少?",
        "sql": (
            "SELECT COUNT(*) AS recent_customer_count FROM `customers` "
            "WHERE `created_at` >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
        ),
    },
    {
        "question": "按状态分组的客户数",
        "sql": (
            "SELECT `status`, COUNT(*) AS count FROM `customers` "
            "GROUP BY `status` ORDER BY `count` DESC"
        ),
    },
]


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def render_sql_generation_system(
    schema_text: str,
    max_rows: int = 100,
) -> str:
    """Render the Phase 1 system prompt with the live schema baked in."""
    return SQL_GENERATION_SYSTEM.format(
        schema_text=schema_text,
        max_rows=max_rows,
    )


def render_sql_generation_user(question: str) -> str:
    return SQL_GENERATION_USER_TEMPLATE.format(question=question)


def render_regeneration_user(
    question: str,
    last_sql: str,
    error: str,
) -> str:
    return SQL_REGENERATION_WITH_ERROR_USER_TEMPLATE.format(
        question=question,
        last_sql=last_sql,
        error=error,
    )


def render_explanation_system() -> str:
    return EXPLANATION_SYSTEM


def render_explanation_user(
    question: str,
    sql: str,
    rows: List[Dict[str, Any]],
    row_count: int,
    preview_cap: int = 10,
) -> str:
    """Render the Phase 2 user prompt, capped to ``preview_cap`` rows.

    Long result sets would blow up the prompt — we keep the first
    ``preview_cap`` rows verbatim and append a "..." marker.
    """
    if len(rows) <= preview_cap:
        rows_preview = repr(rows)
    else:
        rows_preview = repr(rows[:preview_cap]) + (
            f"\n... (total {row_count} rows, only first "
            f"{preview_cap} shown)"
        )
    return EXPLANATION_USER_TEMPLATE.format(
        question=question,
        sql=sql,
        rows_preview=rows_preview,
        row_count=row_count,
    )


def parse_explanation(raw: str) -> Dict[str, Optional[Any]]:
    """Pull the trailing "置信度: 0.85" line out of the LLM response.

    Returns ``{"explanation": <text without confidence line>,
    "confidence": <float 0-1 or None>}``.

    The LLM is told to end with the confidence line, but in practice
    some models (notably qwen2.5:7b) may forget. We default to
    ``confidence=None`` and ``explanation=raw`` in that case so the
    UI can still show the text.
    """
    import re
    # Match trailing "置信度: 0.85" or "置信度:0.85" optionally with
    # a trailing period. Anchored to the end of the string with
    # optional whitespace.
    pattern = re.compile(
        r"置信度\s*[:：]\s*(-?(?:0?\.\d+|1(?:\.0+)?|\d+(?:\.\d+)?))\s*[。.]?\s*$",
        re.MULTILINE,
    )
    m = pattern.search(raw)
    if not m:
        return {"explanation": raw.strip(), "confidence": None}
    try:
        conf = float(m.group(1))
        # Clamp to [0, 1] for safety.
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        return {"explanation": raw.strip(), "confidence": None}
    text = raw[: m.start()].rstrip()
    return {"explanation": text or raw.strip(), "confidence": conf}
