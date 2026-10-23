from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from costopt.api.routes import router
from costopt.config import settings
from costopt.observability.logging import configure_logging, get_logger
from costopt.storage.migrations import apply_migrations
from costopt.storage.sqlite import get_connection


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Apply database migrations when the server starts, not when modules are imported."""
    with get_connection() as connection:
        apply_migrations(connection)
    yield


def create_app() -> FastAPI:
    configure_logging()
    logger.info(
        "CostOpt API initialization started",
        extra={"event": "api_initialization_started", "environment": settings.environment},
    )
    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description="CostOpt workforce optimization API with a local data runtime",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173", "http://localhost:5173",
            "http://127.0.0.1:4173", "http://localhost:4173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "environment": settings.environment,
            "procurement_enabled": settings.enable_procurement,
            "compliance_mode": "mock" if settings.use_mock_compliance else "provider",
            "gemini_explanations_configured": settings.gemini_api_key is not None,
            "gemini_model": settings.gemini_model,
        }

    app.include_router(router, prefix="/api/v1")
    logger.info(
        "CostOpt API initialization completed",
        extra={"event": "api_initialization_completed", "environment": settings.environment},
    )
    return app


app = create_app()
