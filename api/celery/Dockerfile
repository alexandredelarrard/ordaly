FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Build context = api/ (parent). Keeps app requirements single source of truth.
COPY app/requirements.txt /app/requirements.txt
COPY celery/requirements-celery.txt /app/requirements-celery.txt

RUN pip install --upgrade pip && pip install --no-cache-dir -r /app/requirements-celery.txt

COPY app/ /app/

CMD ["celery", "-A", "src.celery.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
