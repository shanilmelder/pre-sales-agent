"""The retention purge's registry (Story 10.6): what each module contributes to the purge.

`platform` never imports a business module, so modules register their parts here at import
(their `application/purge.py`, loaded by the worker, see `app.main_worker`):

- **steps** (`register_step`): one per module that holds Opportunity data. A step deletes that
  module's rows for one Opportunity, on the session it is given (the purge role's
  transaction, never the app's), and returns how many rows it deleted plus the SHA-256 of
  every file reference those rows held (one entry per reference). `tables` names every table
  the step empties, cascaded children included: `test_purge.py` fails when a table with an
  `opportunity_id` column is in no step. Steps run in ascending `order` (then module name),
  so a module whose rows others reference by foreign key (`opportunities`) runs last.
- **the selector** (`register_selector`): the Opportunities whose retention date is before a
  given day, computed with the owning module's domain rule (never SQL date arithmetic).
- **the lock** (`register_lock`): inside the purge transaction, locks one Opportunity's row
  (`SELECT ... FOR UPDATE`) and re-checks it with the domain rule, so an Opportunity reopened,
  changed or already purged since it was selected is skipped.
- **run ids** (`register_run_ids`): the workflow runs of an Opportunity, collected before any
  step runs, so the platform's own rows tied to a run (trace, model and tool calls) go too.

Everything here holds ids and counts only.
"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class StepResult:
    rows: int
    """Rows deleted, cascaded children included when the step counts them."""
    released_sha256: list[str] = field(default_factory=list)
    """One entry per file reference the deleted rows held (`platform_files`)."""


type PurgeStepFn = Callable[[AsyncSession, UUID], Awaitable[StepResult]]


@dataclass(frozen=True, slots=True)
class PurgeStep:
    module: str
    order: int
    fn: PurgeStepFn
    tables: frozenset[str]


class RetentionRule(StrEnum):
    """Which retention rule made an Opportunity due (Story 10.5's periods)."""

    LOST_3Y = "lost_3y"
    WON_7Y = "won_7y"


@dataclass(frozen=True, slots=True)
class RetentionDue:
    opportunity_id: UUID
    outcome: str
    """`won` or `lost`."""
    rule: RetentionRule
    retention_until: date
    """The last day the data is kept; due for purge from the day after."""


type RetentionSelector = Callable[[AsyncSession, date], Awaitable[list[RetentionDue]]]
"""Every Opportunity whose retention date is before the given day, earliest first."""

type RetentionLock = Callable[[AsyncSession, UUID, date], Awaitable[RetentionDue | None]]
"""Lock the Opportunity's row and return its due state if its retention date is still before
the given day; None when it is gone or no longer due."""

type RunIdsFn = Callable[[AsyncSession, UUID], Awaitable[list[UUID]]]

_STEPS: list[PurgeStep] = []
_SELECTORS: list[RetentionSelector] = []
_RUN_IDS: list[RunIdsFn] = []
_LOCKS: list[RetentionLock] = []


class PurgeNotWiredError(RuntimeError):
    """No module registered the retention selector (a deployment error: the worker loads the
    modules' purge registrations)."""


async def delete_rows(
    session: AsyncSession, statements: Iterable[str], opportunity_id: UUID
) -> int:
    """Run each `DELETE` (SQL binding `:opportunity_id`) in order; rows deleted in all. For
    module steps, which delete children before their parents so every row is counted."""
    deleted = 0
    for statement in statements:
        result = await session.execute(text(statement), {"opportunity_id": opportunity_id})
        deleted += int(result.rowcount)  # type: ignore[attr-defined]
    return deleted


async def delete_returning(
    session: AsyncSession, statement: str, opportunity_id: UUID
) -> tuple[int, list[str]]:
    """Run one `DELETE ... RETURNING <sha256 column>`: rows deleted and the non-null values
    returned (one per file reference)."""
    result = await session.execute(text(statement), {"opportunity_id": opportunity_id})
    values: list[str | None] = list(result.scalars())
    return len(values), [value for value in values if value is not None]


def register_step(module: str, order: int, fn: PurgeStepFn, *, tables: Iterable[str]) -> None:
    """Add a module's purge step. One step per module."""
    if any(step.module == module for step in _STEPS):
        raise ValueError(f"module {module!r} already registered a purge step")
    names = frozenset(tables)
    if not names:
        raise ValueError("a purge step must name the tables it empties")
    _STEPS.append(PurgeStep(module=module, order=order, fn=fn, tables=names))


def register_selector(fn: RetentionSelector) -> None:
    if _SELECTORS:
        raise ValueError("the retention selector is already registered")
    _SELECTORS.append(fn)


def register_lock(fn: RetentionLock) -> None:
    if _LOCKS:
        raise ValueError("the retention lock is already registered")
    _LOCKS.append(fn)


def lock() -> RetentionLock:
    if not _LOCKS:
        raise PurgeNotWiredError("no retention lock is registered")
    return _LOCKS[0]


def register_run_ids(fn: RunIdsFn) -> None:
    _RUN_IDS.append(fn)


def steps() -> list[PurgeStep]:
    """The registered steps in the order they run."""
    return sorted(_STEPS, key=lambda step: (step.order, step.module))


def selector() -> RetentionSelector:
    if not _SELECTORS:
        raise PurgeNotWiredError("no retention selector is registered")
    return _SELECTORS[0]


def run_id_providers() -> list[RunIdsFn]:
    return list(_RUN_IDS)


def covered_tables() -> frozenset[str]:
    """Every table some registered step empties."""
    return frozenset(name for step in _STEPS for name in step.tables)
