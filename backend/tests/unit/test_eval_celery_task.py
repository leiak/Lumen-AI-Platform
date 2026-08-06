"""M37.2 — Celery task eager mode 测试。

4 测试覆盖 plan §T15 要求:

1. happy path:eager mode 跑 task → run 状态走完 → 返回 status=completed
2. runner 异常(embedding_model_config_id 不匹配)→ task 仍 SUCCESS,
   run.status=failed(task 自己不 raise,业务失败由 status 表达)
3. run 不存在 → task 返 {"status": "deleted"},不崩
4. Celery task 注册名 == "run_rag_eval" —— API 派单 + 客户端调用同一字符串

用 ``celery_app.conf.task_always_eager = True`` 同步执行,不用 worker。
"""
import asyncio
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from lumen_core.database import SessionLocal, ensure_eval_datasets_table, ensure_eval_runs_table
from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.knowledge import KnowledgeBase
from lumen_models.user import User
from lumen_models.model_config import ModelConfig
from lumen_tasks.celery_app import celery_app
from lumen_tasks.eval_tasks import run_eval_task


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def eager_celery():
    """测试期间把 Celery 切到 eager mode(同步执行 task body,不走 worker)。"""
    celery_app.conf.task_always_eager = True
    yield celery_app
    celery_app.conf.task_always_eager = False


@pytest.fixture
def db_session():
    ensure_eval_datasets_table()
    ensure_eval_runs_table()
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def tenant_user(db_session):
    user = db_session.query(User).filter(User.tenant_id == 1).first()
    if user is None:
        pytest.skip("no user in tenant 1")
    return user


@pytest.fixture
def kb(db_session):
    cfg = (
        db_session.query(ModelConfig)
        .filter(ModelConfig.is_active == 1, ModelConfig.is_embedding == 1)
        .order_by(ModelConfig.id)
        .first()
    )
    if cfg is None:
        pytest.skip("no active embedding model")
    row = KnowledgeBase(
        name=f"m37-celery-kb-{uuid.uuid4().hex[:8]}",
        tenant_id=1,
        embedding_model_config_id=cfg.id,
        status="active",
    )
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    yield row
    # teardown
    db_session.query(EvalRunResult).filter(
        EvalRunResult.run_id.in_(
            db_session.query(EvalRun.id).filter(EvalRun.dataset_id.in_(
                db_session.query(EvalDataset.id).filter(EvalDataset.kb_id == row.id)
            ))
        )
    ).delete(synchronize_session=False)
    db_session.query(EvalRun).filter(EvalRun.dataset_id.in_(
        db_session.query(EvalDataset.id).filter(EvalDataset.kb_id == row.id)
    )).delete(synchronize_session=False)
    db_session.query(EvalDatasetItem).filter(EvalDatasetItem.dataset_id.in_(
        db_session.query(EvalDataset.id).filter(EvalDataset.kb_id == row.id)
    )).delete(synchronize_session=False)
    db_session.query(EvalDataset).filter(EvalDataset.kb_id == row.id).delete(synchronize_session=False)
    db_session.query(KnowledgeBase).filter(KnowledgeBase.id == row.id).delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def dataset_with_items(db_session, kb, tenant_user):
    """空 dataset → happy path 走 status=completed 0 items,避开 retrieval pipeline。"""
    ds = EvalDataset(
        kb_id=kb.id, tenant_id=1, name=f"m37-celery-ds-{uuid.uuid4().hex[:8]}",
        source="manual", is_active=1, created_by=tenant_user.id,
    )
    db_session.add(ds); db_session.commit(); db_session.refresh(ds)
    return ds


def _make_run(db_session, dataset, *, embedding_model_config_id=None) -> EvalRun:
    if embedding_model_config_id is None:
        embedding_model_config_id = (
            db_session.query(KnowledgeBase)
            .filter(KnowledgeBase.id == dataset.kb_id).first().embedding_model_config_id
        )
    cfg = {
        "name": "celery-test",
        "top_k": 5,
        "rerank": False,
        "search_weights": {},
        "embedding_model_config_id": embedding_model_config_id,
        "judge_model_config_id": 1,
        "judge_metrics": [],
    }
    run = EvalRun(
        dataset_id=dataset.id,
        config_json=cfg,
        status="pending",
        total_items=0,
        completed_items=0,
    )
    db_session.add(run); db_session.commit(); db_session.refresh(run)
    return run


