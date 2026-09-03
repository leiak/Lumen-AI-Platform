FROM python:3.11-slim

# 2026-06-16: switched to Tsinghua mirror + bumped pip install timeout to 600s.
# pypi.org reads from China routinely timeout on large wheels like jieba (19.2MB)
# at <10 kB/s, breaking fresh `docker compose build celery_worker`. Mirror avoids
# the slow path entirely; timeout is a belt-and-braces fallback.
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
 && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn \
 && pip install --upgrade pip

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 600 -r requirements.txt

COPY . .

EXPOSE 8000

# Phase 1 Group A 1.1 (2026-09-03): gunicorn 多 worker 化生产入口。
# dev 仍走 `uvicorn --reload`(单 worker,Windows 兼容,debug 友好);
# 生产镜像 CMD 走 gunicorn + uvicorn.workers.UvicornWorker —— workers 数
# 由 docker-compose / k8s 注入 WEB_WORKERS env(默认 = max(2, cpu_count()));
# scheduler 仅 WORKER_RANK=0 worker 启动(见 gunicorn.conf.py +
# lumen_main.py lifespan 守门)。
CMD ["gunicorn", "lumen_main:app", "-c", "gunicorn.conf.py", "--bind", "0.0.0.0:8000"]
