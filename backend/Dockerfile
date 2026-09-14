# Multi-stage build: builder installs all dependencies, runtime copies venv + source.
FROM python:3.11-slim as builder

# 2026-06-16: Tsinghua mirror + 600s timeout for large wheels like jieba (19.2MB).
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
 && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn \
 && pip install --upgrade pip

WORKDIR /app

COPY requirements.txt .
# Install into venv to minimize bloat in final image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --timeout 600 -r requirements.txt


# Runtime layer: minimal footprint, only venv + app source.
FROM python:3.11-slim

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY gunicorn.conf.py .
COPY lumen_main.py .
COPY lumen_api lumen_api
COPY lumen_core lumen_core
COPY lumen_mcp_servers lumen_mcp_servers
COPY lumen_models lumen_models
COPY lumen_schemas lumen_schemas
COPY lumen_scripts lumen_scripts
COPY lumen_services lumen_services
COPY lumen_tasks lumen_tasks
COPY lumen_tools lumen_tools
COPY monitoring monitoring
COPY scripts scripts
COPY .env.docker .

EXPOSE 8000

# Phase 1 Group A 1.1 (2026-09-03): gunicorn 多 worker 化生产入口。
# dev 仍走 `uvicorn --reload`(单 worker,Windows 兼容,debug 友好);
# 生产镜像 CMD 走 gunicorn + uvicorn.workers.UvicornWorker —— workers 数
# 由 docker-compose / k8s 注入 WEB_WORKERS env(默认 = max(2, cpu_count()));
# scheduler 仅 WORKER_RANK=0 worker 启动(见 gunicorn.conf.py +
# lumen_main.py lifespan 守门)。
CMD ["gunicorn", "lumen_main:app", "-c", "gunicorn.conf.py", "--bind", "0.0.0.0:8000"]
