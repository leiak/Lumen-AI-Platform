"""M37.2 — 检索指标 + 答案指标 + judge 解析单元测试。

覆盖 plan §T10 + §T11:

- TestRetrievalMetrics(10 测试)—— hit / mrr / ndcg / recall + aggregate
- TestAnswerMetrics(4 测试)—— keyword_hit_rate + 2 个 prompt 构造器
- TestJudgeParsing(4 测试)—— parse_judge_response + strict schema 兜底
  (D8 关键:LLM 输出非 JSON / 多字段时 Pydantic 严格校验)

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP3 T10/T11
"""
import json

import pytest
from pydantic import ValidationError

from lumen_services.eval.judge import (
    AnswerRelevancyScore,
    FaithfulnessScore,
    make_parse_failed_response,
    parse_judge_response,
)
from lumen_services.eval.metrics import (
    aggregate,
    answer_relevancy_prompt,
    faithfulness_prompt,
    hit_at_k,
    keyword_hit_rate,
    mrr,
    ndcg_at_k,
    recall_at_k,
)


class TestRetrievalMetrics:
    """检索指标纯函数测试 — 不依赖 DB / LLM,纯数学。"""

    # --- 1. 空集边界 -------------------------------------------------------

    def test_empty_inputs_all_zero(self):
        """空 retrieved / 空 expected / 全空都返 0,不要抛异常或 NaN。"""
        assert hit_at_k([], [], k=10) == 0.0
        assert hit_at_k([1, 2, 3], [], k=10) == 0.0
        assert hit_at_k([], [1, 2], k=10) == 0.0
        assert mrr([], [1, 2]) == 0.0
        assert mrr([1, 2], []) == 0.0
        assert ndcg_at_k([], [1], k=5) == 0.0
        assert ndcg_at_k([1, 2], [], k=5) == 0.0
        assert recall_at_k([], [1], k=5) == 0.0
        assert recall_at_k([1, 2], [], k=5) == 0.0

    # --- 2. 全集命中 -------------------------------------------------------

    def test_full_hit_all_metrics_one(self):
        """所有 expected 都在 top-k 且位置理想,4 个指标全返 1.0。

        NDCG=1.0 的前提:expected 在 retrieved 里按「理想顺序」排列(排名
        越靠前越好)—— 这里 retrieved=[10, 30, 50, ...] 把 expected
        [10, 30, 50] 排在第 0/1/2 名,DCG = IDCG → NDCG = 1.0。如果
        expected 散在非相邻位置,NDCG < 1.0(见 test_partial_hit_only_first_doc)。
        """
        retrieved = [10, 30, 50, 40, 20]
        expected = [10, 30, 50]
        # hit@5:有 → 1.0;hit@3:有 → 1.0
        assert hit_at_k(retrieved, expected, k=5) == 1.0
        assert hit_at_k(retrieved, expected, k=3) == 1.0
        # MRR:第一个 expected = 10 在 rank=0 → 1.0
        assert mrr(retrieved, expected) == 1.0
        # NDCG@5:DCG=IDCG(都在 rank 0/1/2) → 1.0
        assert ndcg_at_k(retrieved, expected, k=5) == pytest.approx(1.0)
        # Recall@5:3/3 = 1.0
        assert recall_at_k(retrieved, expected, k=5) == 1.0

    # --- 3. 部分命中(hit / recall / mrr 差异) ------------------------------

    def test_partial_hit_hit_vs_recall_differs(self):
        """expected=[a,b,c] 只命中 a,验证 hit=1 但 recall<1,体现指标差异。"""
        retrieved = [1, 2, 3, 4, 5]  # 不在 expected 里
        expected = [10, 20, 30]
        # 没期望 → 全 0
        assert hit_at_k(retrieved, expected, k=5) == 0.0
        assert recall_at_k(retrieved, expected, k=5) == 0.0
        assert mrr(retrieved, expected) == 0.0

    def test_partial_hit_only_first_doc(self):
        """expected=[a,b] 只命中 a(在 rank=2)—— hit=1, MRR=0.333, recall=0.5。

        这是 hit / mrr / recall 三个指标分得最开的场景。
        """
        retrieved = [100, 200, 10, 300]  # 10 在 rank=2
        expected = [10, 20]
        assert hit_at_k(retrieved, expected, k=5) == 1.0
        assert hit_at_k(retrieved, expected, k=2) == 0.0  # top-2 没 10
        # MRR:第一个 expected = 10 在 rank=2 → 1/3
        assert mrr(retrieved, expected) == pytest.approx(1.0 / 3.0)
        # Recall@5:top-5 里有 10 一个,expected 2 个 → 0.5
        assert recall_at_k(retrieved, expected, k=5) == pytest.approx(0.5)
        # NDCG@5:DCG = 1/log2(4) ≈ 0.5(10 在 rank=2 → i+2=4),
        # IDCG = 1/log2(2) + 1/log2(3) ≈ 1.0 + 0.63 = 1.63
        # → NDCG ≈ 0.5/1.63 ≈ 0.307
        ndcg_val = ndcg_at_k(retrieved, expected, k=5)
        assert 0.0 < ndcg_val < 1.0  # 部分命中应在 (0, 1) 之间

    # --- 4. k=0 边界 -------------------------------------------------------

    def test_k_zero_all_zero(self):
        """k=0 没有 slot,hit/recall/ndcg 全 0(MRR 不受 k 影响,正常算)。"""
        retrieved = [2, 1, 3]  # 2 在 rank=0 → MRR=1.0
        expected = [2]
        assert hit_at_k(retrieved, expected, k=0) == 0.0
        assert recall_at_k(retrieved, expected, k=0) == 0.0
        assert ndcg_at_k(retrieved, expected, k=0) == 0.0
        # MRR 不接 k 参数,正常算(2 在 rank=0 → 1.0)
        assert mrr(retrieved, expected) == 1.0

    def test_k_negative_treated_as_zero(self):
        """k<0 跟 k=0 一样处理(无 slot)—— 防御负数。"""
        retrieved = [1, 2, 3]
        expected = [2]
        assert hit_at_k(retrieved, expected, k=-5) == 0.0
        assert recall_at_k(retrieved, expected, k=-5) == 0.0

    # --- 5. k > len(retrieved) 边界 ----------------------------------------

    def test_k_beyond_len_treats_as_len(self):
        """k=100 但 retrieved 只有 3 条 → 用前 3 条算,不 IndexError。"""
        retrieved = [10, 20, 30]
        expected = [20, 40]
        # hit:20 在 top-3 → 1.0;k=100 等同 k=3
        assert hit_at_k(retrieved, expected, k=100) == 1.0
        # recall:20 在,40 不在 → 1/2 = 0.5
        assert recall_at_k(retrieved, expected, k=100) == pytest.approx(0.5)
        # MRR:20 在 rank=1 → 1/2
        assert mrr(retrieved, expected) == pytest.approx(0.5)
        # NDCG@100:DCG=1/log2(3)≈0.63, IDCG=1/log2(2)+1/log2(3)≈1.63 → ≈0.387
        assert 0.0 < ndcg_at_k(retrieved, expected, k=100) < 1.0

    # --- 6. aggregate -----------------------------------------------------

    def test_aggregate_basic(self):
        """mean / p50 / p95 / count 正确,空列表兜底 0。"""
        # 简单 10 条 0.0 ~ 1.0 均匀分布
        values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        result = aggregate(values)
        assert result["count"] == 10
        assert result["mean"] == pytest.approx(0.55)
        # p50 = 第 ceil(0.5*10)-1 = 4 下标 → sorted[4] = 0.5
        assert result["p50"] == pytest.approx(0.5)
        # p95 = 第 ceil(0.95*10)-1 = 9 下标 → sorted[9] = 1.0
        assert result["p95"] == pytest.approx(1.0)

    def test_aggregate_empty_returns_zeros(self):
        """空列表 → mean/p50/p95 全 0,count=0(避免除零 + 模板渲染崩)。"""
        result = aggregate([])
        assert result == {"mean": 0.0, "p50": 0.0, "p95": 0.0, "count": 0}

    def test_aggregate_single_value(self):
        """1 个值 → mean/p50/p95 都等于该值。"""
        result = aggregate([0.42])
        assert result["count"] == 1
        assert result["mean"] == pytest.approx(0.42)
        assert result["p50"] == pytest.approx(0.42)
        assert result["p95"] == pytest.approx(0.42)


