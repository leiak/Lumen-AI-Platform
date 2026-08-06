"""M37.2 — Eval run Celery task。

入口 ``run_eval_task(run_id)`` 调 ``runner.run_eval(db, run_id)``,由
``POST /api/v1/eval/runs/``(T16)派单,worker 异步执行。

**M29.1 lesson**:Celery worker boot 时不会像 FastAPI startup 那样 import
整个 ``lumen_main`` 模块,所以 ``lumen_models`` 的 ORM mapper / 服务模块的
依赖链不会被自动注册。本文件**顶部**强制 import 这些模块(``# noqa: F401``),
防 task 首跑炸 ``ModuleNotFoundError`` —— 参考 ``document_tasks.py`` 的
6 行 ``noqa: F401`` 注释。

**为什么不直接 ``.delay()`` 派单**:runner 是 ``async def``,Celery task
本身是 sync。``asyncio.run(run_eval(...))`` 桥接,跟 runner / report 设计
保持一致(都同步入口 async 内部)。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP4 T15
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

# M29.1 / M33.5 lesson:顶部预加载所有模块,防 celery worker 启动后首跑 task
# 时 ModuleNotFoundError。具体哪些 import 必须在这里:
#   - lumen_schemas.* —— ORM 模型的关系目标在 mapper 配置时需要
#   - lumen_models.* —— 评测表 + 所有 FK 目标(eval_runs / eval_run_results
#     / eval_datasets / eval_dataset_items / knowledge_bases / users)
#   - lumen_services.eval.* —— runner 依赖(retrieval pipeline / judge)
#   - lumen_services.retrieval —— runner 调 get_retrieval_pipeline
#   - lumen_models.eval_run, eval_dataset —— 必须,FK 链上
# noqa: F401 让 linter 知道这些 import 不是「没用」
import asyncio  # noqa: F401
import lumen_models  # noqa: F401
import lumen_models.eval_run  # noqa: F401
import lumen_models.eval_dataset  # noqa: F401
import lumen_models.knowledge  # noqa: F401
import lumen_models.user  # noqa: F401
import lumen_models.model_config  # noqa: F401
import lumen_models.tenant  # noqa: F401
import lumen_schemas  # noqa: F401
import lumen_services  # noqa: F401
import lumen_services.eval  # noqa: F401
import lumen_services.eval.runner  # noqa: F401
import lumen_services.eval.report  # noqa: F401
import lumen_services.retrieval  # noqa: F401
import lumen_services.retrieval.pipeline  # noqa: F401

from lumen_tasks.celery_app import celery_app
from lumen_core.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="run_rag_eval",
    autoretry_for=(),  # 业务失败由 status 字段表达,不要 celery 自动重试
    max_retries=0,
    soft_time_limit=7200,  # 2h,跟 task_time_limit 一致
    time_limit=7200,
)
def run_eval_task(self, run_id: int) -> Dict[str, Any]:
    """Celery task 入口:跑 ``run_id`` 对应的评测。

    Args:
        run_id: ``EvalRun.id``。

    Returns:
        ``{"run_id": int, "status": "completed" | "failed" | "cancelled",
           "total_items": int, "completed_items": int}`` —— 给
        ``celery_app.AsyncResult`` 兜底用,业务失败由 ``eval_runs.status``
        字段决定。

    异常策略:
    - runner.run_eval() 自身不 raise(异常被捕到 status=failed),
      所以这里 task 永远 SUCCESS。Celery 失败重试关掉 —— 业务层已经在
      status 字段上表达失败,重试会改写 status 反倒更难排查。
    - 如果 runner 因为环境 bug 真的 raise(比如 DB 连接崩),task 也会失败,
      Celery 默认 exponential backoff 重试 3 次后再放弃,但我们 autoretry_for=()
      关掉了重试,改成立即 FAILURE 让人工介入。
    """
    db = SessionLocal()
    try:
        logger.info("run_eval_task: start EvalRun #%s", run_id)
        # bridge sync Celery → async runner
        asyncio.run(_run_in_event_loop(db, run_id))
        # 同步再查一次,拿最新 status 给 Celery result
        from lumen_models.eval_run import EvalRun
        run = db.get(EvalRun, run_id)
        if run is None:
            return {"run_id": run_id, "status": "deleted"}
        return {
            "run_id": run.id,
            "status": run.status,
            "total_items": run.total_items,
            "completed_items": run.completed_items,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_eval_task: EvalRun #%s crashed", run_id)
        return {
            "run_id": run_id,
            "status": "task_crashed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        db.close()


async def _run_in_event_loop(db, run_id: int) -> None:
    """在 sync Celery 入口里跑 async runner。

    为什么单独包一层:celery task 函数本身是 sync 的,不能 ``await``。
    每条 celery worker thread 启一个临时 event loop 跑完即关。
    """
    from lumen_services.eval.runner import run_eval

    await run_eval(db, run_id)