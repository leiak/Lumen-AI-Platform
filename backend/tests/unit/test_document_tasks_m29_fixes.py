"""M29.1: 3 个 latent bug 在 KB ingest 路径上的回归测试。

`document_tasks.process_document_task` 在真实 KB 上传时被
dev chat smoke 暴露的 3 个非致命错误:
1. ``_emit_notification`` 用了不存在的 ``doc.kb_id`` 字段 —
   真实 ORM 字段是 ``knowledge_base_id``。M29.1 改源后
   ``test_document_tasks_notification.py`` 加了
   ``metadata["kb_id"] == 3`` 断言(那边覆盖)。
2. ``get_retrieval_pipeline("knowledge_base")`` 1-arg 调用,
   M28 改成 3-arg ``(kb_id, model_config_id, db)`` 后这条
   漏改,BM25 index 永远不更新。
3. ``EmbeddingCallLoggingService.log_call`` 写 row 时
   ``NoReferencedTableError: embedding_call_logs.agent_id`` —
   worker 启动只 import 了 ``document_tasks`` 内部用到的 model,
   没 import ``Agent``,SQLAlchemy 排序 FK 时找不到目标表。
   ``log_call`` 内部 try/except 吞了异常,**observability 9 行
   全部 skipped**,M27 的 "embedding trace" 在 KB 摄入路径
   完全失效。

bug #1 在 ``test_document_tasks_notification.py`` 覆盖,
bug #2 和 #3 在这里。
"""
import pytest


def test_bm25_pipeline_uses_3arg_signature():
    """Bug #2 回归: ``get_retrieval_pipeline`` 必须用 M28 后的
    3-arg 形式 ``(kb_id, model_config_id, db)``,不能用 1-arg
    字符串 ``"knowledge_base"``(那是已废的 cache key 名)。
    """
    from lumen_tasks import document_tasks
    import inspect

    src = inspect.getsource(document_tasks.process_document_task)
    assert 'get_retrieval_pipeline(kb_id, doc.embedding_model_config_id, db)' in src, (
        "process_document_task 必须用 3-arg 形式调用 "
        "get_retrieval_pipeline(kb_id, model_config_id, db),"
        "M28 改了签名后这里必须跟上"
    )
    assert 'get_retrieval_pipeline("knowledge_base")' not in src, (
        "发现 1-arg 旧调用 — M28 修了 get_retrieval_pipeline 签名,"
        "document_tasks 没跟上会让 BM25 index 永远不更新"
    )


def test_process_document_task_imports_agent_for_fk():
    """Bug #3 回归: ``EmbeddingCallLoggingService.log_call`` 在 INSERT
    ``embedding_call_logs`` 时 SQLAlchemy 排 FK 顺序要 ``agents`` 表
    在 registry。Celery worker 启动路径 ``app.tasks.celery_app``
    **不**走 ``app.main``,所以 main.py:36 的 ``from lumen_models.agent
    import Agent`` 不会在 worker 进程里跑。worker 必须自己 import。

    测法:从 ``app.models.agent`` 直接导入 Agent,确认它进了
    ``Base.registry.mappers``(证明 SQLAlchemy 反射成功),然后再
    import ``document_tasks`` 确认没把它从 registry 里踢掉。
    """
    from lumen_core.database import Base
    from lumen_models.agent import Agent

    # SQLAlchemy 2.0: Base.registry.mappers 装的是 Mapper 对象,
    # 按 class_ 查更直观。
    def _registered_classes():
        return {m.class_ for m in Base.registry.mappers}

    # Sanity: Agent 自己 import 后应该已经在 registry
    assert Agent in _registered_classes(), (
        "Agent model 没注册到 SQLAlchemy — main.py:36 的 import "
        "链断了,影响所有依赖 Agent FK 的 INSERT"
    )

    # 关键回归: import document_tasks 不能破坏 Agent registry
    from lumen_tasks import document_tasks  # noqa: F401
    assert Agent in _registered_classes(), (
        "document_tasks import 后 Agent 仍在 registry 是 "
        "embedding_call_logs.agent_id FK 解析的前置条件"
    )


def test_process_document_task_module_imports_agent():
    """Bug #3 配套: 静态 import 检查。回归保护: 即使有人
    refactor 把 ``from lumen_models.agent import Agent`` 移走,
    这个 test 也会 fail 提醒。"""
    from lumen_tasks import document_tasks
    import inspect

    src = inspect.getsource(document_tasks)
    assert "from lumen_models.agent import Agent" in src, (
        "document_tasks.process_document_task 顶部必须 import "
        "Agent — Celery worker 启动路径不走 main.py,SQLAlchemy "
        "排 embedding_call_logs.agent_id FK 时找不到 agents 表"
    )
