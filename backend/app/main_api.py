"""`api` process entry point: HTTP only, never runs agents, graphs or parsing (AD-1)."""

import asyncio
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, FastAPI, Request, Response
from pydantic import BaseModel

from app.platform.config import Settings, get_settings
from app.platform.db import create_engine, ping
from app.platform.errors import (
    PROBLEM_JSON,
    Problem,
    install_error_handlers,
    unhandled_error_response,
)
from app.platform.logging import configure_logging, get_logger

API_PREFIX = "/api/v1"
REQUEST_ID_HEADER = "X-Request-ID"
_log = get_logger("app.api")


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    db: Literal["ok"]


def _health_router() -> APIRouter:
    router = APIRouter(tags=["platform"])

    @router.get(
        "/health",
        operation_id="get_health",
        responses={
            503: {
                "description": "Database unavailable (`db_unavailable`)",
                "content": {PROBLEM_JSON: {"schema": Problem.model_json_schema()}},
            }
        },
    )
    async def health(request: Request) -> HealthResponse:
        settings: Settings = request.app.state.settings
        await ping(request.app.state.engine, timeout_s=settings.db_connect_timeout_s + 1)
        return HealthResponse(status="ok", version=settings.version, db="ok")

    return router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        _log.info("api.started", extra={"version": settings.version, "env": settings.env})
        yield
        await engine.dispose()

    app = FastAPI(
        title="Pre-Sales Agent API",
        version=settings.version,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            response = await unhandled_error_response(request, exc)
        response.headers[REQUEST_ID_HEADER] = request_id
        _log.info(
            "http.request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    app.include_router(_health_router(), prefix=API_PREFIX)
    return app


app = create_app()


def main() -> None:
    """Local run (`uv run python -m app.main_api`); uses a selector loop, which psycopg's
    async driver needs on Windows. Containers run uvicorn directly."""
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_config=None)
    server = uvicorn.Server(config)
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(server.serve(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
