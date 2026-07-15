"""Text2Sql skill executor (M33 6th executor type).

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §7

The text2sql skill is a *tool-only* skill: when the LLM decides to
call it, we ask the user a natural-language question via
``Text2SqlEngine.ask`` and return a markdown-formatted answer to the
chat stream. There's no system-prompt injection because the LLM is
the orchestrator — it decides when to invoke the tool.

Compared to the standalone /text2sql/ask endpoint:

- The schema validation + trial execution is the same.
- The data source is resolved from the skill's
  ``type_config.data_source_name`` (default: "默认 ai_platform").
- The LLMCallContext uses ``client_app="dashboard"`` so the trace
  page shows the source as the chat client.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from lumen_core.database import SessionLocal
from lumen_models.skill_marketplace import SkillMarketplace
from lumen_schemas.skill import Text2SqlTypeConfig
from lumen_services.skill_executors.base import BaseSkillExecutor
from lumen_services.text2sql.data_source_service import Text2SqlDataSourceService
from lumen_services.text2sql.engine import Text2SqlEngine


logger = logging.getLogger(__name__)


class Text2SqlExecutor(BaseSkillExecutor):
    """The 6th skill executor type — natural language → SQL → answer."""

    type = "text2sql"

    def to_system_prompt(self, skill: SkillMarketplace) -> Optional[str]:
        # Tool-only: the LLM should call us, not see us as instructions.
        return None

    def to_langchain_tool(
        self,
        skill: SkillMarketplace,
        tenant_id: int,
    ) -> Optional[BaseTool]:
        cfg = Text2SqlTypeConfig(**(skill.type_config or {}))

        # LangChain 1.0: empty schema is treated as "no args" and the
        # input dict is dropped. The ``question`` field forces
        # get_fields() to be non-empty so the LLM call lands here.
        class Text2SqlInput(BaseModel):
            model_config = ConfigDict(extra="allow")
            question: str = Field(
                ...,
                description=(
                    "用户的自然语言问题(中文或英文),比如 '客户总数是多少' "
                    "或 '近 7 天新增的用户'"
                ),
            )

        # Capture the data source name at registration time so the
        # tool body is just a thin wrapper.
        data_source_name = cfg.data_source_name or "默认 ai_platform"

        def _run(input_data=None, **kwargs) -> str:
            # LangChain 1.0 normalisation (M24 fix): when the LLM
            # sends a dict, it lands as input_data, NOT **kwargs.
            if input_data is None:
                input_data = kwargs
            elif kwargs:
                input_data = {**input_data, **kwargs}
            question = (input_data or {}).get("question") or ""
            if not isinstance(question, str) or not question.strip():
                return "Error: question is required"

            # Open a fresh Session — the chat path runs in an async
            # context, and we don't want to share transactions across
            # the tool boundary.
            db = SessionLocal()
            try:
                ds = Text2SqlDataSourceService.get_by_name_for_tenant(
                    db, tenant_id=tenant_id, name=data_source_name,
                )
                if ds is None:
                    # Auto-seed fallback (matches the standalone
                    # /text2sql/ask UX): if the named source doesn't
                    # exist, create a default one.
                    ds = Text2SqlDataSourceService.get_default(
                        db, tenant_id=tenant_id
                    )
                if ds is None:
                    return f"Error: data source {data_source_name!r} not found"
                result = Text2SqlEngine(db, ds).ask(
                    question,
                    user_id=None,
                    tenant_id=tenant_id,
                    client_app="dashboard",
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.exception("Text2Sql executor failed: %s", exc)
                return f"Error: text2sql executor failed: {exc}"
            finally:
                db.close()

            if result.status != "success":
                return (
                    f"[text2sql failed: {result.error_type}] "
                    f"{result.error_message or 'no detail'}"
                )
            # Markdown response: SQL + first 10 rows + explanation
            lines = [
                f"**Question**: {question}",
                "",
                f"**SQL**: ```sql\n{result.generated_sql}\n```",
                "",
                f"**Rows returned**: {result.row_count}"
                f"{' (truncated)' if result.truncated else ''}",
            ]
            if result.rows:
                # Render the first few rows as a markdown table
                cols = list(result.columns)[:8]
                lines.append("")
                lines.append("| " + " | ".join(cols) + " |")
                lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
                for row in result.rows[:10]:
                    cells = [
                        str(row.get(c, ""))[:80] if row.get(c) is not None else "—"
                        for c in cols
                    ]
                    lines.append("| " + " | ".join(cells) + " |")
            if result.explanation:
                lines.append("")
                lines.append(f"**Explanation**: {result.explanation}")
            return "\n".join(lines)

        return StructuredTool.from_function(
            func=_run,
            name=f"skill_{skill.id}_text2sql",
            description=(
                skill.description
                or "智能问数:自然语言转 SQL,查 ai_platform 库的业务数据"
            ),
            args_schema=Text2SqlInput,
        )
