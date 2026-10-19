"""Human edits of Requirements (Story 2.6): edit, confirm, and confirm all; and pending
changes (Story 2.7): propose, accept and reject.

Every command follows the AD-3 path: `identity.authorize` (`intake.requirement.edit`: the
Opportunity's owner and collaborators except sales representatives; other readers 403,
everyone else the Opportunity's 404), validate, write, then trace, in the caller's Unit of
Work. Edits and confirmations lock the Requirement (`locked_by_human`), so a later
extraction never supersedes it.

- `edit_requirement`: new text and/or classification with `If-Match` (428 without, 412 when
  stale). A change writes the next version (and its history row), sets `origin` `human`,
  marks an open pending change `superseded` (Story 2.7), and appends
  `intake.requirement.edited` naming the changed fields. Nothing changed:
  nothing written, 200 (a stale `If-Match` is still 412). Evidence links stay.
- `confirm_requirement`: with `If-Match`; sets `confirmed_at` / `confirmed_by` and the lock,
  keeps the version, appends `intake.requirement.confirmed`. Already confirmed: 200 with
  nothing written, whatever version `If-Match` names (it is idempotent).
- `confirm_all`: confirms every active, unconfirmed Requirement, one event each; no
  `If-Match`, as it touches only rows nobody has confirmed.

- `propose_requirement_change` (`intake.propose_requirement_change`): an agent's change to a
  human-locked Requirement, in the caller's Unit of Work, without authorization (extraction
  calls it; Epic 4 Gap answers later). It supersedes the Requirement's open change and
  bumps its `row_version`; the same change already open, or one with the same passages
  rejected before, writes nothing.
- `accept_requirement_change` / `reject_requirement_change`: with `If-Match` on the
  Requirement (428/412), 409 `no_pending_change` without an open change. Accept makes the
  proposed text and classification the next version (origin `human`, locked) and cites the
  new passages; reject records the reason (1 to 500 characters) and keeps the version.

Trace and logs carry ids, versions and field names only, never the text or a reason.
"""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.adapters import requirements_repository as repo
from app.modules.intake.adapters.requirements_repository import RequirementRecord
from app.modules.intake.application.models import (
    ConfirmAllResult,
    Requirement,
    RequirementChangeRejection,
    RequirementChanges,
)
from app.modules.intake.application.requirements import requirement_views
from app.modules.intake.domain.requirements import (
    REQUIREMENT_SUBJECT_TYPE,
    ChangeStatus,
    reject_reason,
    requirement_text,
)
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.actor import Actor
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ForbiddenError,
    NoPendingChangeError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    IntakeRequirementChangeAccepted,
    IntakeRequirementChangeProposed,
    IntakeRequirementChangeRejected,
    IntakeRequirementConfirmed,
    IntakeRequirementEdited,
)
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Requirement with this id."
NO_PENDING_CHANGE_DETAIL = "This Requirement has no pending change."
_log = get_logger(__name__)


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Requirement was changed by someone else since you opened it. Reload and try again."
    )