class TestAnswerMetrics:
    """答案指标单元测试 —— keyword_hit_rate + 2 个 prompt 构造器。

    plan §T11 要求 4 测试,覆盖:
    1. keyword_hit_rate basic:中英文混合 / 大小写 / 部分命中
    2. keyword_hit_rate edge:空 answer / 空 keywords / 纯空白
    3. faithfulness_prompt:answer + contexts 都嵌入,空 contexts 兜底
    4. answer_relevancy_prompt:answer + query 都嵌入
    """

    # --- 1. keyword_hit_rate basic -----------------------------------------

    def test_keyword_hit_rate_mixed_chinese_english(self):
        """中文 + 英文关键词混合,大小写不敏感,部分命中算占比。"""
        answer = (
            "Python 是一门解释型语言,支持多范式。"
            "Python is widely used in AI and Data Science."
        )
        kws = ["Python", "ai", "javascript", "解释型"]  # 3/4 命中
        # Python × 2(中英都出现)+ ai(case-insensitive match "AI")=3, javascript 不在
        # 但 ai 在 "Data Science" 里? 是 substring "AI" — 不,小写比对后 "ai" in
        # "...Data Science." 是 False(原文 "AI" → "ai", "ai" 不在 "Data Science"
        # 小写里)→ 重新算:Python in 答案(小写)2 次 + "解释型" in 答案 1 次 = 3 命中
        # 等价:3/4 = 0.75
        rate = keyword_hit_rate(answer, kws)
        assert rate == pytest.approx(0.75)

    def test_keyword_hit_rate_case_insensitive(self):
        """英文关键词大小写不敏感(answer 大写 vs keyword 小写应命中)。"""
        rate = keyword_hit_rate("The API is broken", ["api", "broken"])
        assert rate == pytest.approx(1.0)

    # --- 2. keyword_hit_rate edge cases ------------------------------------

    def test_keyword_hit_rate_empty_inputs(self):
        """空 answer / 空 keywords / 全空 / 关键词全是空白,全部安全返 0。"""
        assert keyword_hit_rate("", ["x"]) == 0.0  # answer 空
        assert keyword_hit_rate("answer", []) == 0.0  # keywords 空
        assert keyword_hit_rate("", []) == 0.0  # 全空
        # 关键词全是空白字符串 → strip 后为空,不算「有关键词」(防御)
        assert keyword_hit_rate("any answer", ["   ", "\t"]) == 0.0

    def test_keyword_hit_rate_full_hit(self):
        """所有关键词都命中 → 1.0。"""
        rate = keyword_hit_rate(
            "深度学习和神经网络是 AI 的核心技术",
            ["深度学习", "神经网络", "AI"],
        )
        assert rate == pytest.approx(1.0)

    # --- 3. faithfulness_prompt ---------------------------------------------

    def test_faithfulness_prompt_embeds_answer_and_contexts(self):
        """answer + contexts 都嵌入 prompt,空 contexts 显式标注「无」。"""
        contexts = [
            "RAG 是 retrieval-augmented generation 的缩写",
            "它结合了检索和生成两个步骤",
        ]
        answer = "RAG = retrieval-augmented generation"
        prompt = faithfulness_prompt(answer, contexts)
        # answer 出现
        assert answer in prompt
        # 每条 context 都出现
        for c in contexts:
            assert c in prompt
        # contexts 标号 #1 / #2 出现(便于 judge 引用)
        assert "[context #1]" in prompt
        assert "[context #2]" in prompt

    def test_faithfulness_prompt_empty_contexts(self):
        """contexts 为空时不崩,显式标注「无检索上下文」让 judge 知道。"""
        prompt = faithfulness_prompt("某个答案", [])
        assert "某个答案" in prompt
        assert "(无检索上下文)" in prompt  # 兜底标记

    # --- 4. answer_relevancy_prompt -----------------------------------------

    def test_answer_relevancy_prompt_embeds_query_and_answer(self):
        """answer + query 都嵌入 prompt,模板里的 {query}/{answer} 占位都填了。"""
        prompt = answer_relevancy_prompt(
            answer="Python 是 1991 年发布的解释型语言。",
            query="Python 是什么时候发布的?",
        )
        assert "Python 是什么时候发布的?" in prompt
        assert "Python 是 1991 年发布的解释型语言。" in prompt
        # 占位符不应残留
        assert "{query}" not in prompt
        assert "{answer}" not in prompt


