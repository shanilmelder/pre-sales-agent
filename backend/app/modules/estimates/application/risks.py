"""Risks (Story 8.5): converting an open Gap to a Risk, editing a Risk, and carrying Risks to a
re-draft.

**Converting** (`estimates.risk.create`: the owner and collaborators except sales
representatives; other readers 403, everyone else the Opportunity's 404): `create_risk` takes
the Gap, a description (trimmed, 1-500 characters), a likelihood and an impact. It needs the
Opportunity's current draft (409 `no_draft_estimate` otherwise), and the Gap must be one of
the Opportunity's (404) and `open` (409 `gap_not_open`). It takes the Opportunity's draft lock
and then its Assumption lock (the order accepting takes them) and, in one Unit of Work,
stores the Risk (numbered after the version's others), marks the Gap `converted` to `risk`
(`gaps.mark_converted`, tracing `gaps.gap.converted`) and deletes the draft's unaccepted
Assumption proposed for the same Gap; it traces `estimates.risk.created`. If any step fails,
nothing commits.

**Editing** (`estimates.risk.edit`, the same people): `edit_risk` takes a new description,
likelihood and/or impact, and a reason (1-300 characters), with `If-Match` (428 without; 412
"Changed by {name} since you opened it." when stale). Only a Risk of the `draft` version
(409 `estimate_version_not_draft` otherwise); the same locks. Values equal to the stored ones
are a no-op. A change bumps `row_version` and traces `estimates.risk.edited`.

Risks are never accepted and never block submission.

**Carrying** (`carry_risks`): `estimates.accept_draft` calls it in its Unit of Work, under the
draft lock: every Risk of the superseded draft is copied into the new version (same
description, levels, origin and creator; new id, `row_version` 1, `carried_from` set).

Logs and trace carry ids, levels and lengths only, never the description or the reason.
"""

from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import CarriedRisk, RiskRecord, VersionRecord
from app.modules.estimates.application.assumption_edits import changed_by_message
from app.modules.estimates.application.models import RiskChanges, RiskCreate
from app.modules.estimates.domain.assumptions import ORIGIN_GAP
from app.modules.estimates.domain.estimates import REASON_RULE, VersionStatus, edit_reason
from app.modules.estimates.domain.risks import (
    DESCRIPTION_RULE,
    RISK_SUBJECT_TYPE,
    RiskLevel,
    risk_description,
)
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
    GapNotOpenError,
    NoDraftEstimateError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import EstimatesRiskCreated, EstimatesRiskEdited
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NO_DRAFT_DETAIL = "There is no draft Estimate to add the Risk to."
GAP_NOT_FOUND_DETAIL = "No Gap with this id in this Opportunity."
GAP_NOT_OPEN_DETAIL = (
    "The Gap is no longer open: it was dismissed, answered, converted or replaced by a newer "
    "Gap detection."
)
NOT_FOUND_DETAIL = "No Risk with this id."
NOT_DRAFT_DETAIL = "This Estimate Version is not the draft any more. Reload to see the latest."
_log = get_logger(__name__)


async def _authorized(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, action: Action
) -> UUID:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, action, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants these actions to users only
        raise ForbiddenError("Only people can change Risks.")
    return user_id


async def create_risk(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, body: RiskCreate
) -> RiskRecord:
    """Convert the open Gap to a Risk of the current draft; the Risk as stored."""
    user_id = await _authorized(uow, actor, opportunity_id, Action.RISK_CREATE)
    description = risk_description(body.description)
    if description is None:
        raise UnprocessableError(DESCRIPTION_RULE)
    # The draft lock first, then the Assumption lock: the order accepting takes them.
    await repo.lock_opportunity(uow, opportunity_id)
    await repo.lock_assumptions(uow, opportunity_id)
    version = await repo.draft_version(uow, opportunity_id)  # never a submitted one (Story 8.6)
    if version is None:
        raise NoDraftEstimateError(NO_DRAFT_DETAIL)
    gap = (await gaps.gap_summaries(uow, opportunity_id, [body.gap_id])).get(body.gap_id)
    if gap is None:
        raise NotFoundError(GAP_NOT_FOUND_DETAIL)
    if gap.status != GapStatus.OPEN:
        raise GapNotOpenError(GAP_NOT_OPEN_DETAIL)

    risk = await repo.insert_risk(
        uow,
        risk_id=new_id(),
        version_id=version.id,
        position=await repo.last_risk_position(uow, version.id) + 1,
        description=description,
        likelihood=body.likelihood.value,
        impact=body.impact.value,
        origin_ref={"kind": ORIGIN_GAP, "id": str(gap.id), "row_version": gap.row_version},
        user_id=user_id,
    )
    await gaps.mark_converted(uow, gap.id, actor=actor.actor, assumption_kind="risk")
    removed = await repo.delete_unaccepted_for_gap(uow, version.id, gap.id)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=EstimatesRiskCreated(
            version_id=str(version.id),
            gap_id=str(gap.id),
            likelihood=body.likelihood.value,
            impact=body.impact.value,
            description_length=len(description),
            removed_assumption_count=removed,
        ),
        subject_type=RISK_SUBJECT_TYPE,
        subject_id=risk.id,
        opportunity_id=opportunity_id,
        subject_version=risk.row_version,
    )
    _log.info(
        "estimates.risk_created",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": str(version.id),
            "risk_id": str(risk.id),
            "gap_id": str(gap.id),
            "actor_id": str(user_id),
            "removed_assumption_count": removed,
        },
    )
    return risk


