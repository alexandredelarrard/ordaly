import logging
import os
import sys
from io import StringIO
from pathlib import Path

from dotenv import load_dotenv, find_dotenv
from omegaconf import DictConfig, OmegaConf
from logging.config import dictConfig
from typing import Optional

from src.utils.config import read_config
from src.utils.seed import set_seed

class AppContext:
    """Runtime context: settings, logger, storage paths."""

    def __init__(self, config: DictConfig) -> None:

        self.config = config
        self._load_env()
        self._setup_logging()

        self.log = logging.getLogger("ordaly")
        data = Path(self.config.data_root)
        if not data.is_absolute():
            data = (Path.cwd() / data).resolve()
        data.mkdir(parents=True, exist_ok=True)

        # default values 
        self.incoming_dir = (data / "incoming_documents").resolve()
        self.incoming_dir.mkdir(parents=True, exist_ok=True)

    def _setup_logging(self):
        """Setup logging configuration"""

        # create logging buffer
        buffer = StringIO()
        handler = logging.StreamHandler(buffer)
        formatter = logging.Formatter(self.config.logging.formatters.file.format)
        handler.setFormatter(formatter)
        logging.root.addHandler(handler)
        self.log_buffer = buffer

        self.log = logging.getLogger(__name__)

    def _load_env(self):
        """Load environment variables"""
        dot_env_file = find_dotenv(usecwd=True)
        if dot_env_file:
            load_dotenv(dot_env_file)
            logging.info(f"Loaded environment file: {dot_env_file}")
        else:
            logging.warning("No .env file found")

    @property
    def log_dir(self) -> Path:
        d = Path(self.config.log_dir)
        if not d.is_absolute():
            d = (Path.cwd() / d).resolve()
        return d

    @property
    def jwt_secret(self) -> str:
        return os.environ.get("JWT_SECRET_KEY")

    @property
    def jwt_algorithm(self) -> str:
        return os.environ.get("JWT_SECRET_KEY", "HS256")

    @property
    def jwt_access_token_expire_minutes(self) -> int:
        return os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 120)

    @property
    def cors_origins(self) -> list[str]:
        return os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

    @property
    def database_url(self) -> Optional[str]:
        return os.environ.get("DATABASE_URL", None)

    @property
    def sendgrid_api_key(self) -> Optional[str]:
        return os.environ.get("SENDGRID_API_KEY", None)

    @property
    def sendgrid_from_email(self) -> Optional[str]:
        return os.environ.get("SENDGRID_FROM_EMAIL", None)

    @property
    def sendgrid_from_name(self) -> Optional[str]:
        return os.environ.get("SENDGRID_FROM_NAME", None)
    
    @property
    def google_api_key(self) -> Optional[str]:
        return os.environ.get("GOOGLE_API_KEY", None)

    @property
    def openai_api_key(self) -> Optional[str]:
        return os.environ.get("OPENAI_API_KEY", None)
    
    @property
    def gemini_model_fast(self) -> Optional[str]:
        return self.config.gemini_model_fast or "gemini-2.0-flash"
    
    @property
    def gemini_model_pro(self) -> Optional[str]:
        return self.config.gemini_model_pro or "gemini-2.0-flash"
    

def get_config_context(config_path: str):

    try:
        config = read_config(path="./configs")
        log_root = Path(config.log_dir)
        if not log_root.is_absolute():
            log_root = (Path.cwd() / log_root).resolve()
        # One canonical path for API + Celery workers (hour-stamped files in MakeFileHandler).
        config.logging.handlers.file_handler.filename = str(log_root / "output.log")
        dictConfig(OmegaConf.to_container(config.logging, resolve=True))
        set_seed(config)

    except FileNotFoundError:
        print(f"configuration file {config_path} not found ", file=sys.stderr)
        sys.exit(1)

    context = AppContext(config=config)

    return config, context

config, context = get_config_context("./configs")