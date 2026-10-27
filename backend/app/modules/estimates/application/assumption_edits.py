"""A person's edit of an Assumption (Story 8.5).

**Editing** (`estimates.assumption.edit`: the owner and collaborators except sales
representatives; other readers 403, everyone else the Opportunity's 404): `edit_assumption`
takes a new kind, wording, hours and/or line (fields left out stay as they are) and a reason
(trimmed, 1-300 characters), with `If-Match` (428 without; 412 "Changed by {name} since you
opened it." when stale). The result must keep the Story 8.4 rules (wording 1-500 characters; a
Contingency has 0.5-1,000 hours, rounded to 0.1, and maybe a line of its version; a Condition
has no hours and no line), else 422 with the rule's sentence. Only an Assumption of the
Opportunity's `draft` version: another version's is 409 `estimate_version_not_draft`.

It takes the Opportunity's draft lock and then its Assumption lock (the order
`accept_assumption` takes them). Values equal to the stored ones are a no-op (200, nothing
written, no trace, the acceptance kept). A change bumps `row_version`, clears who accepted it
and when (the row is a blocker again), records who changed it, and, when the kind changed and
its Gap is converted to an Assumption, updates the Gap's `converted_to` through gaps'
public API, all in the same Unit of Work. It appends `estimates.assumption.edited` with the
before and after kind, hours, line and wording length, and the reason's length; never the
wording or the reason. Totals are never stored: the read model recalculates them.
"""

from decimal import Decimal
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import AssumptionRecord, VersionRecord
from app.modules.estimates.application.models import AssumptionChanges
from app.modules.estimates.domain.assumptions import (
    ASSUMPTION_SUBJECT_TYPE,
    CONDITION_LINE_RULE,
    LINE_RULE,
    AssumptionKind,
    check_assumption,
)
from app.modules.estimates.domain.estimates import REASON_RULE, VersionStatus, edit_reason
from app.modules.gaps.application import public as gaps
from app.modules.gaps.application.public import GapStatus
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    EstimateVersionNotDraftError,
    ForbiddenError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.locks import opportunity_lock
from app.platform.logging import get_logger
from app.platform.trace.catalogue import EstimatesAssumptionEdited
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Assumption with this id."
NOT_DRAFT_DETAIL = "This Estimate Version is not the draft any more. Reload to see the latest."
SOMEONE_ELSE = "someone else"
_log = get_logger(__name__)


async def changed_by_message(uow: UnitOfWork, changed_by: UUID | None) -> str:
    """The 412 detail: "Changed by {name} since you opened it." ("someone else" when the
    changer is unknown)."""
    name = SOMEONE_ELSE
    if changed_by is not None:
        name = (await identity.user_names(uow, {changed_by})).get(changed_by, name)
    return f"Changed by {name} since you opened it."


async def _authorized(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> UUID:
    """Authorize `estimates.assumption.edit` on the Opportunity; the acting user's id."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSUMPTION_EDIT, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants this action to users only
        raise ForbiddenError("Only people can edit Assumptions.")
    return user_id


async def _load(
    uow: UnitOfWork, opportunity_id: UUID, assumption_id: UUID
) -> tuple[AssumptionRecord, VersionRecord]:
    record = await repo.get_assumption(uow, assumption_id)
    version = None if record is None else await repo.get_version(uow, record.version_id)
    if record is None or version is None or version.opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return record, version


def _hours(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


async def edit_assumption(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    assumption_id: UUID,
    changes: AssumptionChanges,
    if_match: str | None,
) -> None:
    """Change the Assumption's kind, wording, hours and/or line, with a reason. `if_match` is
    the raw `If-Match` header (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    reason = edit_reason(changes.reason)
    if reason is None:
        raise UnprocessableError(REASON_RULE)
    # The draft lock first, then the Assumption lock: the order `accept_assumption` takes.
    await opportunity_lock(uow, opportunity_id)
    record, version = await _load(uow, opportunity_id, assumption_id)
    if version.status != VersionStatus.DRAFT:
        raise EstimateVersionNotDraftError(NOT_DRAFT_DETAIL)
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or record.row_version != expected:
        raise RowVersionMismatchError(await changed_by_message(uow, record.changed_by))

    given = changes.model_fields_set
    kind = changes.kind.value if "kind" in given and changes.kind is not None else record.kind
    wording = (
        changes.wording if "wording" in given and changes.wording is not None else record.wording
    )
    hours = changes.amount_hours if "amount_hours" in given else record.amount_hours
    line_id = changes.line_id if "line_id" in given else record.line_id
    checked = check_assumption(kind, wording, hours)
    if isinstance(checked, str):
        raise UnprocessableError(checked)
    if line_id is not None:
        if checked.kind is AssumptionKind.CONDITION:
            raise UnprocessableError(CONDITION_LINE_RULE)
        if line_id not in {line.id for line in await repo.lines_of(uow, version.id)}:
            raise UnprocessableError(LINE_RULE)

    if (
        checked.kind.value == record.kind
        and checked.wording == record.wording
        and checked.hours == record.amount_hours
        and line_id == record.line_id
    ):
        return  # nothing to change: the acceptance stays

    updated = await repo.edit_assumption(
        uow,
        assumption_id,
        expected_row_version=expected,
        kind=checked.kind.value,
        wording=checked.wording,
        amount_hours=checked.hours,
        line_id=line_id,
        user_id=user_id,
    )
    if updated is None:  # pragma: no cover - the locks serialise Assumption writes
        raise RowVersionMismatchError(await changed_by_message(uow, record.changed_by))
    gap_id = UUID(str(record.origin_ref["id"]))
    if checked.kind.value != record.kind:
        origin = (await gaps.gap_summaries(uow, opportunity_id, [gap_id])).get(gap_id)
        if (
            origin is not None
            and origin.status == GapStatus.CONVERTED
            and origin.converted_to in {k.value for k in AssumptionKind}
        ):
            await gaps.set_converted_to(uow, gap_id, checked.kind.value)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=EstimatesAssumptionEdited(
            version_id=str(version.id),
            gap_id=str(gap_id),
            before_kind=AssumptionKind(record.kind).value,
            after_kind=checked.kind.value,
            before_hours=_hours(record.amount_hours),
            after_hours=_hours(checked.hours),
            before_line_id=None if record.line_id is None else str(record.line_id),
            after_line_id=None if line_id is None else str(line_id),
            before_wording_length=len(record.wording),
            after_wording_length=len(checked.wording),
            was_accepted=record.accepted_at is not None,
            reason_length=len(reason),
        ),
        subject_type=ASSUMPTION_SUBJECT_TYPE,
        subject_id=assumption_id,
        opportunity_id=opportunity_id,
        subject_version=updated.row_version,
    )
    _log.info(
        "estimates.assumption_edited",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": str(version.id),
            "assumption_id": str(assumption_id),
            "actor_id": str(user_id),
            "row_version": updated.row_version,
            "kind_changed": checked.kind.value != record.kind,
            "was_accepted": record.accepted_at is not None,
        },
    )
