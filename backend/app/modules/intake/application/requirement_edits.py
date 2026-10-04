"""Human edits of Requirements (Story 2.6): edit, confirm, and confirm all.

Every command follows the AD-3 path: `identity.authorize` (`intake.requirement.edit`: the
Opportunity's owner and collaborators except sales representatives; other readers 403,
everyone else the Opportunity's 404), validate, write, then trace, in the caller's Unit of
Work. Edits and confirmations lock the Requirement (`locked_by_human`), so a later
extraction never supersedes it.

- `edit_requirement`: new text and/or classification with `If-Match` (428 without, 412 when
  stale). A change writes the next version (and its history row), sets `origin` `human`,
  and appends `intake.requirement.edited` naming the changed fields. Nothing changed:
  nothing written, 200 (a stale `If-Match` is still 412). Evidence links stay.
- `confirm_requirement`: with `If-Match`; sets `confirmed_at` / `confirmed_by` and the lock,
  keeps the version, appends `intake.requirement.confirmed`. Already confirmed: 200 with
  nothing written, whatever version `If-Match` names (it is idempotent).
- `confirm_all`: confirms every active, unconfirmed Requirement, one event each; no
  `If-Match`, as it touches only rows nobody has confirmed.

Trace and logs carry ids, versions and field names only, never the text.
"""

from typing import Literal
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.adapters import requirements_repository as repo
from app.modules.intake.adapters.requirements_repository import RequirementRecord
from app.modules.intake.application.models import (
    ConfirmAllResult,
    Requirement,
    RequirementChanges,
)
from app.modules.intake.application.requirements import requirement_views
from app.modules.intake.domain.requirements import REQUIREMENT_SUBJECT_TYPE, requirement_text
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ForbiddenError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.logging import get_logger
from app.platform.trace.catalogue import IntakeRequirementConfirmed, IntakeRequirementEdited
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Requirement with this id."
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
