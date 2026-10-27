"""The shared per-Opportunity lock (AD-26, Story 9.7).

`opportunity_lock(uow, opportunity_id)` takes `pg_advisory_xact_lock(<bigint>)` until the Unit
of Work commits or rolls back. The key is the first 8 bytes of the Opportunity's UUID as a
signed big-endian integer, so every module computes the same key without a shared table.

Every command that changes what the Baseline checks read takes it: Estimate drafting, line,
Assumption and Risk edits, submit, New version and `set_baseline` (`estimates`); Gap
detection, dismissal, answers and conversion (`gaps`); Finding overrides and resolutions
(`assessments`); Review Requests, decisions and replies (`reviews`); and an assessment run's
bookkeeping (`workflows`, before its own run lock, since finishing a run builds an Estimate
Version). Postgres advisory locks are re-entrant within a session, so a nested call is safe.
Any path that also takes a module lock takes this one first.
"""

from uuid import UUID

from sqlalchemy import text

from app.platform.uow import UnitOfWork


def opportunity_lock_key(opportunity_id: UUID) -> int:
    """The advisory lock key: the UUID's first 8 bytes as a signed big-endian bigint."""
    return int.from_bytes(opportunity_id.bytes[:8], "big", signed=True)


async def opportunity_lock(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Serialise the Opportunity's Baseline-affecting commands until commit (see the module
    docstring)."""
    await uow.session.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:key AS bigint))"),
        {"key": opportunity_lock_key(opportunity_id)},
    )
