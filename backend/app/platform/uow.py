"""Unit of Work: one DB transaction per request or job step (AD-25, AD-3).

Commands take the `UnitOfWork` as their first argument, join its transaction and never
commit. Only the edge commits: `unit_of_work()` (job runners, scripts) and the FastAPI
dependency `get_uow` (request handlers). This is the only file allowed to call `.commit(`
(enforced by tests/test_architecture.py).

Handlers must signal errors by raising (a `ProblemError` subclass), never by returning an
error response: any normal return, whatever its status code, commits the transaction.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


class UnitOfWork:
    """Wraps the request's `AsyncSession`. It deliberately has no `commit`."""

    __slots__ = ("_session",)

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def flush(self) -> None:
        """Send pending writes now (surfaces constraint and version errors early)."""
        await self._session.flush()


@asynccontextmanager
async def unit_of_work(engine: AsyncEngine) -> AsyncIterator[UnitOfWork]:
    """Open a transaction; commit if the block returns, roll back if it raises."""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        try:
            yield UnitOfWork(session)
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def get_uow(request: Request) -> AsyncIterator[UnitOfWork]:
    """Request-scoped UoW. Use it through `UoW` so it runs with `scope="function"`: the
    commit then happens after the handler returns but before the response is sent, and a
    failing commit becomes a problem+json error instead of a lost write.

    Raise errors (`ProblemError`); don't return error responses, because a normal return
    commits."""
    async with unit_of_work(request.app.state.engine) as uow:
        yield uow


UoW = Annotated[UnitOfWork, Depends(get_uow, scope="function")]
