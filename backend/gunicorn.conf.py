"""Phase 1 Group A 1.1 (2026-09-03): gunicorn 多 worker 配置。

**为什么需要 gunicorn**: Phase 0 dev 一直 `uvicorn --reload` 单 worker,
阻塞型 endpoint(`/videos/compose` / `/image-generation` 等)在单 worker 下
互相抢占;Phase 1 1.1 引入 gunicorn 多 worker 化,生产环境并行处理 + 任意
worker 挂掉 K8s / supervisor 都能立即拉新。

**关键设计**:

1. **dev vs 进程**:
   - dev (`uvicorn --reload`):Windows 兼容 + debug 友好,单 worker,默认启 scheduler
   - prod (`gunicorn -c gunicorn.conf.py`):Linux / K8s,多 worker,仅 worker 0 启 scheduler

2. **post_fork**: SQLAlchemy engine 在 fork 时持有父进程已 open 的 DB socket,
   必须子进程 dispose 重建,否则"MySQL server has gone away"挂首请求。
   跟 Phase 0 a1df16b ship 的 K8s shutdown dispose 同模式。

3. **scheduler 单 worker**: retention / workflow scheduler 都是单例 + 内存
   job store,跑在 N 个 worker 会重复触发 + race 写 DB。仅 worker 0
   (rank=0) 才启。WORKER_RANK 由 docker-compose / k8s 注入,auto 模式
   gunicorn 自动给每个 worker 0..N-1 编号。

4. **lifespan 触发**: gunicorn UvicornWorker fork 后子进程跑 startup lifespan,
   所以 lifespan 函数必须保持 idemponent + 单 worker 0 才启 scheduler。
   when_ready 在 master 派完所有 worker 之后调一次(用于日志 / 校验),
   per-worker 启动 lifespan。
"""
import logging
import multiprocessing
import os

# ---------------------------------------------------------------------
# Worker / server config
# ---------------------------------------------------------------------

workers = int(os.getenv("WEB_WORKERS", max(2, multiprocessing.cpu_count())))
worker_class = "uvicorn.workers.UvicornWorker"

timeout = int(os.getenv("WEB_TIMEOUT", 120))
graceful_timeout = 30
keepalive = 5

# preload_app: master 进程 import app(只 import,不 serve),子进程 fork 时继承
# 已加载的 module state —— 节省内存(每个 worker 不重复 load numpy/torch/
# transformers)。但**有副作用 —— 子进程的 module-level 全局变量是 fork 时
# 的快照**:lumen_main 的 `_startup_complete=False` 是 module-level,不影响
# 因为子进程 lifespan startup 会 flip;SQLAlchemy engine 是 module-level 单例
# 必须 post_fork dispose。
preload_app = True


# ---------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------


def post_fork(server, worker):  # noqa: D401, ARG001
    """每个 worker fork 后立即 dispose SQLAlchemy engine pool。

    fork 之后子进程继承的 DB socket 实际是父进程的;MySQL server 视角这个连接
    是父进程在用,子进程第一次 query 经常 "MySQL server has gone away"。
    dispose() 关闭所有 connection,下一次 query 自动重建(对每个子进程的
    engine 透明)。
    """
    try:
        from lumen_core.database import engine
        engine.dispose()
        server.log.info("worker pid=%s: engine pool disposed", worker.pid)
    except Exception as e:  # noqa: BLE001
        server.log.warning("worker pid=%s: engine.dispose() failed: %s", worker.pid, e)


def when_ready(server):  # noqa: D401, ARG001
    """所有 worker fork 之后,master 决定是否启 scheduler。

    scheduler 是单例 + 内存 job store,只能跑在一个进程。仅 WORKER_RANK=0
    worker 的 lifespan startup 会启,其他 worker 的 lifespan 跳过。
    RUN_SCHEDULER 显式控制:
    - "true":强制启(单 worker 模式 / 调试用)
    - "false":强制不启
    - "auto"(默认):WORKER_RANK=0 才启
    """
    _worker_rank = int(os.getenv("WORKER_RANK", "0"))
    run_scheduler = os.getenv("RUN_SCHEDULER", "auto").lower()
    server.log.info(
        "gunicorn master ready: workers=%s worker_rank=%s run_scheduler=%s",
        workers, _worker_rank, run_scheduler,
    )


def worker_int(worker):  # noqa: D401, ARG001
    """SIGINT / SIGQUIT — 让 worker 走 graceful shutdown。"""
    worker.log.info("worker pid=%s: SIGINT/SIGQUIT received", worker.pid)


def on_exit(server):  # noqa: D401, ARG001
    """master 退出时记录 —— K8s 滚动更新会触发。"""
    server.log.info("gunicorn master exiting")