async def _load(
    uow: UnitOfWork, opportunity_id: UUID, risk_id: UUID
) -> tuple[RiskRecord, VersionRecord]:
    record = await repo.get_risk(uow, risk_id)
    version = None if record is None else await repo.get_version(uow, record.version_id)
    if record is None or version is None or version.opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return record, version


async def edit_risk(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    risk_id: UUID,
    changes: RiskChanges,
    if_match: str | None,
) -> None:
    """Change the Risk's description, likelihood and/or impact, with a reason. `if_match` is
    the raw `If-Match` header (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id, Action.RISK_EDIT)
    reason = edit_reason(changes.reason)
    if reason is None:
        raise UnprocessableError(REASON_RULE)
    description: str | None = None
    if changes.description is not None:
        description = risk_description(changes.description)
        if description is None:
            raise UnprocessableError(DESCRIPTION_RULE)
    await repo.lock_opportunity(uow, opportunity_id)
    await repo.lock_assumptions(uow, opportunity_id)
    record, version = await _load(uow, opportunity_id, risk_id)
    if version.status != VersionStatus.DRAFT:
        raise EstimateVersionNotDraftError(NOT_DRAFT_DETAIL)
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or record.row_version != expected:
        raise RowVersionMismatchError(await changed_by_message(uow, record.changed_by))

    after_description = record.description if description is None else description
    likelihood = record.likelihood if changes.likelihood is None else changes.likelihood.value
    impact = record.impact if changes.impact is None else changes.impact.value
    if (after_description, likelihood, impact) == (
        record.description,
        record.likelihood,
        record.impact,
    ):
        return  # nothing to change

    updated = await repo.edit_risk(
        uow,
        risk_id,
        expected_row_version=expected,
        description=after_description,
        likelihood=likelihood,
        impact=impact,
        user_id=user_id,
    )
    if updated is None:  # pragma: no cover - the locks serialise Risk writes
        raise RowVersionMismatchError(await changed_by_message(uow, record.changed_by))
    await trace.append(
        uow,
        actor=actor.actor,
        payload=EstimatesRiskEdited(
            version_id=str(version.id),
            before_likelihood=RiskLevel(record.likelihood).value,
            after_likelihood=RiskLevel(likelihood).value,
            before_impact=RiskLevel(record.impact).value,
            after_impact=RiskLevel(impact).value,
            before_description_length=len(record.description),
            after_description_length=len(after_description),
            reason_length=len(reason),
        ),
        subject_type=RISK_SUBJECT_TYPE,
        subject_id=risk_id,
        opportunity_id=opportunity_id,
        subject_version=updated.row_version,
    )
    _log.info(
        "estimates.risk_edited",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": str(version.id),
            "risk_id": str(risk_id),
            "actor_id": str(user_id),
            "row_version": updated.row_version,
        },
    )


async def carry_risks(uow: UnitOfWork, *, source_version_id: UUID, target_version_id: UUID) -> int:
    """Copy every Risk of `source_version_id` (the draft a re-draft supersedes) into
    `target_version_id`. The caller holds the Opportunity's draft lock. Returns how many."""
    risks = await repo.risks_of(uow, source_version_id)
    carried = [
        CarriedRisk(risk_id=new_id(), position=position, source=source)
        for position, source in enumerate(risks, start=1)
    ]
    await repo.insert_carried_risks(uow, target_version_id, carried)
    return len(carried)
