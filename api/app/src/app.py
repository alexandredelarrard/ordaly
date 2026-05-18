import logging
from contextlib import asynccontextmanager

import python_multipart
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.context import context, config
from src.routers import health, inbound_email, tasks
from src.utils.database import close_database, init_database

python_multipart.multipart.MULTIPART_MAX_PART_SIZE = 100 * 1024 * 1024

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = context.database_url
    if db_url:
        init_database(db_url)
        logger.info("Database engine initialized")
    yield
    await close_database()


def create_app() -> FastAPI:
    app = FastAPI(
        title=context.config.app_name,
        description="CRE underwriting inbound pipeline",
        version="0.2.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def bypass_ngrok_warning(request, call_next):
        response = await call_next(request)
        response.headers["ngrok-skip-browser-warning"] = "true"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=context.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(inbound_email.router)
    app.include_router(tasks.router)

    return app


app = create_app()