def _reload_run(db_session, run_id: int) -> EvalRun:
    """重新读 EvalRun —— 跨 session commit 后,旧 session 的 InnoDB 快照
    看不到新数据(REPEATABLE READ)。

    修法:**commit 当前 session 释放 snapshot**,再 expire_all 清 SQLAlchemy
    缓存,然后 db.get() 触发新 SELECT —— 新 SELECT 会拿到 commit 后的最新
    snapshot。

    为什么不用新 SessionLocal:fixture 里 db_session 有 teardown 清理逻辑,
    新开会绕开它导致 dev DB 污染(详见 MEMORY.md 2026-06-29 笔记)。
    """
    db_session.commit()  # 释放 InnoDB REPEATABLE READ snapshot
    db_session.expire_all()
    return db_session.get(EvalRun, run_id)


MOCK_CHUNKS = [
    {"text": "ctx1", "metadata": {"document_id": 100}, "score": 0.9},
]


class _FakePipeline:
    def search(self, *args, **kwargs):
        return MOCK_CHUNKS


def _patched_pipeline():
    return patch(
        "lumen_services.eval.runner.get_retrieval_pipeline",
        return_value=_FakePipeline(),
    )


# ---------------------------------------------------------------------------
# 1. happy path:eager mode 跑 task → completed
# ---------------------------------------------------------------------------


def test_celery_task_eager_completes_run(eager_celery, db_session, dataset_with_items):
    """空 dataset → runner 直接走 status=completed;task 返 status=completed。"""
    ds = dataset_with_items
    run = _make_run(db_session, ds)

    with _patched_pipeline():
        result = run_eval_task(run.id)

    refreshed = _reload_run(db_session, run.id)
    assert refreshed.status == "completed"
    # task 返回值
    assert result["run_id"] == run.id
    assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# 2. embedding 不匹配 → task 不崩,run.status=failed
# ---------------------------------------------------------------------------


def test_celery_task_eager_swallows_business_failure(eager_celery, db_session, dataset_with_items):
    """runner 抛 ValueError(embedding 不匹配)→ task 不 raise,run.status=failed。"""
    ds = dataset_with_items
    # 故意设错 embedding id 让 _execute raise
    run = _make_run(db_session, ds, embedding_model_config_id=99999)

    with _patched_pipeline():
        result = run_eval_task(run.id)

    refreshed = _reload_run(db_session, run.id)
    # task 本身 SUCCESS,业务失败由 status 表达
    assert refreshed.status == "failed"
    assert refreshed.error_message is not None
    assert "embedding_model_config_id" in refreshed.error_message
    # task 返回 dict 里也带了 status=failed
    assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# 3. run 不存在 → task 返 deleted,不崩
# ---------------------------------------------------------------------------


def test_celery_task_eager_handles_missing_run(eager_celery, db_session):
    """run_id 不存在 → runner 直接 return;task 返 {"status": "deleted"}。"""
    result = run_eval_task(99999999)
    assert result["status"] == "deleted"
    assert result["run_id"] == 99999999


# ---------------------------------------------------------------------------
# 4. task 注册名正确(API 派单 + 客户端调用要对得上)
# ---------------------------------------------------------------------------


def test_celery_task_name_registration():
    """Celery worker 启动时注册 task 的 name;API 派单要按这个 name .delay()。

    M29.2.1 lesson:``include=[...]`` 是注册入口,但 task 装饰器里的
    ``name=`` 是派单时的 lookup key,必须保持稳定。
    """
    # celery_app.tasks 是 dict,task name → Task 实例
    assert "run_rag_eval" in celery_app.tasks
    task_obj = celery_app.tasks["run_rag_eval"]
    assert task_obj.name == "run_rag_eval"
    # task_obj.run 是 Celery 包装的 runner proxy,不一定等同原函数引用 —
    # 用名字比对就够了:run_eval_task.__name__ == "run_eval_task"。
    assert task_obj.run.__name__ == run_eval_task.__name__


# ---------------------------------------------------------------------------
# 5. (bonus) M29.1 lesson:模块导入不依赖 worker boot 顺序
# ---------------------------------------------------------------------------


def test_eval_tasks_module_imports_standalone():
    """直接 ``import lumen_tasks.eval_tasks`` 不报错。

    M29.1 lesson:celery worker boot 时 celery_app 已加载,再 import
    eval_tasks 时 module-level 的 12 行 ``noqa: F401`` 应该全部 OK。
    如果某个 import 因 worker boot 时序问题崩,这个测试就 fail。
    """
    import importlib
    mod = importlib.import_module("lumen_tasks.eval_tasks")
    assert mod.run_eval_task is not None
    assert mod.celery_app is not None