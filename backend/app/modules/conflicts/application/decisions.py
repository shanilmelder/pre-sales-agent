"""A person resolves or escalates a Conflict (Story 6.3, demo slice; FR-31).

**Resolving** (`resolve_conflict`; `conflicts.conflict.resolve`: the owner and
collaborators except sales representatives, or the reviewer an escalated Conflict was
escalated to; everyone else 403, and the Opportunity's 404 for those who can't read it):
an `open` or `escalated` Conflict, by choosing one of its positions or entering a different
one (1-200 characters), with a reason (1-1,000 characters). It records who, when, why and
the choice, keeps every position, and traces `conflicts.conflict.resolved` (`decided`) with
the reason, the choice and every original position's summary.

An `effort` decision also sets the Estimate: choosing an agent's position gives the line the
agents' total for the Requirement (the figure the Conflict compared), an entered position
(hours from 0 to 2,000 to 0.1 h, else 422) those hours, and choosing the Estimate's position
leaves it alone. The change is an Estimate line edit (Story 8.2) by the person with the
resolution's reason, made through `EstimateLink` in the same Unit of Work, and only when
exactly one line of the current draft covers the Requirement and covers nothing else;
otherwise the decision is recorded with `not_applied`. Scope and recommendation decisions
never change the Estimate.

**Escalating** (`escalate_conflict`; `conflicts.conflict.escalate`, as resolving but without
the reviewer rule): an `open` Conflict, to the Opportunity's owner or a collaborator other
than the caller (else 422), with a reason. Traced as `conflicts.conflict.escalated`.

Both take the Conflict's `row_version` in `If-Match` (428 without; 412 "Changed by {name}
since you opened it." when stale); an already resolved Conflict is 409
`conflict_already_resolved`. The reason, choice and reviewer rules (422) are checked after
If-Match and status; a body that doesn't fit the schema still answers 422 first. A
resolver who may not edit Estimate lines (a sales representative reviewer, FR-64) resolves
an `effort` Conflict without changing the line (`not_applied`: `not_permitted`). Logs carry
ids and kinds only, never the reason, a position or Requirement text.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.modules.conflicts.adapters import repository as repo
from app.modules.conflicts.adapters.repository import ConflictRecord, PositionRecord
from app.modules.conflicts.application.conflicts import (
    conflicts_view,
    may_resolve,
    reviewer_ids,
)
from app.modules.conflicts.application.models import (
    ConflictEscalation,
    ConflictResolution,
    ConflictView,
)
from app.modules.conflicts.domain.conflicts import (
    CONFLICT_SUBJECT_TYPE,
    ConflictStatus,
    ConflictType,
    PositionSource,
    tenth,
)
from app.modules.conflicts.domain.decisions import (
    CHOICE_RULE,
    ENTERED_RULE,
    HOURS_RULE,
    REASON_RULE,
    REVIEWER_RULE,
    NotApplied,
    decision_reason,
    entered_hours,
    entered_text,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.actor import Actor
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ConflictAlreadyResolvedError,
    ConflictNotOpenError,
    ForbiddenError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    ConflictPositionSummary,
    ConflictsConflictEscalated,
    ConflictsConflictResolved,
)
from app.platform.uow import UnitOfWork

NOT_FOUND_DETAIL = "No Conflict with this id."
ALREADY_RESOLVED_DETAIL = "This Conflict is already resolved."
NOT_OPEN_DETAIL = "This Conflict is already escalated."
SOMEONE_ELSE = "someone else"
MAX_ROW_VERSION = 2**31 - 1
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AppliedDecision:
    """What an `effort` decision did to the Estimate: the line it set (`line_id`), or why it
    set none (`not_applied`)."""

    line_id: UUID | None
    not_applied: NotApplied | None = None


ApplyDecision = Callable[[UnitOfWork, Actor, UUID, UUID, Decimal, str], Awaitable[AppliedDecision]]
"""`(uow, actor, opportunity_id, requirement_id, hours, reason)`: set the hours on the
current draft's one line covering only that Requirement, as an edit by the actor."""
LockEstimate = Callable[[UnitOfWork, UUID], Awaitable[None]]
"""`(uow, opportunity_id)`: take the Estimate's draft lock until commit."""


