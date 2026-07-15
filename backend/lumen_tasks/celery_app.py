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
    include=["lumen_tasks.document_tasks", "lumen_tasks.ppt_task"],
)

# Celery configuration
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
)

# Task registration 现在由 Celery 的 ``include`` 处理。worker 启动时
# Celery 会 import ``app.tasks.document_tasks``,触发 ``@celery_app.task``
# 装饰器跑,``process_document_task`` 自动注册。直接 module-level import
# 是 pre-M29.2.1 时代的 workaround,会撞循环 import — 已删。
