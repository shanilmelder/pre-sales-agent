"""The Opportunity outcome and its retention date (Story 10.5).

Three commands change `outcome`, `outcome_recorded_at` and `contract_end_date`, each on the
AD-3 path in the caller's Unit of Work: load the Opportunity the caller can read (404
otherwise), `identity.authorize`, the domain rules, `If-Match` on the Opportunity's
`row_version` (428 missing, 412 stale), the write, then one trace event:

- `record_outcome` (`opportunities.outcome.record`: the owner, not as a sales representative
  alone, or a Head of Delivery): close as `lost` with a reason, or mark `won` with a contract
  end date once a Baseline exists (409 `baseline_required`). With an outcome already recorded
  it is 409 `outcome_already_recorded`. Traces `opportunities.opportunity.closed`.
- `change_contract_end_date` (`opportunities.contract_end_date.update`: Head of Delivery and
  platform administrators): won only (409 `outcome_not_won`), with a reason. Traces
  `opportunities.contract_end_date.updated`; the same date again changes nothing.
- `reopen_outcome` (`opportunities.outcome.reopen`: as above): clears all three fields, with
  a reason (409 `outcome_not_recorded` when there is no outcome). Traces
  `opportunities.opportunity.reopened`.

Rule breaks are 422 `outcome_invalid` with an `errors` list of `{field, message}`. The
retention date is computed by `domain.opportunity.retention_until`, never stored. Trace
payloads carry the outcome, dates and the person's reason, nothing else of the customer's;
logs carry ids only.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.adapters import repository
from app.modules.opportunities.application.models import (
    ContractEndDateChange,
    Opportunity,
    OutcomeRecord,
    OutcomeReopen,
)
from app.modules.opportunities.application.opportunities import (
    MAX_ROW_VERSION,
    _detail,
    _load_readable,
    _stale,
    get,
)
from app.modules.opportunities.domain.opportunity import (
    REASON_MAX,
    SUBJECT_TYPE,
    Outcome,
    check_contract_end_date,
    outcome_reason,
    retention_until,
)
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    BaselineRequiredError,
    OutcomeAlreadyRecordedError,
    OutcomeInvalidError,
    OutcomeNotRecordedError,
    OutcomeNotWonError,
)
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    OpportunitiesContractEndDateUpdated,
    OpportunitiesOpportunityClosed,
    OpportunitiesOpportunityReopened,
)
from app.platform.uow import UnitOfWork

_log = get_logger(__name__)

REASON_RULE = f"Give a reason of 1 to {REASON_MAX:,} characters."
CONTRACT_END_REQUIRED = "Give the contract end date."


def _invalid(field: str, message: str) -> OutcomeInvalidError:
    return OutcomeInvalidError(message, errors=[{"field": field, "message": message}])


def _reason(value: str | None) -> str:
    try:
        return outcome_reason(value)
    except ValueError:
        raise _invalid("reason", REASON_RULE) from None


def _contract_end(value: date | None) -> date:
    if value is None:
        raise _invalid("contract_end_date", CONTRACT_END_REQUIRED)
    try:
        return check_contract_end_date(value)
    except ValueError as exc:
        raise _invalid("contract_end_date", f"The contract end date {exc}.") from None


async def _bump(uow: UnitOfWork, opportunity_id: UUID, if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        raise _stale()
    new_version = await repository.bump_row_version(uow, opportunity_id, expected)
    if new_version is None:
        raise _stale()
    return new_version


def _iso(value: date | None) -> str:
    assert value is not None
    return value.isoformat()


async def record_outcome(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    body: OutcomeRecord,
    if_match: str | None,
) -> Opportunity:
    """Close the Opportunity as lost or mark it won (module docstring)."""
    record, _, resource = await _load_readable(uow, actor, opportunity_id)
    identity.authorize(actor, Action.OUTCOME_RECORD, resource)
    if record.outcome is not None:
        raise OutcomeAlreadyRecordedError(
            "This Opportunity already has an outcome. Reopen it to record another."
        )
    reason: str | None = None
    contract_end: date | None = None
    if body.outcome is Outcome.LOST:
        reason = _reason(body.reason)
    else:
        contract_end = _contract_end(body.contract_end_date)
        if not await repository.has_baseline(uow, opportunity_id):
            raise BaselineRequiredError("An Opportunity can be marked won once it has a Baseline.")

    new_version = await _bump(uow, opportunity_id, if_match)
    recorded_at = datetime.now(UTC)
    await repository.write_outcome(
        uow,
        opportunity_id,
        outcome=body.outcome,
        recorded_at=recorded_at,
        contract_end_date=contract_end,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=OpportunitiesOpportunityClosed(
            outcome=body.outcome.value,
            reason=reason,
            contract_end_date=None if contract_end is None else contract_end.isoformat(),
            retention_until=_iso(retention_until(body.outcome, recorded_at, contract_end)),
        ),
        subject_type=SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
        subject_version=new_version,
    )
    _log.info(
        "opportunities.opportunity_closed",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": actor.actor.id,
            "outcome": body.outcome.value,
        },
    )
    return await get(uow, actor, opportunity_id)


async def change_contract_end_date(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    body: ContractEndDateChange,
    if_match: str | None,
) -> Opportunity:
    """Change a won Opportunity's contract end date (module docstring)."""
    record, members, resource = await _load_readable(uow, actor, opportunity_id)
    identity.authorize(actor, Action.CONTRACT_END_DATE_UPDATE, resource)
    if record.outcome is not Outcome.WON or record.contract_end_date is None:
        raise OutcomeNotWonError("Only a won Opportunity has a contract end date to change.")
    reason = _reason(body.reason)
    contract_end = _contract_end(body.contract_end_date)
    if contract_end == record.contract_end_date:
        # Nothing to change, but a stale view must still be told to reload.
        if record.row_version != parse_if_match(if_match):
            raise _stale()
        return await _detail(uow, actor, record, members, resource)

    new_version = await _bump(uow, opportunity_id, if_match)
    await repository.write_contract_end_date(uow, opportunity_id, contract_end)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=OpportunitiesContractEndDateUpdated(
            previous_contract_end_date=record.contract_end_date.isoformat(),
            contract_end_date=contract_end.isoformat(),
            reason=reason,
            retention_until=_iso(
                retention_until(Outcome.WON, record.outcome_recorded_at, contract_end)
            ),
        ),
        subject_type=SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
        subject_version=new_version,
    )
    _log.info(
        "opportunities.contract_end_date_updated",
        extra={"opportunity_id": str(opportunity_id), "actor_id": actor.actor.id},
    )
    return await get(uow, actor, opportunity_id)


async def reopen_outcome(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    body: OutcomeReopen,
    if_match: str | None,
) -> Opportunity:
    """Reopen an Opportunity with an outcome (module docstring)."""
    record, _, resource = await _load_readable(uow, actor, opportunity_id)
    identity.authorize(actor, Action.OUTCOME_REOPEN, resource)
    previous = record.outcome
    if previous is None:
        raise OutcomeNotRecordedError("This Opportunity has no outcome to reopen.")
    reason = _reason(body.reason)

    new_version = await _bump(uow, opportunity_id, if_match)
    await repository.write_outcome(
        uow, opportunity_id, outcome=None, recorded_at=None, contract_end_date=None
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=OpportunitiesOpportunityReopened(previous_outcome=previous.value, reason=reason),
        subject_type=SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
        subject_version=new_version,
    )
    _log.info(
        "opportunities.opportunity_reopened",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": actor.actor.id,
            "previous_outcome": previous.value,
        },
    )
    return await get(uow, actor, opportunity_id)
