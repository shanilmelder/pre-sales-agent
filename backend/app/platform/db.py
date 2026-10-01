"""Async SQLAlchemy engine (psycopg 3) and a liveness ping."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.platform.config import Settings
from app.platform.errors import DbUnavailableError
from app.platform.logging import get_logger

_log = get_logger(__name__)


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the engine. Connections are opened lazily, so this never touches the network."""
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": max(1, int(settings.db_connect_timeout_s))},
    )


async def ping(engine: AsyncEngine, timeout_s: float) -> None:
    """Run `SELECT 1`. Raises DbUnavailableError if the database can't be reached in time."""
    try:
        async with asyncio.timeout(timeout_s):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:
        _log.warning("db.ping_failed", extra={"exc_type": type(exc).__name__})
        raise DbUnavailableError("The database is not reachable.") from exc
