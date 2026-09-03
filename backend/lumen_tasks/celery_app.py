from celery import Celery
from lumen_core.config import settings

# Create Celery app
# M29.2.1 (2026-06-16): 用 Celery 内置的 ``include`` 参数声明 task 模块,
# 而不是 module-level ``from lumen_tasks.document_tasks import ...`` ——
# 后者会让 celery_app.py 和 document_tasks.py 形成循环 import:
#  - celery_app.py line 31 触发 document_tasks.py load
#  - document_tasks.py line 6 反向 `from celery_app import celery_app`
#  - celery_app.py 此时正在加载中 → ImportError "partially initialized module"
# 用 ``include`` 让 Celery worker 启动时自动 import document_tasks
# (那时 celery_app 已完全加载,document_tasks import 成功)。
celery_app = Celery(
    "lumen_platform",
    broker=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
    backend=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
    include=["lumen_tasks.document_tasks", "lumen_tasks.ppt_task", "lumen_tasks.eval_tasks"],
)

# Celery configuration
# Phase 1 Group A 1.3 (2026-09-03):多 queue + task_routes + acks_late +
# trace_signals worker_init 接入。
#
# **task_routes 决策**(为什么 3 个 queue):
# - doc_parse:知识库文档处理(parse + chunk + embed)。CPU + IO 重,需要
#   与其他任务隔离,免 PPT / eval 长任务占满 worker 池。
# - ppt_gen:PPT 视频生成,长任务(可能 30min+),独立 worker + 高并发。
# - eval_run:RAG 评测,可能 1h+(soft_time_limit=7200s),独立 worker + 单
#   并发避免互相干扰。
# - default:兜底 queue,celery_worker_doc `-Q doc_parse,default` 接住所有
#   没有路由的任务(防无人接死信)。
#
# **acks_late + reject_on_worker_lost**:任务真正完成后才 ack;worker
# crash 进程被 kill 触发 task_reject_on_worker_lost 重新入队,防丢任务。
# Phase 0 ship 时这些 flag 默认 False —— 文档 parse 跑到一半 worker
# SIGKILL 会让 doc status 永远 pending,Phase 1 必须开。
#
# **worker_init 装 trace_signals**(Phase 0 ship 但未接入):
# 每个 worker 启动时跑一次,装 task_prerun/task_postrun/before_task_publish
# 三个信号,实现 trace_id 跨 process 贯通。
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    worker_prefetch_multiplier=1,
    # Windows 上 prefork pool 有 billiard bug: spawn 模式下
    # fast_trace_task 无法访问 _loc，导致 PENDING 后立即 ERROR。
    # 改用 threads pool 避免跨进程问题。
    worker_pool="threads",
    # ---- Phase 1 Group A 1.3 多 queue + 可靠投递 ----
    task_routes={
        # 按模块命名空间路由,涵盖每个 module 下所有 task(包括将来新加的)
        "lumen_tasks.document_tasks.*": {"queue": "doc_parse"},
        "lumen_tasks.ppt_task.*": {"queue": "ppt_gen"},
        "lumen_tasks.eval_tasks.*": {"queue": "eval_run"},
    },
    task_default_queue="default",
    # ack late:任务**真正完成后**才 ack;worker 中途 crash 任务不 ack
    # → broker requeue → 其他 worker 接手。
    task_acks_late=True,
    # worker 进程 lost(was killed / OOM / host reboot)拒绝消息,触发 requeue
    task_reject_on_worker_lost=True,
    # celery events 可观察(flower / celery events 命令行)
    worker_send_task_events=True,
)


# ---- Phase 1 Group A 1.3: trace_signals 接入 ----
# worker_init 信号:每个 celery worker 启动时跑一次,装 trace_id 信号链。
# 装在 celery_app module 顶部 import 时不会触发,只有 worker 进程 fork
# 出来才会 emit worker_init —— 这跟 FastAPI startup_event 必须在 lifespan
# 里跑同理(模块顶层 import 不等于 worker 启动)。
from celery.signals import worker_init  # noqa: E402


@worker_init.connect
def _on_worker_init(**_kwargs) -> None:
    """worker 启动钩子:装 trace_id 信号链。

    Phase 0 ship 了 trace_signals.py 但未接入 —— 本任务必修。
    装完后:
    - producer 端发 task 时 ctx 有 trace_id → before_task_publish 写到 headers
    - worker 端 task_prerun 读 headers 注入 ctx
    - worker 端 task_postrun 清 ctx(防串下一个 task)
    """
    from lumen_tasks.trace_signals import install_celery_signals
    install_celery_signals()


# Task registration 现在由 Celery 的 ``include`` 处理。worker 启动时
# Celery 会 import ``app.tasks.document_tasks``,触发 ``@celery_app.task``
# 装饰器跑,``process_document_task`` 自动注册。直接 module-level import
# 是 pre-M29.2.1 时代的 workaround,会撞循环 import — 已删。
