"""M29.2.1 (2026-06-16): Celery worker 循环 import 修复回归测试。

修前症状:
  ``ImportError: cannot import name 'process_document_task' from
  partially initialized module 'lumen_tasks.document_tasks'
  (most likely due to a circular import)``

根因:
  ``backend/app/tasks/celery_app.py`` 末尾 module-level ``from
  app.tasks.document_tasks import process_document_task``(原 line 31)
  跟 ``document_tasks.py`` line 6 ``from lumen_tasks.celery_app import
  celery_app`` 形成循环。``prefork`` pool fork 时 celery_app 还在
  加载中,document_tasks 反向 import 触发"partially initialized"
  ImportError,worker SpawnPoolWorker 全部 exitcode 1,任务全部 stuck
  in queued。

修法:
  ``celery_app = Celery(..., include=["lumen_tasks.document_tasks"])`` —
  让 Celery 用内置的 ``include`` 列表在 worker 启动时 import task 模块
  (那时 celery_app 已完全加载),不撞循环。删 celery_app.py 末尾的
  module-level import。

测试:
  1. ``celery_app.conf.include`` 含 ``app.tasks.document_tasks``
  2. celery_app.py **不再** module-level import document_tasks
  3. 静态: celery_app.py 不该有 ``from lumen_tasks.document_tasks``
  4. import 时不抛 ImportError
  5. ``celery_app.tasks`` 注册名含 ``process_document`` (include 触发)
"""
import sys
import inspect

import pytest


def test_celery_app_include_list_has_document_tasks():
    """回归: ``Celery(...)`` 必须用 ``include=["lumen_tasks.document_tasks"]``,
    而不是 module-level ``from lumen_tasks.document_tasks import ...``。
    """
    from lumen_tasks.celery_app import celery_app
    include = celery_app.conf.include
    assert "lumen_tasks.document_tasks" in include, (
        f"celery_app.conf.include 必须含 'lumen_tasks.document_tasks',"
        f"实际: {include}"
    )


def test_celery_app_module_no_module_level_document_tasks_import():
    """回归: celery_app.py 不能再有 module-level document_tasks import
    (会跟 document_tasks.py line 6 反向 import 形成循环)。
    """
    import lumen_tasks.celery_app as celery_mod
    src_path = celery_mod.__file__
    assert src_path and src_path.endswith(".py")
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    # 删注释行 — M29.2.1 修复说明里含 ``from lumen_tasks.document_tasks import``
    # 字面字符串(在 docstring/comment 里),不应被认作真 import。
    code_lines = [
        line for line in src.split("\n")
        if not line.lstrip().startswith("#")
    ]
    code_only = "\n".join(code_lines)
    # 模块级 import(不在 def/if 内)
    assert "from lumen_tasks.document_tasks import" not in code_only, (
        "celery_app.py 不该有 module-level "
        "'from lumen_tasks.document_tasks import ...',"
        "那会跟 document_tasks.py:6 'from lumen_tasks.celery_app import "
        "celery_app' 形成循环 import,"
        "Celery worker prefork pool 启动时撞死。"
        "改用 Celery(..., include=[...])。"
    )


def test_celery_app_can_be_imported_without_circular_error():
    """回归: import celery_app 本身不能抛 ImportError。"""
    # 强制 reload 确保从干净状态 import
    for mod_name in [
        "lumen_tasks.celery_app",
        "lumen_tasks.document_tasks",
    ]:
        sys.modules.pop(mod_name, None)
    try:
        from lumen_tasks.celery_app import celery_app
        assert celery_app is not None
        assert celery_app.main == "lumen_platform"
    except ImportError as e:
        pytest.fail(
            f"Import celery_app 抛 ImportError — 循环 import 未修:{e}"
        )


def test_celery_app_can_coexist_with_document_tasks_import():
    """回归: document_tasks 能正常 import celery_app(不撞循环)。
    """
    from lumen_tasks.celery_app import celery_app
    from lumen_tasks.document_tasks import process_document_task

    assert celery_app is not None
    assert process_document_task is not None
    # 任务是用 celery_app.task 装饰器注册的。task name 在 Celery 默认
    # 行为下用函数名 (``process_document``) — @celery_app.task(name=...)
    # 没传,所以是裸函数名。
    assert process_document_task.name == "process_document"
    # 任务注册到 celery_app.tasks(include 触发 import 后)
    assert "process_document" in celery_app.tasks


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
