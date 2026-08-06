"""M37.2 — RAG 评测指标。

两节:

1. **检索指标**(本文件,纯数学):hit_at_k / mrr / ndcg_at_k / recall_at_k
   + aggregate(mean/p50/p95/count)。不需要 LLM,跑完一条 item 立即算。
2. **答案指标**(T11)+ LLM judge(judge.py):keyword_hit_rate(规则)/
   faithfulness / answer_relevancy(0/1/2 三档 judge 输出)。

二元相关性 NDCG 实现简化版 —— retrieved 里命中 expected = relevance 1,
未命中 = relevance 0。DCG = sum(rel_i / log2(rank+2))。IDCG 用「理想
顺序:所有 expected 排在最前」算 —— 二元场景下 IDCG = sum(1/log2(i+2))
i=0..min(|expected|, k)-1。这是 ragas / sklearn ndcg_score 的二元特例。

边界处理原则(避免除零 / 静默崩):

- 空 expected → 所有指标返 0.0(没有目标,谈不上「命中」)
- k=0 → hit/recall 返 0.0;ndcg 返 0.0(IDCG=0)
- k > len(retrieved) → 截到 len(retrieved)
- aggregate 空列表 → mean/p50/p95 = 0.0,count = 0

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2 检索指标
Plan: docs-internal/superpowers/plans/m37-plan.md CP3 T10
"""
from __future__ import annotations

import math
import os
from functools import lru_cache
from typing import Dict, Iterable, List, Optional


# ---------------------------------------------------------------------------
# 检索指标(hit / mrr / ndcg / recall)
# ---------------------------------------------------------------------------


def hit_at_k(retrieved: List[int], expected: List[int], k: int) -> float:
    """top-k 是否命中至少一个 expected doc。

    Args:
        retrieved: 检索结果 doc_id 列表(已按 score 降序)。
        expected: 期望相关 doc_id 集合(顺序无关)。
        k: top-k 截断;k <= 0 视为 0(无可用 slot)。

    Returns:
        1.0 命中 / 0.0 未命中。空 expected 也返 0.0(没有目标)。

    算法:retrieved[:k] 与 expected 集合取交集,非空即 1.0。
    """
    if k <= 0 or not expected:
        return 0.0
    if not retrieved:
        return 0.0
    expected_set = set(expected)
    for doc_id in retrieved[:k]:
        if doc_id in expected_set:
            return 1.0
    return 0.0


def mrr(retrieved: List[int], expected: List[int]) -> float:
    """Mean Reciprocal Rank —— 第一个 expected 的倒数排名(0 表示未命中)。

    Args:
        retrieved: 同 hit_at_k。
        expected: 同 hit_at_k。

    Returns:
        1/(rank+1);rank 从 0 起。未命中返 0.0。

    跟 hit_at_k 的差别:hit 只关心「top-k 里有 / 没有」,mrr 看「第一个
    期望 doc 出现在第几名」 —— 对 rerank 调参更敏感(第 1 vs 第 3 区别
    巨大,hit@10 体现不出)。
    """
    if not retrieved or not expected:
        return 0.0
    expected_set = set(expected)
    for rank, doc_id in enumerate(retrieved):
        if doc_id in expected_set:
            return 1.0 / (rank + 1)
    return 0.0


def ndcg_at_k(retrieved: List[int], expected: List[int], k: int) -> float:
    """二元相关性 NDCG@k —— top-k 排序质量。

    Args:
        retrieved: 同 hit_at_k。
        expected: 同 hit_at_k。
        k: top-k 截断。

    Returns:
        NDCG ∈ [0.0, 1.0]。空 expected / k<=0 / IDCG=0 时返 0.0。

    算法:
        DCG  = sum_{i=0..k-1} rel_i / log2(i+2)
             其中 rel_i = 1 if retrieved[i] ∈ expected else 0
        IDCG = sum_{i=0..min(|expected|,k)-1} 1 / log2(i+2)
             —— 理想排序:所有 expected 排在最前
        NDCG = DCG / IDCG

    为什么简化:项目不存 graded relevance(只有 relevant / not relevant
    二元),所以 NDCG 简化为「期望 doc 排得越靠前越好」。这跟 sklearn
    ndcg_score 在 k=1 且全 1/0 标签场景下等价。
    """
    if k <= 0 or not expected:
        return 0.0
    if not retrieved:
        return 0.0

    expected_set = set(expected)
    # DCG:实际 top-k 中期望 doc 的对数权重得分
    dcg = 0.0
    for i, doc_id in enumerate(retrieved[:k]):
        if doc_id in expected_set:
            dcg += 1.0 / math.log2(i + 2)
    # IDCG:理想 top-min(|E|,k) 全是期望 doc
    ideal_hits = min(len(expected), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def recall_at_k(retrieved: List[int], expected: List[int], k: int) -> float:
    """top-k 召回率 —— top-k 中期望 doc 数 / 总期望 doc 数。

    Args:
        retrieved: 同 hit_at_k。
        expected: 同 hit_at_k。
        k: top-k 截断。

    Returns:
        recall ∈ [0.0, 1.0]。空 expected 返 0.0(分母为 0 时不静默返 0,
        显式 0 表示「无目标可比」,前端可以据此跳过该条)。

    跟 hit_at_k 的差别:hit 是「有 / 无」二值,recall 是「占期望
    总数多少」。hit@10 = 1 不代表 recall@10 = 1(若 expected = [a,b,c]
    只命中 a)。
    """
    if k <= 0 or not expected:
        return 0.0
    if not retrieved:
        return 0.0
    expected_set = set(expected)
    top_k_set = set(retrieved[:k])
    return len(top_k_set & expected_set) / len(expected_set)


# ---------------------------------------------------------------------------
# 聚合(整体指标 mean / p50 / p95 / count)
# ---------------------------------------------------------------------------


def aggregate(values: Iterable[float]) -> Dict[str, float]:
    """对一组 float 算 mean / p50 / p95 / count,供 report.py 聚合用。

    Args:
        values: 一组 float(可迭代)。

    Returns:
        ``{"mean": float, "p50": float, "p95": float, "count": int}``。
        空迭代时 mean/p50/p95 全部 0.0,count = 0。

    算法:
        - mean = sum / n
        - p50 / p95:排序后取 ceil(percentile * n) - 1 下标,等价 numpy
          default linear interpolation 的中位下标(项目指标用整数下标
          足够,避免引入 numpy 依赖)。
    """
    vals: List[float] = list(values)
    n = len(vals)
    if n == 0:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "count": 0}
    mean = sum(vals) / n
    sorted_vals = sorted(vals)

    def _percentile(p: float) -> float:
        # 等价 numpy default:linear,但用 nearest-rank —— 不依赖 numpy,
        # 评测 30~100 条 item 场景下 nearest-rank 跟 linear 差异 < 0.01
        idx = max(0, min(int(math.ceil(p * n)) - 1, n - 1))
        return sorted_vals[idx]

    return {
        "mean": mean,
        "p50": _percentile(0.50),
        "p95": _percentile(0.95),
        "count": n,
    }


