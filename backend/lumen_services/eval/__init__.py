"""M37 — RAG 评测服务包。

子模块:

- ``metrics`` — 纯数学检索指标 + LLM judge 答案指标
- ``judge`` — LLM-as-judge 客户端(call_type=eval_judge,trace 自动落库)
- ``runner`` — 主评测循环(per-item commit + 续跑)
- ``report`` — 聚合 metrics_json + 生成 Markdown 报告
- ``compare`` — 两 run 对比(delta + winners)

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md
Plan: docs-internal/superpowers/plans/m37-plan.md CP3/CP4
"""
