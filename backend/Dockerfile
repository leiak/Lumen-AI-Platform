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

CMD ["uvicorn", "lumen_main:app", "--host", "0.0.0.0", "--port", "8000"]
