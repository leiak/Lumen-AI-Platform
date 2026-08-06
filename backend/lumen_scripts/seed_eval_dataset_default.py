"""M37.1 seed: 1 builtin eval dataset + 30 items.

为 ``/dashboard/eval/datasets`` 准备"开箱即用"的评测集 demo,避免冷启动
时 evaluation dashboard / API 没有 builtin dataset 演示。脚本:

  1. 选 dev DB 中文档最多的 KB(>= 5 条 documents,确保 expected_doc_ids
     能取到真实 doc ID)
  2. 创建 / 更新 1 个 ``tenant_id=NULL`` builtin dataset,``name="demo_baseline"``
  3. 按 5 类(factual / reasoning / multi_hop / keyword_heavy / out_of_scope)
     各写 6 条 item,共 30 条。每条 ``expected_doc_ids`` 都从该 KB 实际
     ``documents.id`` 顺序挑选

Idempotent: 已存在的 builtin dataset ``demo_baseline`` 跳过创建,items
按 ``(dataset_id, query)`` 去重,已存在的 item 不会重复插入。

Usage:
    cd backend && python -m lumen_scripts.seed_eval_dataset_default

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.3
Plan: docs-internal/superpowers/plans/m37-plan.md CP2 T7
"""
import os
import sys
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from lumen_core.database import (  # noqa: E402
    SessionLocal,
    ensure_eval_datasets_table,
)
# 预加载让 Base.metadata / mapper registry 看到所有模型(knowledge.py 里
# KnowledgeBase.tenant 关系需要 Tenant model)。dev DB 直跑场景下,显式
# import 让 SQLAlchemy 一次性把所有 mapper 注册好,避免 "Tenant not found"。
from lumen_models import (  # noqa: E402,F401
    agent,
    agent_team,
    chat,
    customer,
    embedding_call_log,
    external_app,
    image_generation,
    knowledge,
    llm_call_log,
    mcp,
    memory,
    model_config,
    nlp_training,
    notification,
    playbook,
    ppt_task,
    role,
    settings,
    skill,
    skill_marketplace,
    stock_asset,
    subtitle,
    system_config,
    tenant,
    text2sql,
    tts,
    user,
    video,
    vision_training,
    workflow,
    workflow_template,
    wx_publisher,
)
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem  # noqa: E402
from lumen_models.knowledge import Document, KnowledgeBase  # noqa: E402


# ---- 30 queries,5 类 × 6 条 -------------------------------------------------
# 这些 query 是与领域无关的「RAG 行为测试」query —— 用来验证 retrieval /
# answer 指标在 dev DB 上的「端到端是否跑通」,不依赖具体业务知识。
#
# 类说明(跟 lumen_schemas.eval_dataset.EvalDatasetCategory 字面对应):
#   factual         —— 期望单文档直接给答案
#   reasoning       —— 期望多段解释,语义相似度
#   multi_hop       —— 必须跨多文档拼接
#   keyword_heavy   —— 关键词精确匹配
#   out_of_scope    —— KB 不覆盖,期望拒答 / refusal 信号
QUERIES_BY_CATEGORY = {
    "factual": [
        "简要介绍这个知识库的主题",
        "文档的主要分类有哪些",
        "文档的创建时间在哪个区间",
        "这个知识库用什么 embedding 模型",
        "系统的核心功能是什么",
        "知识库支持哪些文档格式",
    ],
    "reasoning": [
        "为什么文档需要分块处理",
        "请解释 chunk_size 和 overlap 的取舍",
        "为什么要做检索增强生成(RAG)",
        "为什么 embedding 模型影响检索质量",
        "解释 BM25 和向量检索的互补关系",
        "为什么需要 rerank 步骤",
    ],
    "multi_hop": [
        "把文档主题和 embedding 模型选型联系起来总结",
        "对比分块策略和检索召回率的因果链",
        "解释 rerank 与上下文长度限制的关系",
        "把模型配置和 prompt 模板的关系串联起来",
        "综合说明检索、rerank、生成三步如何协同",
        "把知识库治理、版本控制和回滚串成一条因果链",
    ],
    "keyword_heavy": [
        "列出 RAG 评估涉及的所有指标名称",
        "列出支持的所有模型 provider 关键字",
        "列出 chunking 的关键参数名",
        "列出检索指标的关键计算公式名",
        "列出系统中常见的英文错误码关键词",
        "列出知识库的所有可见性过滤关键字",
    ],
    "out_of_scope": [
        "今天北京天气怎么样",
        "请推荐一家上海的本帮菜餐厅",
        "计算 (1+2+3+...+100)",
        "写一首七言绝句",
        "翻译一句话成英文",
        "用 Python 写个快速排序",
    ],
}


def pick_kb(db: Session) -> Optional[KnowledgeBase]:
    """选 dev DB 中文档数 >= 5 的 KB,优先选文档最多的那个。

    过滤掉 test fixture KB(命名通常带 ``test-kb-XXXXXXXX`` / ``test_kb_XXX``
    这种 uuid 后缀),让 demo baseline 绑到生产风格 KB,而不是被 M27/M31 测试
    fixture 占据。dev DB 没合适 KB → 返回 None。
    """
    import re
    test_kb_pattern = re.compile(r"test[-_]kb[-_]", re.IGNORECASE)
    rows = (
        db.query(KnowledgeBase, func.count(Document.id).label("doc_count"))
        .outerjoin(Document, Document.knowledge_base_id == KnowledgeBase.id)
        .group_by(KnowledgeBase.id)
        .having(func.count(Document.id) >= 5)
        .order_by(func.count(Document.id).desc())
        .all()
    )
    # 第一遍:跳过 test fixture
    for kb, _ in rows:
        if not test_kb_pattern.search(kb.name or ""):
            return kb
    # 全是 test fixture → 兜底取最多的那个(总比 None 强,demo 至少能跑)
    if rows:
        return rows[0][0]
    return None


