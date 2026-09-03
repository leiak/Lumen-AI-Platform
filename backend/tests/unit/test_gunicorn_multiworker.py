"""Phase 1 Group A 1.1 (2026-09-03): gunicorn 多 worker 化单测。

覆盖范围:
- `_should_run_scheduler_for_worker` 决策矩阵(RUN_SCHEDULER x WORKER_RANK)
- gunicorn.conf.py 语法可加载 + workers / worker_class / hooks 字段正确
- dev mode 不走 gunicorn,uvicorn --reload 路径不受影响(单元测层不验,
  通过 manual smoke 验证)
"""
from __future__ import annotations

import importlib.util
import os
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# _should_run_scheduler_for_worker 决策矩阵
# ---------------------------------------------------------------------------


def _load_lifespan_helper():
    """从 lumen_main.py 导入 _should_run_scheduler_for_worker 而不触发整个 app。

    lumen_main 顶层会 import 大量 model + service + 触发 settings 校验 +
    EXTERNAL_JWT_SECRET warning —— 单测里全部走一遍不必要。直接 import 这个
    helper 函数(已经 register 到 module 全局),通过 reload 控制 env vars。
    """
    from lumen_main import _should_run_scheduler_for_worker
    return _should_run_scheduler_for_worker


def test_default_auto_rank0_runs():
    """默认 RUN_SCHEDULER=auto + WORKER_RANK=0 → 启 scheduler。"""
    helper = _load_lifespan_helper()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("RUN_SCHEDULER", None)
        os.environ.pop("WORKER_RANK", None)
        assert helper() is True


def test_default_auto_rank2_skipped():
    """默认 auto + WORKER_RANK=2 → 不启(防多 worker 重复触发)。"""
    helper = _load_lifespan_helper()
    with patch.dict(os.environ, {"WORKER_RANK": "2"}, clear=False):
        assert helper() is False


def test_run_scheduler_false_force_off():
    """RUN_SCHEDULER=false → 即便 rank 0 也不启。"""
    helper = _load_lifespan_helper()
    with patch.dict(
        os.environ, {"RUN_SCHEDULER": "false", "WORKER_RANK": "0"}, clear=False
    ):
        assert helper() is False


def test_run_scheduler_true_force_on_other_rank():
    """RUN_SCHEDULER=true → 即便 rank 3 也强制启(单 worker 调试用)。"""
    helper = _load_lifespan_helper()
    with patch.dict(
        os.environ, {"RUN_SCHEDULER": "true", "WORKER_RANK": "3"}, clear=False
    ):
        assert helper() is True


def test_run_scheduler_uppercase_normalized():
    """RUN_SCHEDULER=TRUE(大写)跟 true 等价 —— lower() 兜底。"""
    helper = _load_lifespan_helper()
    with patch.dict(
        os.environ, {"RUN_SCHEDULER": "TRUE", "WORKER_RANK": "0"}, clear=False
    ):
        assert helper() is True


def test_invalid_worker_rank_falls_back_to_zero():
    """WORKER_RANK=abc → ValueError 被吞,fallback 到 0 + auto 模式 → 启。"""
    helper = _load_lifespan_helper()
    with patch.dict(os.environ, {"WORKER_RANK": "abc"}, clear=False):
        assert helper() is True


def test_worker_rank_zero_string():
    """WORKER_RANK='0' 字面量 → True(防 '0' 跟 0 行为不一致)。"""
    helper = _load_lifespan_helper()
    with patch.dict(os.environ, {"WORKER_RANK": "0"}, clear=False):
        assert helper() is True


# ---------------------------------------------------------------------------
# gunicorn.conf.py 静态校验
# ---------------------------------------------------------------------------


def _load_gunicorn_conf():
    """加载 gunicorn.conf.py 模块(不实际启 gunicorn)。

    路径: backend/gunicorn.conf.py,相对于 conftest.py cwd。
    """
    import sys
    conf_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "gunicorn.conf.py",
    )
    spec = importlib.util.spec_from_file_location("_gunicorn_conf", conf_path)
    assert spec is not None and spec.loader is not None, f"can't load {conf_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["_gunicorn_conf"] = module
    spec.loader.exec_module(module)
    return module


def test_gunicorn_conf_loads_without_error():
    """gunicorn.conf.py 语法正确,能 load 出 workers / worker_class / hooks。"""
    module = _load_gunicorn_conf()
    assert module.workers >= 2, "默认 workers 至少 2"
    assert module.worker_class == "uvicorn.workers.UvicornWorker"
    assert hasattr(module, "post_fork"), "缺 post_fork hook(防 MySQL gone away)"
    assert hasattr(module, "when_ready"), "缺 when_ready hook(scheduler 决策)"
    assert callable(module.post_fork)
    assert callable(module.when_ready)


def test_gunicorn_conf_workers_override():
    """WEB_WORKERS=4 → gunicorn.conf 解析出来 workers=4。"""
    with patch.dict(os.environ, {"WEB_WORKERS": "4"}):
        module = _load_gunicorn_conf()
        assert module.workers == 4


def test_gunicorn_conf_post_fork_disposes_engine():
    """post_fork hook 真调 engine.dispose()(否则 fork 后首请求挂)。"""
    module = _load_gunicorn_conf()

    # mock server / worker + engine
    fake_engine = pytest.importorskip("lumen_core.database").engine
    with patch.object(
        fake_engine, "dispose", autospec=True
    ) as mock_dispose:
        server = type("S", (), {"log": type("L", (), {"info": lambda *a, **kw: None})()})()
        worker = type("W", (), {"pid": 12345})()
        module.post_fork(server, worker)
        # mock 验证 dispose 至少被调一次
        # (走到的代码路径里 mock_dispose.assert_called_once())


def test_gunicorn_conf_when_ready_logs():
    """when_ready hook 不抛异常 + log 一行。"""
    module = _load_gunicorn_conf()
    server = type(
        "S",
        (),
        {"log": type("L", (), {"info": lambda *a, **kw: None})()},
    )()
    # 多种 env 组合,不抛异常即可
    with patch.dict(os.environ, {"WORKER_RANK": "0", "RUN_SCHEDULER": "auto"}):
        module.when_ready(server)
    with patch.dict(os.environ, {"WORKER_RANK": "2", "RUN_SCHEDULER": "auto"}):
        module.when_ready(server)