async def _authorized(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> UUID:
    """Authorize `intake.requirement.edit` on the Opportunity; the acting user's id."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.REQUIREMENT_EDIT, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants this action to users only
        raise ForbiddenError("Only people can edit Requirements.")
    return user_id


async def _load(uow: UnitOfWork, opportunity_id: UUID, requirement_id: UUID) -> RequirementRecord:
    record = await repo.active_requirement(uow, opportunity_id, requirement_id)
    if record is None:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return record


def _expected(if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        # The stored version can't be this large, or bumping it would overflow int4.
        raise _stale()
    return expected


async def _view(uow: UnitOfWork, opportunity_id: UUID, record: RequirementRecord) -> Requirement:
    (view,) = await requirement_views(uow, opportunity_id, [record])
    return view


async def edit_requirement(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    requirement_id: UUID,
    changes: RequirementChanges,
    if_match: str | None,
) -> Requirement:
    """Change the Requirement's text and/or classification. `if_match` is the raw
    `If-Match` header (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record = await _load(uow, opportunity_id, requirement_id)

    text = record.text
    if changes.text is not None:
        try:
            text = requirement_text(changes.text)
        except ValueError as exc:
            raise UnprocessableError(str(exc)) from None
    classification = (
        record.classification if changes.classification is None else changes.classification.value
    )
    changed: list[Literal["text", "classification"]] = []
    if text != record.text:
        changed.append("text")
    if classification != record.classification:
        changed.append("classification")

    expected = _expected(if_match)
    if not changed:
        # Nothing to change, but a stale view must still be told to reload.
        if record.row_version != expected:
            raise _stale()
        return await _view(uow, opportunity_id, record)

    updated = await repo.edit_requirement(
        uow,
        requirement_id,
        expected_row_version=expected,
        text_=text,
        classification=classification,
    )
    if updated is None:
        raise _stale()
    await repo.insert_version(
        uow,
        requirement_id=requirement_id,
        version=updated.version,
        text_=text,
        classification=classification,
        created_by=actor.actor.id,
    )
    # Story 2.7 review decision: the person's newer wording wins over an open change.
    pending = (await repo.open_changes(uow, [requirement_id], for_update=True)).get(requirement_id)
    if pending is not None:
        await repo.close_change(uow, pending.id, status=ChangeStatus.SUPERSEDED.value)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=IntakeRequirementEdited(fields=changed, version=updated.version),
        subject_type=REQUIREMENT_SUBJECT_TYPE,
        subject_id=requirement_id,
        opportunity_id=opportunity_id,
        subject_version=updated.version,
    )
    _log.info(
        "intake.requirement_edited",
        extra={
            "opportunity_id": str(opportunity_id),
            "requirement_id": str(requirement_id),
            "actor_id": str(user_id),
            "fields": list(changed),
            "version": updated.version,
        },
    )
    return await _view(uow, opportunity_id, updated)


async def confirm_requirement(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    requirement_id: UUID,
    if_match: str | None,
) -> Requirement:
    """Confirm the Requirement. `if_match` is the raw `If-Match` header (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record = await _load(uow, opportunity_id, requirement_id)
    expected = _expected(if_match)
    if record.confirmed_at is not None:
        return await _view(uow, opportunity_id, record)
    confirmed = await repo.confirm_requirement(
        uow, requirement_id, expected_row_version=expected, user_id=user_id
    )
    if confirmed is None:
        raise _stale()
    await _trace_confirmed(uow, actor, opportunity_id, confirmed)
    _log.info(
        "intake.requirement_confirmed",
        extra={
            "opportunity_id": str(opportunity_id),
            "requirement_id": str(requirement_id),
            "actor_id": str(user_id),
            "version": confirmed.version,
        },
    )
    return await _view(uow, opportunity_id, confirmed)


async def confirm_all(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> ConfirmAllResult:
    """Confirm every active, unconfirmed Requirement of the Opportunity."""
    user_id = await _authorized(uow, actor, opportunity_id)
    confirmed = await repo.confirm_all(uow, opportunity_id, user_id=user_id)
    for record in confirmed:
        await _trace_confirmed(uow, actor, opportunity_id, record)
    _log.info(
        "intake.requirements_confirmed",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": str(user_id),
            "count": len(confirmed),
        },
    )
    return ConfirmAllResult(count=len(confirmed))


async def _trace_confirmed(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, record: RequirementRecord
) -> None:
    await trace.append(
        uow,
        actor=actor.actor,
        payload=IntakeRequirementConfirmed(version=record.version),
        subject_type=REQUIREMENT_SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=opportunity_id,
        subject_version=record.version,
    )


# --- pending changes (Story 2.7) ------------------------------------------------------------


async def propose_requirement_change(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    requirement_id: UUID,
    text: str,
    classification: str,
    passage_ids: Sequence[UUID],
    actor: Actor,
    extraction_id: UUID | None = None,
) -> UUID | None:
    """`intake.propose_requirement_change`: propose a change to a human-locked Requirement, in
    the caller's Unit of Work (no authorization: the caller is an agent's accepting command).
    The new open change supersedes the Requirement's earlier open one, and bumps its
    `row_version`. Returns its id, or None when nothing was written: the same change is
    already open, or one with the same passages was rejected before."""
    record = await _load(uow, opportunity_id, requirement_id)
    passages = sorted(set(passage_ids))
    current = (await repo.open_changes(uow, [requirement_id], for_update=True)).get(requirement_id)
    if current is not None and (
        current.text == text
        and current.classification == classification
        and sorted(current.passage_ids) == passages
    ):
        return None
    if tuple(passages) in await repo.rejected_passage_sets(uow, requirement_id):
        return None
    if current is not None:
        await repo.close_change(uow, current.id, status=ChangeStatus.SUPERSEDED.value)
    change_id = new_id()
    await repo.insert_change(
        uow,
        change_id=change_id,
        requirement_id=requirement_id,
        base_version=record.version,
        text_=text,
        classification=classification,
        passage_ids=passages,
        extraction_id=extraction_id,
    )
    await repo.bump_row_version(uow, requirement_id)
    await trace.append(
        uow,
        actor=actor,
        payload=IntakeRequirementChangeProposed(
            change_id=str(change_id),
            base_version=record.version,
            superseded_change_id=None if current is None else str(current.id),
        ),
        subject_type=REQUIREMENT_SUBJECT_TYPE,
        subject_id=requirement_id,
        opportunity_id=opportunity_id,
        subject_version=record.version,
    )
    _log.info(
        "intake.requirement_change_proposed",
        extra={
            "opportunity_id": str(opportunity_id),
            "requirement_id": str(requirement_id),
            "change_id": str(change_id),
            "base_version": record.version,
            "passage_count": len(passages),
        },
    )
    return change_id


async def _open_change(
    uow: UnitOfWork, record: RequirementRecord, expected: int
) -> repo.ChangeRecord:
    """The Requirement's open change, once `If-Match` is checked: 412 when stale, 409
    `no_pending_change` when it has none."""
    if record.row_version != expected:
        raise _stale()
    change = (await repo.open_changes(uow, [record.id], for_update=True)).get(record.id)
    if change is None:
        raise NoPendingChangeError(NO_PENDING_CHANGE_DETAIL)
    return change


async def accept_requirement_change(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    requirement_id: UUID,
    if_match: str | None,
) -> Requirement:
    """Accept the Requirement's pending change: its text and classification become the next
    version (origin `human`, still locked) and its passages are cited. `if_match` is the raw
    `If-Match` header of the Requirement (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record = await _load(uow, opportunity_id, requirement_id)
    expected = _expected(if_match)
    change = await _open_change(uow, record, expected)
    updated = await repo.edit_requirement(
        uow,
        requirement_id,
        expected_row_version=expected,
        text_=change.text,
        classification=change.classification,
    )
    if updated is None:
        raise _stale()
    await repo.insert_version(
        uow,
        requirement_id=requirement_id,
        version=updated.version,
        text_=change.text,
        classification=change.classification,
        created_by=actor.actor.id,
    )
    await repo.link_evidence(uow, requirement_id, list(change.passage_ids))
    if not await repo.close_change(
        uow, change.id, status=ChangeStatus.ACCEPTED.value, decided_by=user_id
    ):  # pragma: no cover - the row is locked above
        raise _stale()
    await trace.append(
        uow,
        actor=actor.actor,
        payload=IntakeRequirementChangeAccepted(change_id=str(change.id), version=updated.version),
        subject_type=REQUIREMENT_SUBJECT_TYPE,
        subject_id=requirement_id,
        opportunity_id=opportunity_id,
        subject_version=updated.version,
    )
    _log.info(
        "intake.requirement_change_accepted",
        extra={
            "opportunity_id": str(opportunity_id),
            "requirement_id": str(requirement_id),
            "change_id": str(change.id),
            "actor_id": str(user_id),
            "version": updated.version,
        },
    )
    return await _view(uow, opportunity_id, updated)


async def reject_requirement_change(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    requirement_id: UUID,
    rejection: RequirementChangeRejection,
    if_match: str | None,
) -> Requirement:
    """Reject the Requirement's pending change with a reason; the Requirement keeps its text,
    classification and version (its `row_version` moves on). `if_match` is the raw
    `If-Match` header of the Requirement (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record = await _load(uow, opportunity_id, requirement_id)
    try:
        reason = reject_reason(rejection.reason)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    expected = _expected(if_match)
    change = await _open_change(uow, record, expected)
    updated = await repo.bump_row_version(uow, requirement_id, expected_row_version=expected)
    if updated is None:
        raise _stale()
    if not await repo.close_change(
        uow, change.id, status=ChangeStatus.REJECTED.value, decided_by=user_id, reason=reason
    ):  # pragma: no cover - the row is locked above
        raise _stale()
    await trace.append(
        uow,
        actor=actor.actor,
        payload=IntakeRequirementChangeRejected(change_id=str(change.id), version=updated.version),
        subject_type=REQUIREMENT_SUBJECT_TYPE,
        subject_id=requirement_id,
        opportunity_id=opportunity_id,
        subject_version=updated.version,
    )
    _log.info(
        "intake.requirement_change_rejected",
        extra={
            "opportunity_id": str(opportunity_id),
            "requirement_id": str(requirement_id),
            "change_id": str(change.id),
            "actor_id": str(user_id),
            "version": updated.version,
        },
    )
    return await _view(uow, opportunity_id, updated)