@dataclass(frozen=True, slots=True)
class EstimateLink:
    """How a decision reaches the Estimate without `conflicts` importing `estimates`: the
    route passes `estimates`' own functions. `lock` is taken before the Conflicts lock, in
    the order an assessment run's end takes them, so the two never deadlock."""

    lock: LockEstimate
    apply: ApplyDecision


async def _load(uow: UnitOfWork, opportunity_id: UUID, conflict_id: UUID) -> ConflictRecord:
    conflict = await repo.get(uow, conflict_id)
    if conflict is None or conflict.opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return conflict


async def _stale(uow: UnitOfWork, conflict: ConflictRecord) -> RowVersionMismatchError:
    name = SOMEONE_ELSE
    changer = conflict.resolved_by or conflict.escalated_by
    if changer is not None:
        name = (await identity.user_names(uow, {changer})).get(changer, name)
    return RowVersionMismatchError(f"Changed by {name} since you opened it.")


async def _checked_version(uow: UnitOfWork, conflict: ConflictRecord, if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or conflict.row_version != expected:
        raise await _stale(uow, conflict)
    if conflict.status == ConflictStatus.RESOLVED:
        raise ConflictAlreadyResolvedError(ALREADY_RESOLVED_DETAIL)
    return expected


def _reason(raw: str) -> str:
    reason = decision_reason(raw)
    if reason is None:
        raise UnprocessableError(REASON_RULE)
    return reason


async def _view(
    uow: UnitOfWork, actor: Principal, resource: Resource, opportunity_id: UUID, conflict_id: UUID
) -> ConflictView:
    view = await conflicts_view(uow, actor, resource, opportunity_id)
    return next(c for c in view.conflicts if c.id == str(conflict_id))


@dataclass(frozen=True, slots=True)
class _Choice:
    chosen: int | None
    entered: str | None
    hours: Decimal | None
    """The hours an `effort` decision sets on the Estimate line; None leaves it alone."""


def _choice(
    conflict: ConflictRecord, positions: list[PositionRecord], resolution: ConflictResolution
) -> _Choice:
    effort = conflict.type == ConflictType.EFFORT
    if isinstance(resolution.choice, int):
        chosen = next((p for p in positions if p.position == resolution.choice), None)
        if chosen is None:
            raise UnprocessableError(CHOICE_RULE)
        hours: Decimal | None = None
        if effort and chosen.source == PositionSource.ASSESSMENT:
            hours = tenth(
                sum(
                    (
                        p.value
                        for p in positions
                        if p.source == PositionSource.ASSESSMENT and p.value is not None
                    ),
                    Decimal(0),
                )
            )
        return _Choice(chosen=chosen.position, entered=None, hours=hours)
    entered = entered_text(resolution.choice.entered)
    if entered is None:
        raise UnprocessableError(ENTERED_RULE)
    hours = None
    if effort:
        hours = entered_hours(entered)
        if hours is None:
            raise UnprocessableError(HOURS_RULE)
    return _Choice(chosen=None, entered=entered, hours=hours)


async def resolve_conflict(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    conflict_id: UUID,
    resolution: ConflictResolution,
    if_match: str | None,
    estimate: EstimateLink,
) -> ConflictView:
    """Resolve the Conflict with the person's decision (see the module docstring); the
    Conflict as it is now."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    await estimate.lock(uow, opportunity_id)
    await repo.lock_opportunity(uow, opportunity_id)
    conflict = await _load(uow, opportunity_id, conflict_id)
    user_id = actor.user_id
    if not may_resolve(actor, resource, conflict):
        # 403 unless the caller holds the action (then a resolved Conflict is a 409 below).
        identity.authorize(actor, Action.CONFLICT_RESOLVE, resource)
    if user_id is None:  # pragma: no cover - the policy grants these actions to users only
        raise ForbiddenError("Only people can resolve Conflicts.")
    expected = await _checked_version(uow, conflict, if_match)
    reason = _reason(resolution.reason)
    positions = await repo.positions_of(uow, [conflict.id])
    choice = _choice(conflict, positions, resolution)

    applied = AppliedDecision(line_id=None)
    requirement_id = next((p.requirement_id for p in positions if p.requirement_id), None)
    if choice.hours is not None and requirement_id is not None:
        if not identity.can(actor, Action.ESTIMATE_LINE_EDIT, resource):
            # FR-64: e.g. a sales representative reviewer resolves but can't edit the Estimate.
            applied = AppliedDecision(line_id=None, not_applied=NotApplied.NOT_PERMITTED)
        else:
            applied = await estimate.apply(
                uow, actor.actor, opportunity_id, requirement_id, choice.hours, reason
            )
    applied_hours = choice.hours if applied.line_id is not None else None

    new_version = await repo.decide(
        uow,
        conflict.id,
        expected_row_version=expected,
        user_id=user_id,
        reason=reason,
        chosen_position=choice.chosen,
        entered_position=choice.entered,
        applied_hours=applied_hours,
    )
    if new_version is None:  # pragma: no cover - the Conflicts lock serialises decisions
        raise await _stale(uow, conflict)
    await repo.notify_conflicts_changed(uow, opportunity_id)  # Story 6.2: live tab
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ConflictsConflictResolved(
            reason_kind="decided",
            reason=reason,
            chosen_position=choice.chosen,
            entered_position=choice.entered,
            positions=[
                ConflictPositionSummary(
                    position=p.position,
                    source="estimate" if p.source == PositionSource.ESTIMATE else "assessment",
                    agent=p.agent,
                    summary=p.summary,
                )
                for p in positions
            ],
            line_id=None if applied.line_id is None else str(applied.line_id),
            applied_hours=None if applied_hours is None else float(applied_hours),
            not_applied=None if applied.not_applied is None else applied.not_applied.value,
        ),
        subject_type=CONFLICT_SUBJECT_TYPE,
        subject_id=conflict.id,
        opportunity_id=opportunity_id,
        subject_version=new_version,
    )
    _log.info(
        "conflicts.resolved",
        extra={
            "opportunity_id": str(opportunity_id),
            "conflict_id": str(conflict.id),
            "actor_id": str(user_id),
            "type": conflict.type,
            "row_version": new_version,
            "chosen": choice.chosen is not None,
            "applied": applied.line_id is not None,
            "not_applied": None if applied.not_applied is None else applied.not_applied.value,
        },
    )
    return await _view(uow, actor, resource, opportunity_id, conflict.id)


async def escalate_conflict(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    conflict_id: UUID,
    escalation: ConflictEscalation,
    if_match: str | None,
) -> ConflictView:
    """Escalate the open Conflict to a reviewer on the Opportunity, with a reason; the
    Conflict as it is now."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    await repo.lock_opportunity(uow, opportunity_id)
    conflict = await _load(uow, opportunity_id, conflict_id)
    identity.authorize(actor, Action.CONFLICT_ESCALATE, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants this action to users only
        raise ForbiddenError("Only people can escalate Conflicts.")
    expected = await _checked_version(uow, conflict, if_match)
    if conflict.status != ConflictStatus.OPEN:
        raise ConflictNotOpenError(NOT_OPEN_DETAIL)
    reason = _reason(escalation.reason)
    if escalation.reviewer_id not in reviewer_ids(resource, user_id):
        raise UnprocessableError(REVIEWER_RULE)

    new_version = await repo.escalate(
        uow,
        conflict.id,
        expected_row_version=expected,
        user_id=user_id,
        reviewer_id=escalation.reviewer_id,
        reason=reason,
    )
    if new_version is None:  # pragma: no cover - the Conflicts lock serialises decisions
        raise await _stale(uow, conflict)
    await repo.notify_conflicts_changed(uow, opportunity_id)  # Story 6.2: live tab
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ConflictsConflictEscalated(reviewer_id=str(escalation.reviewer_id), reason=reason),
        subject_type=CONFLICT_SUBJECT_TYPE,
        subject_id=conflict.id,
        opportunity_id=opportunity_id,
        subject_version=new_version,
    )
    _log.info(
        "conflicts.escalated",
        extra={
            "opportunity_id": str(opportunity_id),
            "conflict_id": str(conflict.id),
            "actor_id": str(user_id),
            "reviewer_id": str(escalation.reviewer_id),
            "row_version": new_version,
        },
    )
    return await _view(uow, actor, resource, opportunity_id, conflict.id)
