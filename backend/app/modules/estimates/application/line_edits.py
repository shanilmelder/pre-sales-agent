"""A person's edit of an Estimate line's hours and role mix (Story 8.2, demo slice).

**Editing** (`estimates.estimate_line.edit`: the owner and collaborators except sales
representatives; other readers 403, everyone else the Opportunity's 404): `edit_line` takes
new effort hours (0-2,000, rounded half up to 0.1) and/or a new role mix (whole percentages
for exactly the template's roles, summing to 100), and a reason (trimmed, 1-300 characters),
with `If-Match` (428 without; 412 "Changed by {name} since you opened it." when stale). Only a
line of the Opportunity's current `draft` version: a superseded one is 409
`estimate_version_not_draft`. It takes the Opportunity's draft lock, so no re-draft can
supersede the version mid-edit. Values equal to the stored ones are a no-op (200, nothing
written, no trace). A change records who, when and why, bumps the line's `row_version` and
appends `estimates.estimate_line.edited` with the before and after values and the reason.
Totals are never stored: the read model recalculates them.

**Carrying** (`carry_edits`): `estimates.accept_draft` calls it in its Unit of Work, under the
draft lock, once the new version and its lines are stored. Each edited line of the superseded
draft is matched to the new version's one line with the same section and title (trimmed,
case-insensitive: the rule Story 8.7 uses for Contingencies); the match takes the edited
hours, role mix, editor, time and reason, marked as carried from that version. Edited lines
with no match (none, more than one, or a line another edit already took) are counted on the
new version; they stay in the superseded version and the Trace.

Logs carry ids, versions and counts only, never the reason or line text.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import LineRecord, VersionRecord
from app.modules.estimates.application.models import EstimateLineChanges
from app.modules.estimates.domain.assumptions import carried_line
from app.modules.estimates.domain.estimates import (
    EFFORT_RULE,
    LINE_SUBJECT_TYPE,
    MIX_RULE,
    NOTHING_RULE,
    REASON_RULE,
    ROLES,
    VersionStatus,
    edit_reason,
    valid_edit_effort,
    valid_mix,
)
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
from app.platform.logging import get_logger
from app.platform.trace.catalogue import EstimatesEstimateLineEdited
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Estimate line with this id."
NOT_DRAFT_DETAIL = "This Estimate Version was replaced by a newer draft. Reload to see it."
SOMEONE_ELSE = "someone else"
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Edit:
    effort: Decimal | None
    mix: dict[str, int] | None
    reason: str


def _validated(changes: EstimateLineChanges) -> _Edit:
    """The edit checked against the rules (422 with the rule's sentence otherwise)."""
    if changes.effort_hours is None and changes.role_mix is None:
        raise UnprocessableError(NOTHING_RULE)
    effort: Decimal | None = None
    if changes.effort_hours is not None:
        effort = valid_edit_effort(changes.effort_hours)
        if effort is None:
            raise UnprocessableError(EFFORT_RULE)
    mix: dict[str, int] | None = None
    if changes.role_mix is not None:
        valid = valid_mix(changes.role_mix)
        if valid is None:
            raise UnprocessableError(MIX_RULE)
        mix = {role.value: share for role, share in valid.items()}
    reason = edit_reason(changes.reason)
    if reason is None:
        raise UnprocessableError(REASON_RULE)
    return _Edit(effort, mix, reason)


def _stored_mix(raw: dict[str, Any]) -> dict[str, int]:
    """The line's role mix as `{role: share}` for every template role."""
    return {role.value: int(raw.get(role.value, 0)) for role in ROLES}


async def _stale(uow: UnitOfWork, line: LineRecord) -> RowVersionMismatchError:
    name = SOMEONE_ELSE
    if line.edited_by is not None:
        name = (await identity.user_names(uow, {line.edited_by})).get(line.edited_by, name)
    return RowVersionMismatchError(f"Changed by {name} since you opened it.")


async def _authorized(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> UUID:
    """Authorize `estimates.estimate_line.edit` on the Opportunity; the acting user's id."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ESTIMATE_LINE_EDIT, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants this action to users only
        raise ForbiddenError("Only people can edit Estimate lines.")
    return user_id


async def _load(
    uow: UnitOfWork, opportunity_id: UUID, line_id: UUID
) -> tuple[LineRecord, VersionRecord]:
    line = await repo.get_line(uow, line_id)
    version = (
        None
        if line is None or line.version_id is None
        else await repo.get_version(uow, line.version_id)
    )
    if line is None or version is None or version.opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return line, version


async def edit_line(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    line_id: UUID,
    changes: EstimateLineChanges,
    if_match: str | None,
) -> None:
    """Change the line's effort and/or role mix, with a reason. `if_match` is the raw
    `If-Match` header (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    edit = _validated(changes)
    # The draft lock (as `accept_draft` takes it): no re-draft supersedes the version mid-edit.
    await repo.lock_opportunity(uow, opportunity_id)
    line, version = await _load(uow, opportunity_id, line_id)
    if version.status != VersionStatus.DRAFT:
        raise EstimateVersionNotDraftError(NOT_DRAFT_DETAIL)
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or line.row_version != expected:
        raise await _stale(uow, line)

    before_mix = _stored_mix(line.role_mix)
    after_effort = line.effort_hours if edit.effort is None else edit.effort
    after_mix = before_mix if edit.mix is None else edit.mix
    if after_effort == line.effort_hours and after_mix == before_mix:
        return  # nothing to change

    updated = await repo.edit_line(
        uow,
        line_id,
        expected_row_version=expected,
        effort_hours=after_effort,
        role_mix=after_mix,
        user_id=user_id,
        reason=edit.reason,
    )
    if updated is None:  # pragma: no cover - the draft lock serialises edits
        raise await _stale(uow, line)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=EstimatesEstimateLineEdited(
            version=version.version,
            before_hours=float(line.effort_hours),
            after_hours=float(after_effort),
            before_role_mix=before_mix,
            after_role_mix=after_mix,
            reason=edit.reason,
        ),
        subject_type=LINE_SUBJECT_TYPE,
        subject_id=line_id,
        opportunity_id=opportunity_id,
        subject_version=updated.row_version,
    )
    _log.info(
        "estimates.line_edited",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": str(version.id),
            "line_id": str(line_id),
            "actor_id": str(user_id),
            "row_version": updated.row_version,
            "effort_changed": after_effort != line.effort_hours,
            "mix_changed": after_mix != before_mix,
        },
    )


# --- carrying to a re-draft -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CarriedEdits:
    carried: int
    uncarried: int


async def carry_edits(
    uow: UnitOfWork, *, source: VersionRecord, target_version_id: UUID
) -> CarriedEdits:
    """Carry the edited lines of `source` (the draft a re-draft supersedes) onto their
    matching lines in `target_version_id` (the new draft, its lines stored), and record how
    many found no match on it. The caller holds the Opportunity's draft lock."""
    edited = [line for line in await repo.lines_of(uow, source.id) if line.edited_at is not None]
    if not edited:
        return CarriedEdits(0, 0)
    candidates = [
        (line.id, line.section, line.title) for line in await repo.lines_of(uow, target_version_id)
    ]
    taken: set[UUID] = set()
    carried = 0
    for line in edited:
        target = carried_line(line.section, line.title, candidates)
        if target is None or target in taken:
            continue
        taken.add(target)
        await repo.carry_line_edit(uow, target, source=line, from_version=source.version)
        carried += 1
    uncarried = len(edited) - carried
    if uncarried:
        await repo.set_uncarried_edit_count(uow, target_version_id, uncarried)
    return CarriedEdits(carried, uncarried)
