"""The LangGraph checkpointer (AD-6; Story 5.2): `AsyncPostgresSaver` on its own
`AsyncConnectionPool`, with `autocommit=True`, `row_factory=dict_row` and `search_path =
orchestration_checkpoints` (a schema the migrations create and grant to the app role; the
library creates its tables there with `setup()`). Checkpoints hold ids only.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.platform.db import libpq_url

SCHEMA = "orchestration_checkpoints"


def connection_kwargs() -> dict[str, Any]:
    return {
        "autocommit": True,
        "row_factory": dict_row,
        "prepare_threshold": 0,
        "options": f"-c search_path={SCHEMA} -c timezone=UTC",
    }


@asynccontextmanager
async def open_checkpointer(
    database_url: str, *, min_size: int = 1, max_size: int = 4, setup: bool = True
) -> AsyncIterator[AsyncPostgresSaver]:
    """A saver on a pool opened here (without waiting for a connection) and closed on exit.
    `setup` creates or migrates the library's tables (idempotent) before yielding."""
    pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] = AsyncConnectionPool(
        libpq_url(database_url),
        min_size=min_size,
        max_size=max_size,
        kwargs=connection_kwargs(),
        open=False,
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(conn=pool)
        if setup:
            await saver.setup()
        yield saver
    finally:
        await pool.close()
