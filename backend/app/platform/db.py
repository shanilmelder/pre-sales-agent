"""Async SQLAlchemy engine (psycopg 3), the declarative `Base` and a liveness ping."""

import asyncio

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.platform.config import Settings
from app.platform.errors import DbUnavailableError
from app.platform.logging import get_logger

_log = get_logger(__name__)

# Deterministic constraint and index names, so Alembic migrations can name them explicitly.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the engine. Connections are opened lazily, so this never touches the network.

    Sessions run in UTC so `timestamptz` values come back as UTC datetimes."""
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": max(1, int(settings.db_connect_timeout_s)),
            "options": "-c timezone=UTC",
        },
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