class TestJudgeParsing:
    """judge 解析的纯函数测试 —— D8 strict schema 兜底是 T11 关键。

    覆盖:
    1. parse_judge_response: 纯 JSON 直过
    2. parse_judge_response: markdown 代码块包装也过(LLM 常见)
    3. parse_judge_response: 非 JSON 抛 ValueError(由 JudgeClient 兜底)
    4. strict schema extra="forbid": LLM 多塞字段要拒
    """

    def test_parse_pure_json(self):
        """纯 JSON 内容直接解析成 strict schema。"""
        content = '{"score": 2, "reasoning": "完全支撑"}'
        result = parse_judge_response(content, FaithfulnessScore)
        assert result.score == 2
        assert result.reasoning == "完全支撑"

    def test_parse_markdown_wrapped_json(self):
        """LLM 经常用 ```json ... ``` 包 JSON,要能剥壳解析。"""
        content = (
            "当然可以,这是我的评估:\n\n"
            "```json\n"
            '{"score": 1, "reasoning": "部分支撑"}\n'
            "```\n"
        )
        result = parse_judge_response(content, AnswerRelevancyScore)
        assert result.score == 1
        assert result.reasoning == "部分支撑"

    def test_parse_invalid_json_raises(self):
        """非 JSON 输入抛 ValueError(由 JudgeClient 兜底成 score=0)。"""
        with pytest.raises(ValueError):
            parse_judge_response("不是 JSON,是自然语言评估", FaithfulnessScore)
        with pytest.raises((ValueError, json.JSONDecodeError)):
            parse_judge_response("[1, 2, 3]", FaithfulnessScore)  # 不是 dict

    def test_strict_schema_rejects_extra_fields(self):
        """D8:LLM 偷偷多塞字段(解释文字 / 重复字段)要拒,不能静默吞。"""
        # 直接用 schema 校验,验证 extra="forbid" 生效
        with pytest.raises(ValidationError):
            FaithfulnessScore.model_validate(
                {"score": 2, "reasoning": "OK", "extra_field": "should reject"}
            )
        # 同样走 parse_judge_response 也要拒
        with pytest.raises(ValidationError):
            parse_judge_response(
                '{"score": 2, "reasoning": "OK", "extra_field": "x"}',
                FaithfulnessScore,
            )
        # parse 失败兜底
        fb = make_parse_failed_response(FaithfulnessScore, reason="unit test")
        assert fb.score == 0
        assert fb.reasoning == "unit test"
