"""The retention schedule (Story 10.6): which Opportunities' data is due for purge.

`retention_due` applies the domain rule (`domain.opportunity.retention_until`: lost, the day
the outcome was recorded plus 3 years; won, the contract end date plus 7 years) to every
Opportunity with an outcome; open ones have no retention date and are never listed. It is the
`platform.purge` job's selector (registered by `application.purge`, on the purge role's
session) and feeds Admin > Retention (`retention_overview`, platform administrators only:
`platform.retention.read`). Ids, outcomes and dates only: no title or customer name.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.adapters import repository
from app.modules.opportunities.application.models import (
    PurgeEventItem,
    RetentionDueItem,
    RetentionOverview,
)
from app.modules.opportunities.domain.opportunity import Outcome, retention_until
from app.platform.purge.history import recent_purges
from app.platform.purge.registry import RetentionDue, RetentionRule
from app.platform.uow import UnitOfWork

UPCOMING_DAYS = 30
"""Admin > Retention lists the Opportunities due within this many days (and overdue ones)."""
_RULES = {Outcome.LOST: RetentionRule.LOST_3Y, Outcome.WON: RetentionRule.WON_7Y}


def _due(
    opportunity_id: UUID,
    raw: str | None,
    recorded_at: datetime | None,
    contract_end: date | None,
    before: date,
) -> RetentionDue | None:
    """The domain rule: due when the retention date is before `before`."""
    if raw is None or recorded_at is None:
        return None
    outcome = Outcome(raw)
    until = retention_until(outcome, recorded_at.astimezone(UTC), contract_end)
    if until is None or until >= before:
        return None
    return RetentionDue(
        opportunity_id=opportunity_id,
        outcome=outcome.value,
        rule=_RULES[outcome],
        retention_until=until,
    )


async def retention_due(uow: UnitOfWork, before: date) -> list[RetentionDue]:
    """Every Opportunity whose retention date is before `before`, earliest first."""
    due: list[RetentionDue] = []
    for opportunity_id, raw, recorded_at, contract_end in await repository.recorded_outcomes(uow):
        item = _due(opportunity_id, raw, recorded_at, contract_end, before)
        if item is not None:
            due.append(item)
    return sorted(due, key=lambda item: (item.retention_until, item.opportunity_id))


async def lock_if_due(uow: UnitOfWork, opportunity_id: UUID, before: date) -> RetentionDue | None:
    """The purge's re-check: lock the Opportunity's row and return its due state if its
    retention date is still before `before`; None when it is gone or no longer due."""
    found = await repository.lock_outcome(uow, opportunity_id)
    if found is None:
        return None
    return _due(opportunity_id, *found, before)


def today_utc() -> date:
    return datetime.now(UTC).date()


async def retention_overview(
    uow: UnitOfWork, actor: Principal, today: date | None = None
) -> RetentionOverview:
    """Admin > Retention: the Opportunities whose retention date is on or before today plus
    `UPCOMING_DAYS` (overdue ones not yet purged included), and the last purges. Read only."""
    identity.authorize(actor, Action.RETENTION_READ)
    day = today or today_utc()
    due = await retention_due(uow, day + timedelta(days=UPCOMING_DAYS + 1))
    recent = await recent_purges(uow)
    return RetentionOverview(
        due=[
            RetentionDueItem(
                opportunity_id=str(item.opportunity_id),
                outcome=Outcome(item.outcome),
                rule=item.rule.value,
                retention_until=item.retention_until,
            )
            for item in due
        ],
        recent=[
            PurgeEventItem(
                purged_opportunity_id=str(record.purged_opportunity_id),
                rule=record.rule,
                rows_by_module=record.rows_by_module,
                files_deleted=record.files_deleted,
                occurred_at=record.occurred_at,
            )
            for record in recent
        ],
    )