# ---------------------------------------------------------------------------
# 答案指标(规则 + judge prompt 构造)
# ---------------------------------------------------------------------------

# judge prompt 模板路径 — 同目录下的 prompts/ 子文件夹。纯文本文件,
# git 跟踪,运营可手工微调文案。lru_cache 防止每条 item 重复 IO。
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


@lru_cache(maxsize=4)
def _load_prompt_template(name: str) -> str:
    """加载纯文本 prompt 模板(同目录 prompts/<name>.txt)。

    ``lru_cache`` 让多次 judge 调用不重复读盘;评测跑 30 条 × 2 metric
    = 60 次构造 prompt,缓存后 2 次 IO。模板文件**不应**在评测运行时
    被改 —— 项目部署流程是改文件 → 重启服务 → 再跑评测。
    """
    path = os.path.join(_PROMPTS_DIR, f"{name}.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def keyword_hit_rate(answer: str, expected_keywords: List[str]) -> float:
    """答案关键词命中率 —— 期望关键词出现在答案中的占比(规则指标)。

    Args:
        answer: RAG 生成的最终答案(可能空字符串)。
        expected_keywords: 期望覆盖的关键词列表(由 EvalDatasetItem
            ``answer_keywords`` 列提供;为空表示不评估该项)。

    Returns:
        命中率 ∈ [0.0, 1.0]。expected_keywords 为空返 0.0(无目标可比,
    跟检索指标的空 expected 一致处理)。
        answer 为空 + expected 非空 → 0.0(没有任何命中)。

    大小写不敏感(中文不受影响,英文统一小写比对);前后空白 ``strip()``;
    关键词做 substring 匹配而非 token-level,简化实现 —— 中文不分词,
    英文单词通常也连写。严格 token 评估留给未来 M37.4。

    边界:全空白关键词(``"   "`` / ``"\t"``)strip 后为空串,**不计入**,
    因为空串是任何串的子串,会误判为命中。有效关键词列表为空 → 返 0.0。
    """
    # 过滤纯空白关键词 —— 它们 strip 后为空串,substr 匹配会假阳性
    effective = [kw for kw in expected_keywords if kw and kw.strip()]
    if not effective:
        return 0.0
    if not answer:
        return 0.0
    answer_norm = answer.strip().lower()
    hits = sum(
        1 for kw in effective
        if kw.strip().lower() in answer_norm
    )
    return hits / len(effective)


def faithfulness_prompt(
    answer: str, contexts: List[str], query: Optional[str] = None
) -> str:
    """构造 faithfulness judge 的完整 prompt 字符串。

    Args:
        answer: RAG 生成的最终答案。
        contexts: 检索命中的 chunk 文本列表(0~N 条);空列表意味着
            judge 会判定 0/2 分(没上下文支撑)。
        query: **当前未在 faithfulness 模板里使用**(模板只问 answer vs
            contexts)。保留参数是为对称性 + 未来扩模板时不破坏调用方。

    Returns:
        完整 prompt 字符串,直接喂给 JudgeClient.call()。

    为什么 contexts 在模板里要标号:LLM 容易在多 context 场景下编造
    归属(把 doc A 的事实归于 doc B)。模板显式编号让 judge 引用
    「context #1」/「context #2」便于审计回看。
    """
    template = _load_prompt_template("faithfulness")
    # 用 \n\n---\n\n 分隔每条 context,标 #1、#2 ……便于 judge 引用
    if contexts:
        numbered = "\n\n---\n\n".join(
            f"[context #{i + 1}]\n{c}" for i, c in enumerate(contexts)
        )
    else:
        numbered = "(无检索上下文)"
    return template.format(contexts=numbered, answer=answer)


def answer_relevancy_prompt(
    answer: str, query: str, contexts: Optional[List[str]] = None
) -> str:
    """构造 answer_relevancy judge 的完整 prompt 字符串。

    Args:
        answer: RAG 生成的最终答案。
        query: 用户原始问题。
        contexts: **当前未在 relevancy 模板里使用**(模板只问 answer vs
            query)。保留参数为对称性。

    Returns:
        完整 prompt 字符串。
    """
    template = _load_prompt_template("answer_relevancy")
    return template.format(query=query, answer=answer)