def pick_doc_ids(db: Session, kb_id: int, limit: int = 30) -> List[int]:
    """从指定 KB 按 id 升序取前 N 个 doc id,用于批量 assign expected_doc_ids。"""
    rows = (
        db.query(Document.id)
        .filter(Document.knowledge_base_id == kb_id)
        .order_by(Document.id.asc())
        .limit(limit)
        .all()
    )
    return [r[0] for r in rows]


def upsert_builtin_dataset(
    db: Session, *, kb_id: int, name: str = "demo_baseline"
) -> EvalDataset:
    """Get-or-create 1 builtin dataset(tenant_id=NULL)。

    已有同名 builtin dataset → 复用(返回 row);没有则 INSERT。
    """
    existing = (
        db.query(EvalDataset)
        .filter(EvalDataset.tenant_id.is_(None), EvalDataset.name == name)
        .first()
    )
    if existing:
        # 校验 kb_id 是否一致;不一致 → 更新(从 demo_baseline 的语义看,绑 KB
        # 是 evaluation 的核心;KB 换了应同步,否则评测指标失效)
        if existing.kb_id != kb_id:
            existing.kb_id = kb_id  # type: ignore[assignment]
        return existing
    row = EvalDataset(
        kb_id=kb_id,
        tenant_id=None,
        name=name,
        description=(
            "M37.1 ship demo baseline dataset — 30 queries across 5 categories "
            "(factual / reasoning / multi_hop / keyword_heavy / out_of_scope), "
            "每条 expected_doc_ids 从绑定 KB 的真实 documents 取。供 dashboard "
            "演示 + M37.2 评测运行器做冒烟测试用。"
        ),
        source="manual",
        is_active=1,
        created_by=None,
    )
    db.add(row)
    db.flush()
    return row


def upsert_item(
    db: Session,
    *,
    dataset_id: int,
    query: str,
    category: str,
    expected_doc_ids: List[int],
    difficulty: str,
    notes: str,
) -> None:
    """按 (dataset_id, query) 去重;新 query 才 INSERT。"""
    existing = (
        db.query(EvalDatasetItem)
        .filter(EvalDatasetItem.dataset_id == dataset_id)
        .filter(EvalDatasetItem.query == query)
        .first()
    )
    if existing:
        return
    db.add(
        EvalDatasetItem(
            dataset_id=dataset_id,
            query=query,
            expected_doc_ids=expected_doc_ids,
            expected_answer=None,
            answer_keywords=None,
            category=category,
            difficulty=difficulty,
            notes=notes,
        )
    )


def main() -> None:
    ensure_eval_datasets_table()
    print("M37.1 seed — writing 1 builtin eval dataset + 30 items...")
    db: Session = SessionLocal()
    try:
        kb = pick_kb(db)
        if kb is None:
            print(
                "FAILED: dev DB has no KB with >=5 documents. "
                "Pick a KB to ingest first, then re-run."
            )
            sys.exit(2)

        doc_ids = pick_doc_ids(db, kb.id, limit=30)
        if len(doc_ids) < 1:
            print(
                f"FAILED: KB #{kb.id} ({kb.name}) has 0 docs; cannot seed."
            )
            sys.exit(2)
        if len(doc_ids) < 5:
            print(
                f"  WARNING: KB #{kb.id} ({kb.name}) has only {len(doc_ids)} "
                "docs; expected_doc_ids 会循环复用,不影响 seed 跑通。"
            )

        ds = upsert_builtin_dataset(db, kb_id=kb.id)
        print(f"  KB = #{kb.id} ({kb.name}); dataset = #{ds.id} ({ds.name})")

        # 难度分配:
        #   factual / keyword_heavy → easy
        #   reasoning               → medium
        #   multi_hop / out_of_scope → hard (out_of_scope 故意难,评测拒答能力)
        difficulty_map = {
            "factual": "easy",
            "reasoning": "medium",
            "multi_hop": "hard",
            "keyword_heavy": "easy",
            "out_of_scope": "hard",
        }

        total_items = 0
        # 轮询 doc_ids 给每条 item 分 expected_doc_ids —— 每条 2 个 doc,最后
        # 一类(out_of_scope)空 list,期望 RAG 拒答
        idx = 0
        for category, queries in QUERIES_BY_CATEGORY.items():
            for q in queries:
                if category == "out_of_scope":
                    # out_of_scope 期望 KB 不命中 → 空 doc ids,answer-quality
                    # 应检 refusal
                    assign_docs: List[int] = []
                else:
                    # 取 2 个 doc(从头轮询)
                    a = doc_ids[idx % len(doc_ids)]
                    b = doc_ids[(idx + 1) % len(doc_ids)]
                    assign_docs = [a, b]
                    idx += 2
                upsert_item(
                    db,
                    dataset_id=ds.id,
                    query=q,
                    category=category,
                    expected_doc_ids=assign_docs,
                    difficulty=difficulty_map[category],
                    notes=f"M37.1 demo seed — category={category}",
                )
                total_items += 1

        db.commit()

        # 输出 ship checklist 摘要
        item_count = (
            db.query(func.count(EvalDatasetItem.id))
            .filter(EvalDatasetItem.dataset_id == ds.id)
            .scalar()
        )
        print(
            f"OK — committed {total_items} new items; dataset #{ds.id} now "
            f"has {item_count} items total. Verify with:\n"
            f"  curl -H 'Authorization: Bearer <token>' "
            f"http://localhost:11335/api/v1/eval/datasets/{ds.id}"
        )
    except Exception as exc:
        db.rollback()
        print(f"FAILED: {type(exc).__name__}: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()