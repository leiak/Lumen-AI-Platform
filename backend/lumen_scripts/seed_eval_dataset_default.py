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
# 每条带 expected_answer(参考答案)+ answer_keywords(关键词命中率用):
#   - expected_answer 供人工 review / 未来 answer-similarity 指标用
#   - answer_keywords 直接喂 metrics.keyword_hit_rate(substring 匹配),
#     所以只挑「答对了几乎必然出现」的词,避免假阴性
#   - out_of_scope 类的关键词是**拒答信号**词 —— 命中率越高说明拒答越干净
#
# 类说明(跟 lumen_schemas.eval_dataset.EvalDatasetCategory 字面对应):
#   factual         —— 期望单文档直接给答案
#   reasoning       —— 期望多段解释,语义相似度
#   multi_hop       —— 必须跨多文档拼接
#   keyword_heavy   —— 关键词精确匹配
#   out_of_scope    —— KB 不覆盖,期望拒答 / refusal 信号
QUERIES_BY_CATEGORY = {
    "factual": [
        {
            "query": "简要介绍这个知识库的主题",
            "expected_answer": "该知识库围绕一个主题域收录文档,内容覆盖其核心概念与使用说明。",
            "answer_keywords": ["知识库"],
        },
        {
            "query": "文档的主要分类有哪些",
            "expected_answer": "文档按主题/用途划分为若干类别,每篇文档归属一个分类。",
            "answer_keywords": ["分类"],
        },
        {
            "query": "文档的创建时间在哪个区间",
            "expected_answer": "文档创建时间集中在知识库建立之后的一段时间区间内。",
            "answer_keywords": ["时间"],
        },
        {
            "query": "这个知识库用什么 embedding 模型",
            "expected_answer": "知识库在创建时锁定了一个 embedding 模型配置,所有分块都用它向量化。",
            "answer_keywords": ["embedding", "模型"],
        },
        {
            "query": "系统的核心功能是什么",
            "expected_answer": "核心功能是把文档解析分块、向量化入库,并在提问时检索相关片段生成答案。",
            "answer_keywords": ["检索"],
        },
        {
            "query": "知识库支持哪些文档格式",
            "expected_answer": "支持常见的文本类格式,例如 PDF、Word(docx)、Markdown、纯文本等。",
            "answer_keywords": ["格式"],
        },
    ],
    "reasoning": [
        {
            "query": "为什么文档需要分块处理",
            "expected_answer": "因为模型上下文长度有限,且整篇文档语义过杂;分块能让检索定位到真正相关的片段。",
            "answer_keywords": ["分块", "上下文"],
        },
        {
            "query": "请解释 chunk_size 和 overlap 的取舍",
            "expected_answer": "chunk_size 越大上下文越完整但检索越不精准;overlap 用来避免句子被切断丢失语义,代价是存储和计算冗余。",
            "answer_keywords": ["chunk_size"],
        },
        {
            "query": "为什么要做检索增强生成(RAG)",
            "expected_answer": "让模型基于检索到的真实文档作答,减少幻觉,并且无需重新训练就能接入最新的私有知识。",
            "answer_keywords": ["检索"],
        },
        {
            "query": "为什么 embedding 模型影响检索质量",
            "expected_answer": "embedding 决定了文本在向量空间的位置,语义表达能力不足会让相关文档的相似度算不准,直接拉低召回。",
            "answer_keywords": ["embedding"],
        },
        {
            "query": "解释 BM25 和向量检索的互补关系",
            "expected_answer": "BM25 擅长关键词精确匹配,向量检索擅长语义近似;混合检索能同时覆盖专有名词命中和同义表达。",
            "answer_keywords": ["BM25"],
        },
        {
            "query": "为什么需要 rerank 步骤",
            "expected_answer": "初筛召回的候选排序较粗,rerank 用更强的模型对少量候选精排,把最相关的片段顶到前面。",
            "answer_keywords": ["rerank"],
        },
    ],
    "multi_hop": [
        {
            "query": "把文档主题和 embedding 模型选型联系起来总结",
            "expected_answer": "文档所属领域决定了词汇分布,选 embedding 模型时要匹配该领域和语种,否则向量表达失真影响检索。",
            "answer_keywords": ["embedding"],
        },
        {
            "query": "对比分块策略和检索召回率的因果链",
            "expected_answer": "分块粒度决定每个向量承载的语义量,粒度过粗会稀释相关信号、过细会切断上下文,两者都会降低召回率。",
            "answer_keywords": ["召回"],
        },
        {
            "query": "解释 rerank 与上下文长度限制的关系",
            "expected_answer": "上下文长度限制了能塞进 prompt 的片段数量,rerank 保证在有限名额里放进最相关的片段。",
            "answer_keywords": ["rerank", "上下文"],
        },
        {
            "query": "把模型配置和 prompt 模板的关系串联起来",
            "expected_answer": "模型配置决定能力与上下文预算,prompt 模板要据此裁剪上下文条数和指令长度,两者需配套调整。",
            "answer_keywords": ["prompt"],
        },
        {
            "query": "综合说明检索、rerank、生成三步如何协同",
            "expected_answer": "检索先粗筛出候选片段,rerank 对候选精排取前几条,生成阶段只依据这些片段作答。",
            "answer_keywords": ["检索", "生成"],
        },
        {
            "query": "把知识库治理、版本控制和回滚串成一条因果链",
            "expected_answer": "治理规范决定文档何时更新,版本控制记录每次变更,出现质量回退时可回滚到上一个可用版本。",
            "answer_keywords": ["版本"],
        },
    ],
    "keyword_heavy": [
        {
            "query": "列出 RAG 评估涉及的所有指标名称",
            "expected_answer": "检索指标有 Hit@K、MRR、NDCG@K、Recall@K;答案指标有 faithfulness、answer_relevancy、keyword_hit_rate。",
            "answer_keywords": ["MRR", "NDCG"],
        },
        {
            "query": "列出支持的所有模型 provider 关键字",
            "expected_answer": "常见 provider 关键字包括 ollama、openai 等。",
            "answer_keywords": ["ollama"],
        },
        {
            "query": "列出 chunking 的关键参数名",
            "expected_answer": "关键参数是 chunk_size 和 chunk_overlap(以及分隔符 separators)。",
            "answer_keywords": ["chunk_size", "overlap"],
        },
        {
            "query": "列出检索指标的关键计算公式名",
            "expected_answer": "Hit@K、MRR(平均倒数排名)、NDCG@K(归一化折损累计增益)、Recall@K。",
            "answer_keywords": ["MRR"],
        },
        {
            "query": "列出系统中常见的英文错误码关键词",
            "expected_answer": "常见的有 not_found、unauthorized、forbidden、validation_error、internal_error。",
            "answer_keywords": ["not_found"],
        },
        {
            "query": "列出知识库的所有可见性过滤关键字",
            "expected_answer": "按 tenant_id 做租户隔离,按 kb_id 做知识库隔离;tenant_id 为空表示全局可见。",
            "answer_keywords": ["tenant_id", "kb_id"],
        },
    ],
    # out_of_scope 的 expected_answer 就是拒答本身 —— answer_keywords 挑
    # 拒答信号词,keyword_hit_rate 高 = 模型老实拒答,低 = 开始瞎编。
    "out_of_scope": [
        {
            "query": "今天北京天气怎么样",
            "expected_answer": "根据知识库内容无法回答该问题。",
            "answer_keywords": ["无法回答"],
        },
        {
            "query": "请推荐一家上海的本帮菜餐厅",
            "expected_answer": "根据知识库内容无法回答该问题。",
            "answer_keywords": ["无法回答"],
        },
        {
            "query": "计算 (1+2+3+...+100)",
            "expected_answer": "根据知识库内容无法回答该问题。",
            "answer_keywords": ["无法回答"],
        },
        {
            "query": "写一首七言绝句",
            "expected_answer": "根据知识库内容无法回答该问题。",
            "answer_keywords": ["无法回答"],
        },
        {
            "query": "翻译一句话成英文",
            "expected_answer": "根据知识库内容无法回答该问题。",
            "answer_keywords": ["无法回答"],
        },
        {
            "query": "用 Python 写个快速排序",
            "expected_answer": "根据知识库内容无法回答该问题。",
            "answer_keywords": ["无法回答"],
        },
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
    expected_answer: Optional[str],
    answer_keywords: Optional[List[str]],
    difficulty: str,
    notes: str,
) -> str:
    """按 (dataset_id, query) 去重;新 query INSERT,老 query 补答案字段。

    Returns:
        ``"inserted"`` / ``"updated"`` / ``"skipped"`` —— 供 main() 统计。

    为什么老行也要动:M37.1 首版 seed 写进去的 30 条 ``expected_answer``
    和 ``answer_keywords`` 全是 NULL,导致 M37.2 的 keyword_hit_rate 恒 0。
    这里只在字段为空时补,已经人工编辑过的 item 不覆盖。
    """
    existing = (
        db.query(EvalDatasetItem)
        .filter(EvalDatasetItem.dataset_id == dataset_id)
        .filter(EvalDatasetItem.query == query)
        .first()
    )
    if existing:
        changed = False
        if existing.expected_answer is None and expected_answer:
            existing.expected_answer = expected_answer  # type: ignore[assignment]
            changed = True
        if not existing.answer_keywords and answer_keywords:
            existing.answer_keywords = answer_keywords  # type: ignore[assignment]
            changed = True
        return "updated" if changed else "skipped"
    db.add(
        EvalDatasetItem(
            dataset_id=dataset_id,
            query=query,
            expected_doc_ids=expected_doc_ids,
            expected_answer=expected_answer,
            answer_keywords=answer_keywords,
            category=category,
            difficulty=difficulty,
            notes=notes,
        )
    )
    return "inserted"


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
        stats = {"inserted": 0, "updated": 0, "skipped": 0}
        # 轮询 doc_ids 给每条 item 分 expected_doc_ids —— 每条 2 个 doc,最后
        # 一类(out_of_scope)空 list,期望 RAG 拒答
        idx = 0
        for category, entries in QUERIES_BY_CATEGORY.items():
            for entry in entries:
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
                outcome = upsert_item(
                    db,
                    dataset_id=ds.id,
                    query=entry["query"],  # type: ignore[arg-type]
                    category=category,
                    expected_doc_ids=assign_docs,
                    expected_answer=entry.get("expected_answer"),  # type: ignore[arg-type]
                    answer_keywords=entry.get("answer_keywords"),  # type: ignore[arg-type]
                    difficulty=difficulty_map[category],
                    notes=f"M37.1 demo seed — category={category}",
                )
                stats[outcome] += 1
                total_items += 1

        db.commit()

        # 输出 ship checklist 摘要
        item_count = (
            db.query(func.count(EvalDatasetItem.id))
            .filter(EvalDatasetItem.dataset_id == ds.id)
            .scalar()
        )
        print(
            f"OK — {stats['inserted']} inserted / {stats['updated']} updated "
            f"(补 expected_answer + answer_keywords) / {stats['skipped']} "
            f"unchanged,共处理 {total_items} 条;dataset #{ds.id} now "
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