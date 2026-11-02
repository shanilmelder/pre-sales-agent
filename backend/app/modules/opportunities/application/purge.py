"""Registers opportunities' retention purge step, the retention selector and the row lock
(Story 10.6).
Imported by the worker only (`app.main_worker`), which runs the `platform.purge` job."""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.opportunities.adapters import purge
from app.modules.opportunities.application.retention import lock_if_due, retention_due
from app.platform.purge.registry import (
    RetentionDue,
    register_lock,
    register_selector,
    register_step,
)
from app.platform.uow import UnitOfWork

ORDER = 1000
"""Last: actuals and estimates reference the Opportunity row by foreign key."""


async def select_due(session: AsyncSession, before: date) -> list[RetentionDue]:
    """The purge's selector: retention date before `before`, on the purge role's session."""
    return await retention_due(UnitOfWork(session), before)


async def lock_due(
    session: AsyncSession, opportunity_id: UUID, before: date
) -> RetentionDue | None:
    """The purge's re-check, in its transaction: lock the row, apply the domain rule again."""
    return await lock_if_due(UnitOfWork(session), opportunity_id, before)


register_step("opportunities", ORDER, purge.purge_opportunity, tables=purge.TABLES)
register_selector(select_due)
register_lock(lock_due)
