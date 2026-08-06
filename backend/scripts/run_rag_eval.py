"""M37.2 — RAG 评测 CLI 直跑模式(不走 Celery)。

Usage:

    cd backend && python -m scripts.run_rag_eval \
        --dataset-id 5 \
        --config-json /path/to/config.json \
        --no-celery

适用场景:
- 本地快速回归测试(开发者改完 rerank / search_weights 后,想立刻看 hit@5)
- 集成测试不依赖 Celery worker(eager mode 也可以,但本脚本更直接)
- seed 后端联调 — `seed_m37_default_eval_config` 配好默认 judge,直接 CLI 跑
  builtin dataset 即可

风格参考 ``run_mcp_server.py`` + ``seed_*.py``:sys.path 修正 + argparse
+ 显式 ``sys.exit``。CLI 走 ``runner.run_eval()`` 直跑,跟 Celery 入口
``run_eval_task`` 共享同一个核心循环 —— 不存在「直跑跟 Celery 跑出来不一
样」的隐患。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP4 T15
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

# 把 backend 根加进 sys.path —— 跟 ``run_mcp_server.py`` / ``seed_*.py``
# 同款,允许 `python -m scripts.run_rag_eval` 任何 cwd 下跑。
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from sqlalchemy import select  # noqa: E402

# 顶部 import 跟 celery eval_tasks 对齐 —— 直跑模式不依赖 Celery worker,
# 但还是要预加载 ORM mapper 防 FK 解析失败。
from lumen_models import (  # noqa: E401,F401
    eval_run, eval_dataset, knowledge, user, model_config, tenant,
)
from lumen_core.database import SessionLocal  # noqa: E402
from lumen_models.eval_run import EvalRun  # noqa: E402
from lumen_models.eval_dataset import EvalDataset  # noqa: E402
from lumen_models.knowledge import KnowledgeBase  # noqa: E402

logger = logging.getLogger("run_rag_eval")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Windows 控制台默认 GBK codepage,输出里的 emoji / 中文会让 print() 抛
# UnicodeEncodeError 直接打断 CLI(踩过:第一行「✅ EvalRun 已创建」就崩,
# run 卡在 pending)。强制 stdout/stderr 走 UTF-8 + errors="replace",
# 编码问题最多显示成 "?" 而不是中断评测。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def parse_args() -> argparse.Namespace:
    """argparse 解析 --dataset-id / --config-json / --no-celery / --user-id。"""
    p = argparse.ArgumentParser(
        description="M37.2 — 直接跑一次 RAG 评测(非 Celery 模式)",
    )
    p.add_argument(
        "--dataset-id", type=int, required=True,
        help="EvalDataset.id;用 ``GET /api/v1/eval/datasets/`` 查 ID",
    )
    p.add_argument(
        "--config-json", type=str, default=None,
        help="评测 config JSON 文件路径;省略则从 system_configs.eval_default_config 读",
    )
    p.add_argument(
        "--no-celery", action="store_true", default=True,
        help="(默认 True) 直跑模式;保留 flag 是为了跟将来 --celery 模式对齐",
    )
    p.add_argument(
        "--user-id", type=int, default=None,
        help="触发 run 的 user.id;不传则用 dataset.created_by",
    )
    return p.parse_args()


def _load_config(db, path: Optional[str]) -> Dict[str, Any]:
    """从文件 / system_configs / KB 兜底拿 config_json。

    优先级:
        1. ``--config-json <path>`` 指定的文件
        2. system_configs.eval_default_config(seed 脚本写)
        3. KB 上 inference 不出来的合理 default

    Returns:
        dict,至少含 ``embedding_model_config_id`` / ``judge_model_config_id`` /
        ``top_k`` / ``search_weights``。
    """
    if path:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        logger.info("loaded config from %s", path)
        return cfg
    # 兜底走 system_configs —— 参考 ``lumen_services.skill_executors.http``
    # 的 inline 模式,直接查表:
    from lumen_models.system_config import SystemConfig
    try:
        row = (
            db.query(SystemConfig)
            .filter(SystemConfig.key == "eval_default_config")
            .first()
        )
        if row is not None and row.value:
            cfg = row.value
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            logger.info("loaded config from system_configs.eval_default_config")
            return cfg
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "system_configs lookup failed: %s, using minimal default", exc
        )
    # 最终兜底 —— 跟 seed 脚本里 DEFAULT_EVAL_CONFIG 字段一致
    return {
        "name": "cli-default",
        "top_k": 10,
        "rerank": True,
        "search_weights": {
            "title": 10.0, "important_kw": 30.0, "question_kw": 20.0, "text": 2.0,
        },
        "embedding_model_config_id": None,
        "judge_model_config_id": None,
        "judge_metrics": ["faithfulness", "answer_relevancy"],
    }


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    try:
        # 1. dataset 必须存在
        dataset = db.get(EvalDataset, args.dataset_id)
        if dataset is None:
            print(f"❌ EvalDataset #{args.dataset_id} 不存在", file=sys.stderr)
            return 1
        kb = db.get(KnowledgeBase, dataset.kb_id)
        if kb is None:
            print(f"❌ dataset #{args.dataset_id} 关联的 KB 不存在", file=sys.stderr)
            return 1

        # 2. 装 config
        cfg = _load_config(db, args.config_json)
        # 用 KB 的 embedding_model_config_id 兜底 cfg 里没填的
        if not cfg.get("embedding_model_config_id"):
            cfg["embedding_model_config_id"] = kb.embedding_model_config_id

        # 3. 建 EvalRun 行(pending)
        run = EvalRun(
            dataset_id=dataset.id,
            config_json=cfg,
            status="pending",
            total_items=0,
            completed_items=0,
            created_by=args.user_id or dataset.created_by,
        )
        db.add(run); db.commit(); db.refresh(run)
        print(
            f"✅ EvalRun #{run.id} 已创建 → 跑 dataset #{dataset.id} "
            f"({dataset.name}, {kb.name})"
        )

        # 4. 直跑 runner
        from lumen_services.eval.runner import run_eval
        asyncio.run(run_eval(db, int(run.id)))

        # 5. 回读最新 status + metrics_json 摘要给用户
        db.refresh(run)
        m: Dict[str, Any] = dict(run.metrics_json or {})
        retrieval = m.get("retrieval", {})
        print(
            f"\n📊 EvalRun #{run.id} 完成\n"
            f"   status           = {run.status}\n"
            f"   total_items      = {run.total_items}\n"
            f"   completed_items  = {run.completed_items}\n"
            f"   retrieval.hit_at_5   = {retrieval.get('hit_at_5', 0)}\n"
            f"   retrieval.mrr        = {retrieval.get('mrr', 0)}\n"
            f"   retrieval.latency p50 = {retrieval.get('latency_ms_p50', 0)} ms\n"
        )
        if run.error_message:
            print(f"⚠️  error_message: {run.error_message}", file=sys.stderr)
        return 0 if run.status == "completed" else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())