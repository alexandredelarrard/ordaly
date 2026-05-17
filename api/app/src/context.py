import logging
import os
import sys
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from src.schemas.settings import AppSettings


def load_environment() -> None:
    """Load ``.env`` into os.environ before ``AppSettings`` is built."""
    if os.getenv("ENV_FILE"):
        load_dotenv(os.environ["ENV_FILE"], override=False)
        return
    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path, override=False)


@lru_cache
def get_settings() -> AppSettings:
    load_environment()
    return AppSettings()


def setup_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_dir = settings.log_dir.expanduser()
    if not log_dir.is_absolute():
        log_dir = (Path.cwd() / log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    service = os.getenv("SERVICE_NAME", "app")
    log_file = log_dir / f"ordaly-{service}.log"

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    root = logging.getLogger()
    root.handlers.clear()

    file_handler = RotatingFileHandler(
        Path(log_file),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    root.setLevel(level)

    log = logging.getLogger("ordaly.context")
    log.info("Logging to %s (level=%s)", str(log_file), level)


class AppContext:
    """Runtime context: settings, logger, storage paths."""

    def __init__(self) -> None:
        setup_logging()
        self.settings = get_settings()
        self.log = logging.getLogger("ordaly")
        data = self.settings.data_root.expanduser()
        if not data.is_absolute():
            data = (Path.cwd() / data).resolve()
        data.mkdir(parents=True, exist_ok=True)
        self.incoming_dir = (data / "incoming_documents").resolve()
        self.incoming_dir.mkdir(parents=True, exist_ok=True)

    @property
    def log_dir(self) -> Path:
        d = self.settings.log_dir.expanduser()
        if not d.is_absolute():
            d = (Path.cwd() / d).resolve()
        return d

    @property
    def jwt_secret(self) -> str:
        return self.settings.jwt_secret_key

    @property
    def jwt_algorithm(self) -> str:
        return self.settings.jwt_algorithm

    @property
    def jwt_access_token_expire_minutes(self) -> int:
        return self.settings.jwt_access_expire_minutes

    @property
    def cors_origins(self) -> list[str]:
        return self.settings.cors_origins_list()


context = AppContext()
