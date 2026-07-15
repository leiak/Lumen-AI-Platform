"""Seed the workflow template marketplace with curated starter templates.

M30 ship follow-up (2026-06-18): M30b shipped the browse / preview /
import UI in ``frontend/app/dashboard/workflow/templates/page.tsx``,
but the dev DB had zero ``workflow_templates`` rows — the marketplace
opened empty. This script populates it with 8 ready-to-browse
templates covering the common entry points (chat, RAG, HTTP, control
flow, processing, advanced chains). Users import the template and
edit the per-node ``config`` in the designer before running.

Idempotent: re-running on a seeded DB is a no-op (templates are
matched by ``(tenant_id, name)``). Author is the first superuser
found in the DB (the bootstrap admin, id=1). Tenant is set to NULL so
templates are visible across all tenants — the platform's template
model is "public, cross-tenant" (see models/workflow_template.py
docstring).

Run standalone:
    cd backend && python -m scripts.seed_workflow_templates

Run from init_dev_db.py (called automatically on every Docker reset):
    from scripts.seed_workflow_templates import seed_workflow_templates
    seed_workflow_templates()
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, List, Tuple

# Make ``app`` importable when invoked as a module.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from sqlalchemy import select  # noqa: E402

from lumen_core.database import SessionLocal  # noqa: E402
# Mirror init_dev_db.py: register every model so FK resolution works
# even when this script is run as `python -m scripts.seed_workflow_templates`
# (uvicorn boot-time imports in main.py don't fire in that case).
from lumen_models import (  # noqa: E401,F401
    tenant, user, role, settings, agent, agent_team, chat, knowledge,
    memory, mcp, model_config, notification, skill, skill_marketplace,
    workflow, workflow_template, image_generation, nlp_training,
    vision_training, external_app,
)
from lumen_models.user import User  # noqa: E402
from lumen_models.workflow_template import WorkflowTemplate  # noqa: E402

logger = logging.getLogger("seed_workflow_templates")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------
# Each entry is a curated starter. ``nodes`` and ``edges`` are
# ``WorkflowDefinition``-shaped (schemas/workflow.py:26-28). The
# ``config`` dicts are intentionally minimal-viable — users edit them
# in the designer after import. Keys like ``model_config_id`` /
# ``agent_id`` / ``kb_id`` are left out on purpose: those are
# environment-specific and we don't want to bind a seed template to a
# particular row id that won't exist on another tenant's DB.
# ---------------------------------------------------------------------------


def _node(node_id: str, node_type: str, config: Dict[str, Any], x: float = 0, y: float = 0) -> Dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "config": config,
        "position": {"x": x, "y": y},
    }


def _edge(edge_id: str, source: str, target: str, condition: str | None = None) -> Dict[str, Any]:
    e: Dict[str, Any] = {"id": edge_id, "source": source, "target": target}
    if condition:
        e["condition"] = condition
    return e


_TEMPLATES: List[Dict[str, Any]] = [
    # 1. Simple LLM chat — the canonical entry point. start → input → llm → output → end
    {
        "name": "简单 LLM 对话",
        "description": "入门级模板: 接收用户输入,调用 LLM 生成回复。导入后在 Inspector 里选择具体的 ModelConfig 即可运行。",
        "category": "chat",
        "tags": ["入门", "llm", "chat"],
        "definition": {
            "nodes": [
                _node("start", "start", {}, 0, 0),
                _node("input", "input", {"variables": [{"name": "user_input", "type": "string"}]}, 0, 80),
                _node("llm_1", "llm", {
                    "title": "简单回复",
                    "system_prompt": "你是一个乐于助人的助手。",
                    "prompt_template": "用户说: {{ user_input }}\n请给出友好的回复。",
                }, 0, 160),
                _node("output", "output", {"variable_name": "response"}, 0, 240),
                _node("end", "end", {}, 0, 320),
            ],
            "edges": [
                _edge("e1", "start", "input"),
                _edge("e2", "input", "llm_1"),
                _edge("e3", "llm_1", "output"),
                _edge("e4", "output", "end"),
            ],
        },
    },
    # 2. RAG knowledge-base QA — the most-requested template.
    {
        "name": "RAG 知识库问答",
        "description": "经典 RAG 场景: 先从知识库检索相关文档,再让 LLM 基于检索结果回答。导入后需在 Inspector 里选 KB id 与 ModelConfig。",
        "category": "rag",
        "tags": ["rag", "知识库", "qa"],
        "definition": {
            "nodes": [
                _node("start", "start", {}, 0, 0),
                _node("input", "input", {"variables": [{"name": "question", "type": "string"}]}, 0, 80),
                _node("kb_retrieve", "knowledge_retrieval", {
                    "title": "知识库检索",
                    "kb_id": None,  # user fills in
                    "query_template": "{{ question }}",
                    "top_k": 5,
                }, 0, 160),
                _node("llm_1", "llm", {
                    "title": "基于检索结果回答",
                    "system_prompt": "你是一个严谨的助手,请仅基于提供的参考资料回答问题。如果资料不足以回答,直接说「资料不足」。",
                    "prompt_template": "用户问题: {{ question }}\n\n参考资料:\n{{ kb_retrieve.chunks }}\n\n请给出回答。",
                }, 0, 240),
                _node("output", "output", {"variable_name": "answer"}, 0, 320),
                _node("end", "end", {}, 0, 400),
            ],
            "edges": [
                _edge("e1", "start", "input"),
                _edge("e2", "input", "kb_retrieve"),
                _edge("e3", "input", "llm_1"),  # llm_1 needs question too
                _edge("e4", "kb_retrieve", "llm_1"),
                _edge("e5", "llm_1", "output"),
                _edge("e6", "output", "end"),
            ],
        },
    },
    # 3. HTTP API call — call an external REST endpoint, then format the response.
    {
        "name": "HTTP API 调用",
        "description": "调用外部 HTTP API 获取数据,用 Jinja2 模板格式化输出。导入后在 HTTP 节点填 URL/Method,在模板节点调整字段。",
        "category": "integration",
        "tags": ["http", "api", "integration"],
        "definition": {
            "nodes": [
                _node("start", "start", {}, 0, 0),
                _node("input", "input", {"variables": [{"name": "city", "type": "string"}]}, 0, 80),
                _node("http_1", "http", {
                    "title": "查询天气",
                    "method": "GET",
                    "url": "https://api.example.com/weather",
                    "headers": {},
                    "query": {"city": "{{ city }}"},
                }, 0, 160),
                _node("fmt", "template_transform", {
                    "title": "格式化天气信息",
                    "template": "{{ city }} 当前天气: {{ http_1.body.temp }}°C, {{ http_1.body.desc }}",
                }, 0, 240),
                _node("output", "output", {"variable_name": "weather_text"}, 0, 320),
                _node("end", "end", {}, 0, 400),
            ],
            "edges": [
                _edge("e1", "start", "input"),
                _edge("e2", "input", "http_1"),
                _edge("e2b", "input", "fmt"),
                _edge("e3", "http_1", "fmt"),
                _edge("e4", "fmt", "output"),
                _edge("e5", "output", "end"),
            ],
        },
    },
    # 4. Conditional branching — classify input then take different paths.
    {
        "name": "条件分支客服路由",
        "description": "用 LLM 判断用户问题属于「售前」还是「售后」,分别走两条不同分支。导入后需给两个 LLM 节点选 ModelConfig,并在 Condition 节点配置 case 表达式。",
        "category": "control",
        "tags": ["condition", "routing", "分类"],
        "definition": {
            "nodes": [
                _node("start", "start", {}, 0, 0),
                _node("input", "input", {"variables": [{"name": "user_query", "type": "string"}]}, 0, 80),
                _node("classify", "question_classifier", {
                    "title": "意图分类",
                    "model_config_id": None,  # user fills in
                    "question": "{{ user_query }}",
                    "categories": [
                        {"name": "presale", "description": "售前咨询: 价格、功能、购买建议"},
                        {"name": "aftersale", "description": "售后问题: 使用、故障、退换货"},
                    ],
                }, 0, 160),
                _node("llm_presale", "llm", {
                    "title": "售前回复",
                    "system_prompt": "你是售前顾问,回答用户关于产品功能、价格、购买建议的问题。",
                    "prompt_template": "用户问题: {{ user_query }}",
                }, -200, 240),
                _node("llm_aftersale", "llm", {
                    "title": "售后回复",
                    "system_prompt": "你是售后工程师,帮助用户解决使用问题,排查故障,办理退换货。",
                    "prompt_template": "用户问题: {{ user_query }}",
                }, 200, 240),
                _node("output", "output", {"variable_name": "reply"}, 0, 320),
                _node("end", "end", {}, 0, 400),
            ],
            "edges": [
                _edge("e1", "start", "input"),
                _edge("e2", "input", "classify"),
                _edge("e2b", "input", "llm_presale"),
                _edge("e2c", "input", "llm_aftersale"),
                _edge("e3", "classify", "llm_presale", condition="category==presale"),
                _edge("e4", "classify", "llm_aftersale", condition="category==aftersale"),
                _edge("e5", "llm_presale", "output"),
                _edge("e6", "llm_aftersale", "output"),
                _edge("e7", "output", "end"),
            ],
        },
    },
    # 5. Code processing — sandboxed Python data transformation.
    {
        "name": "代码数据处理",
        "description": "用受限沙箱里的 Python 脚本对输入数据做计算/转换。适合批量处理、结构化数据清洗。导入后在 Code 节点编辑 Python。",
        "category": "processing",
        "tags": ["code", "sandbox", "数据处理"],
        "definition": {
            "nodes": [
                _node("start", "start", {}, 0, 0),
                _node("input", "input", {"variables": [{"name": "numbers", "type": "list"}]}, 0, 80),
                _node("code_1", "code", {
                    "title": "统计与排序",
                    "code": (
                        "# input_data 包含上游变量,这里取 numbers 列表\n"
                        "nums = input_data.get('numbers', [])\n"
                        "result = {\n"
                        "  'count': len(nums),\n"
                        "  'sum': sum(nums),\n"
                        "  'avg': sum(nums) / len(nums) if nums else 0,\n"
                        "  'sorted_desc': sorted(nums, reverse=True),\n"
                        "}\n"
                    ),
                }, 0, 160),
                _node("fmt", "template_transform", {
                    "title": "格式化统计结果",
                    "template": "共 {{ code_1.result.count }} 个数, 总和 {{ code_1.result.sum }}, 平均 {{ code_1.result.avg }}",
                }, 0, 240),
                _node("output", "output", {"variable_name": "summary"}, 0, 320),
                _node("end", "end", {}, 0, 400),
            ],
            "edges": [
                _edge("e1", "start", "input"),
                _edge("e2", "input", "code_1"),
                _edge("e3", "code_1", "fmt"),
                _edge("e4", "fmt", "output"),
                _edge("e5", "output", "end"),
            ],
        },
    },
    # 6. Template rendering — pure Jinja2 templating, no LLM.
    {
        "name": "模板渲染",
        "description": "纯 Jinja2 模板渲染,不调用 LLM。适合做通知、报告、邮件、Slack 消息的格式化。",
        "category": "processing",
        "tags": ["template", "jinja2", "通知"],
        "definition": {
            "nodes": [
                _node("start", "start", {}, 0, 0),
                _node("input", "input", {"variables": [
                    {"name": "user_name", "type": "string"},
                    {"name": "order_id", "type": "string"},
                    {"name": "amount", "type": "number"},
                ]}, 0, 80),
                _node("fmt", "template_transform", {
                    "title": "订单通知模板",
                    "template": (
                        "尊敬的 {{ user_name }}:\n\n"
                        "您的订单 {{ order_id }} 已提交,金额 ¥{{ amount }}。\n"
                        "我们会在 24 小时内处理,感谢您的信任!"
                    ),
                }, 0, 160),
                _node("output", "output", {"variable_name": "notification_text"}, 0, 240),
                _node("end", "end", {}, 0, 320),
            ],
            "edges": [
                _edge("e1", "start", "input"),
                _edge("e2", "input", "fmt"),
                _edge("e3", "fmt", "output"),
                _edge("e4", "output", "end"),
            ],
        },
    },
    # 7. Multi-step LLM chain — first LLM generates an outline, second LLM expands it.
    {
        "name": "多步推理链",
        "description": "两阶段 LLM: 第一阶段生成大纲,第二阶段基于大纲展开。适合长文写作、研究分析、复杂推理。",
        "category": "advanced",
        "tags": ["llm", "chain", "推理"],
        "definition": {
            "nodes": [
                _node("start", "start", {}, 0, 0),
                _node("input", "input", {"variables": [{"name": "topic", "type": "string"}]}, 0, 80),
                _node("llm_outline", "llm", {
                    "title": "生成大纲",
                    "system_prompt": "你是一个结构化思考者,擅长把复杂主题拆成清晰的大纲。",
                    "prompt_template": "主题: {{ topic }}\n请输出 3-5 个要点的简短大纲,每点一行。",
                }, 0, 160),
                _node("llm_expand", "llm", {
                    "title": "展开成文",
                    "system_prompt": "你是一个专业写手,根据大纲写一篇结构清晰、语言流畅的文章。",
                    "prompt_template": "主题: {{ topic }}\n\n大纲:\n{{ llm_outline.response }}\n\n请基于以上大纲写一篇 500 字左右的文章。",
                }, 0, 240),
                _node("output", "output", {"variable_name": "article"}, 0, 320),
                _node("end", "end", {}, 0, 400),
            ],
            "edges": [
                _edge("e1", "start", "input"),
                _edge("e2", "input", "llm_outline"),
                _edge("e2b", "input", "llm_expand"),
                _edge("e3", "llm_outline", "llm_expand"),
                _edge("e4", "llm_expand", "output"),
                _edge("e5", "output", "end"),
            ],
        },
    },
    # 8. Parameter extraction — extract structured fields from unstructured text.
    {
        "name": "参数提取",
        "description": "用 LLM 从一段非结构化文本里提取结构化字段(姓名、电话、邮箱等)。导入后配置 ModelConfig + 输出 schema。",
        "category": "advanced",
        "tags": ["parameter", "extraction", "structured"],
        "definition": {
            "nodes": [
                _node("start", "start", {}, 0, 0),
                _node("input", "input", {"variables": [{"name": "raw_text", "type": "string"}]}, 0, 80),
                _node("extract", "parameter_extractor", {
                    "title": "提取联系人信息",
                    "model_config_id": None,  # user fills in
                    "text": "{{ raw_text }}",
                    "parameters": [
                        {"name": "name", "description": "人名", "type": "string", "required": True},
                        {"name": "phone", "description": "电话号码", "type": "string", "required": False},
                        {"name": "email", "description": "电子邮箱", "type": "string", "required": False},
                    ],
                }, 0, 160),
                _node("fmt", "template_transform", {
                    "title": "汇总提取结果",
                    "template": "提取结果: 姓名={{ extract.name }}; 电话={{ extract.phone | default('未提供') }}; 邮箱={{ extract.email | default('未提供') }}",
                }, 0, 240),
                _node("output", "output", {"variable_name": "extracted"}, 0, 320),
                _node("end", "end", {}, 0, 400),
            ],
            "edges": [
                _edge("e1", "start", "input"),
                _edge("e2", "input", "extract"),
                _edge("e3", "extract", "fmt"),
                _edge("e4", "fmt", "output"),
                _edge("e5", "output", "end"),
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Seed entry point
# ---------------------------------------------------------------------------


def _pick_author(db) -> Tuple[int, str, int | None]:
    """Pick a sensible author for cross-tenant marketplace templates.

    Falls back to the first superuser (the bootstrap admin). Returns
    ``(user_id, author_name, tenant_id)`` where ``tenant_id`` is the
    author's tenant — used to set ``WorkflowTemplate.tenant_id`` so the
    seed is auditable to the bootstrap admin.
    """
    admin = db.scalar(
        select(User).where(User.is_superuser == True).order_by(User.id.asc())  # noqa: E712
    )
    if admin is None:
        # No superuser at all (shouldn't happen on a bootstrap DB).
        # Fall back to any user.
        admin = db.scalar(select(User).order_by(User.id.asc()))
    if admin is None:
        raise RuntimeError(
            "No user exists in the DB; cannot author seed templates. "
            "Run init_dev_db.py first or ensure at least one user exists."
        )
    return (
        admin.id,
        admin.full_name or admin.username,
        admin.tenant_id,
    )


def seed_workflow_templates() -> Tuple[int, int]:
    """Insert all 8 starter templates. Idempotent.

    Returns ``(inserted_count, skipped_count)``. Called from
    ``init_dev_db.py`` after the admin user is created. Safe to call
    on a DB that already has the rows — we match by ``(name)`` (the
    name is unique within the marketplace, not the tenant_id, because
    templates are cross-tenant).
    """
    db = SessionLocal()
    inserted = 0
    skipped = 0
    try:
        author_id, author_name, author_tenant = _pick_author(db)
        for tpl in _TEMPLATES:
            existing = db.scalar(
                select(WorkflowTemplate).where(WorkflowTemplate.name == tpl["name"])
            )
            if existing is not None:
                logger.info("  skip %r (already exists, id=%s)", tpl["name"], existing.id)
                skipped += 1
                continue
            row = WorkflowTemplate(
                name=tpl["name"],
                description=tpl["description"],
                category=tpl["category"],
                tags=tpl["tags"],
                workflow_json=tpl["definition"],
                author_id=author_id,
                author_name=author_name,
                tenant_id=author_tenant,  # nullable column; set when known
                downloads=0,
            )
            db.add(row)
            inserted += 1
            logger.info("  + %r (category=%s, tags=%s)", tpl["name"], tpl["category"], tpl["tags"])
        db.commit()
    finally:
        db.close()
    return inserted, skipped


def main() -> int:
    print("=== seed_workflow_templates ===")
    inserted, skipped = seed_workflow_templates()
    print(f"Done. inserted={inserted} skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
