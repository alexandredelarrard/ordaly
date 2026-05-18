"""
Celery app.

Logging must match FastAPI: ``dictConfig`` from ``logging.yml`` runs when ``src.context``
loads (same ``ColorHandler`` + ``MakeFileHandler`` as the API). Celery’s default
``worker_hijack_root_logger=True`` replaces root handlers and drops the shared file
handler — keep it disabled so worker logs go to the same file tree under ``log_dir``.
"""

import os

# Load context first so ``get_config_context`` applies logging before Celery configures workers.
from src.context import config, context  # noqa: F401

from celery import Celery

_broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

celery = Celery(
    "ordaly",
    broker=_broker,
    backend=_broker,
    include=["src.celery.tasks.pdf_parse"],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    worker_hijack_root_logger=False,
)
