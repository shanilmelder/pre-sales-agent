"""Human edits of Clarification Questions (Story 4.5, demo slice): edit, approve, and approve
all.

Every command follows the AD-3 path: `identity.authorize` (`gaps.clarification_question.edit`:
the Opportunity's owner and collaborators except sales representatives; other readers 403,
everyone else the Opportunity's 404), validate, write, then trace, in the caller's Unit of
Work. Each takes the Opportunity's detection lock, so a detection accepted at the same time
sees the question either before or after the change, never half-way: a Gap whose question a
person edited or approved is kept by the next detection instead of superseded. Only questions
of `open` Gaps change (409 `gap_not_open` otherwise).

- `edit_question`: new text and/or topic with `If-Match` (428 without, 412 when stale). A
  change sets `edited_by_human`, returns an approved question to `drafted` (clearing its
  approval) and appends `gaps.clarification_question.edited` naming the changed fields.
  Nothing changed: nothing written, 200 (a stale `If-Match` is still 412).
- `approve_question`: with `If-Match`; sets `approved`, `approved_by` and `approved_at` and
  appends `gaps.clarification_question.approved`. Already approved: 200 with nothing written,
  whatever version `If-Match` names (it is idempotent).
- `approve_all`: approves exactly the drafted questions the client lists (id and row
  version), one event each, all or nothing; 412 when the list differs from the drafted
  questions of open Gaps (one changed, approved meanwhile, or not listed).

Trace and logs carry ids, versions and field names only, never the text.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.adapters.repository import GapRecord, QuestionRecord
from app.modules.gaps.application.gaps import question_names, question_view
from app.modules.gaps.application.models import (
    ApproveAllResult,
    ClarificationQuestion,
    QuestionChanges,
    QuestionVersion,
)
from app.modules.gaps.domain import gaps as rules
from app.modules.gaps.domain.gaps import (
    QUESTION_SUBJECT_TYPE,
    GapStatus,
    QuestionState,
    QuestionStatus,
    question_text,
    question_topic,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ForbiddenError,
    GapNotOpenError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    GapsClarificationQuestionApproved,
    GapsClarificationQuestionEdited,
)
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Clarification Question with this id."
NOT_OPEN_DETAIL = (
    "The Gap of this Clarification Question is no longer open: it was converted or replaced "
    "by a newer Gap detection."
)
_log = get_logger(__name__)


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Clarification Question was changed by someone else since you opened it. "
        "Reload and try again."
    )


async def _authorized(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> UUID:
    """Authorize `gaps.clarification_question.edit` on the Opportunity, then take its
    detection lock; the acting user's id."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.GAP_QUESTION_EDIT, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants this action to users only
        raise ForbiddenError("Only people can edit Clarification Questions.")
    await repo.lock_opportunity(uow, opportunity_id)
    return user_id


async def _load(
    uow: UnitOfWork, opportunity_id: UUID, question_id: UUID
) -> tuple[QuestionRecord, GapRecord]:
    found = await repo.get_question(uow, opportunity_id, question_id)
    if found is None:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return found


def _expected(if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        # The stored version can't be this large, or bumping it would overflow int4.
        raise _stale()
    return expected


def _open(gap: GapRecord) -> None:
    if gap.status != GapStatus.OPEN:
        raise GapNotOpenError(NOT_OPEN_DETAIL)


def _state(record: QuestionRecord) -> QuestionState:
    return QuestionState(
        text=record.text,
        topic=record.topic,
        status=QuestionStatus(record.status),
        approved_by=record.approved_by,
        approved_at=record.approved_at,
        edited_by_human=record.edited_by_human,
    )


async def _write(
    uow: UnitOfWork,
    record: QuestionRecord,
    state: QuestionState,
    *,
    expected: int,
    user_id: UUID,
    at: datetime,
) -> QuestionRecord:
    updated = await repo.update_question(
        uow,
        record.id,
        expected_row_version=expected,
        text_=state.text,
        topic=state.topic,
        status=state.status.value,
        approved_by=state.approved_by,
        approved_at=state.approved_at,
        edited_by_human=state.edited_by_human,
        changed_by=user_id,
        status_changed_at=at if state.status != record.status else None,
    )
    if updated is None:
        gap = await repo.get_gap(uow, record.gap_id)
        if gap is None or gap.status != GapStatus.OPEN:
            raise GapNotOpenError(NOT_OPEN_DETAIL)
        raise _stale()
    return updated


def _transition[T](change: Callable[[], T]) -> T:
    """Run a domain transition; a superseded question (inconsistent with an open Gap) is 409
    `gap_not_open`, never a 500."""
    try:
        return change()
    except rules.QuestionNotEditableError:
        raise GapNotOpenError(NOT_OPEN_DETAIL) from None


async def _view(uow: UnitOfWork, record: QuestionRecord) -> ClarificationQuestion:
    return question_view(record, await question_names(uow, [record]))


async def edit_question(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    question_id: UUID,
    changes: QuestionChanges,
    if_match: str | None,
) -> ClarificationQuestion:
    """Change the question's text and/or topic. `if_match` is the raw `If-Match` header
    (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record, gap = await _load(uow, opportunity_id, question_id)
    try:
        text = None if changes.text is None else question_text(changes.text)
        topic = None if changes.topic is None else question_topic(changes.topic)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    expected = _expected(if_match)
    _open(gap)
    state, changed = _transition(
        lambda: rules.edit_question(_state(record), text=text, topic=topic)
    )
    if record.row_version != expected:
        raise _stale()
    if not changed:
        return await _view(uow, record)
    updated = await _write(
        uow, record, state, expected=expected, user_id=user_id, at=datetime.now(UTC)
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsClarificationQuestionEdited(
            gap_id=str(gap.id),
            fields=list(changed),
            row_version=updated.row_version,
            approval_revoked=record.status == QuestionStatus.APPROVED,
        ),
        subject_type=QUESTION_SUBJECT_TYPE,
        subject_id=question_id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "gaps.clarification_question_edited",
        extra={
            "opportunity_id": str(opportunity_id),
            "question_id": str(question_id),
            "actor_id": str(user_id),
            "fields": list(changed),
            "row_version": updated.row_version,
        },
    )
    return await _view(uow, updated)


async def _approve(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    record: QuestionRecord,
    gap: GapRecord,
    *,
    expected: int,
    user_id: UUID,
) -> QuestionRecord:
    at = datetime.now(UTC)
    state = _transition(lambda: rules.approve_question(_state(record), user_id=user_id, at=at))
    updated = await _write(uow, record, state, expected=expected, user_id=user_id, at=at)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsClarificationQuestionApproved(
            gap_id=str(gap.id), approved_by=str(user_id), row_version=updated.row_version
        ),
        subject_type=QUESTION_SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=opportunity_id,
    )
    return updated


async def approve_question(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    question_id: UUID,
    if_match: str | None,
) -> ClarificationQuestion:
    """Approve the question as the caller. `if_match` is the raw `If-Match` header
    (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record, gap = await _load(uow, opportunity_id, question_id)
    expected = _expected(if_match)
    _open(gap)
    if record.status == QuestionStatus.APPROVED:
        return await _view(uow, record)
    if record.row_version != expected:
        raise _stale()
    approved = await _approve(
        uow, actor, opportunity_id, record, gap, expected=expected, user_id=user_id
    )
    _log.info(
        "gaps.clarification_question_approved",
        extra={
            "opportunity_id": str(opportunity_id),
            "question_id": str(question_id),
            "actor_id": str(user_id),
            "row_version": approved.row_version,
        },
    )
    return await _view(uow, approved)


async def approve_all(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    shown: Sequence[QuestionVersion],
) -> ApproveAllResult:
    """Approve exactly the drafted questions the client shows (`shown`: id and row version)
    as the caller; how many. All or nothing: if a listed question changed or is no longer
    drafted (of an open Gap), or a drafted question of an open Gap isn't listed, 412 and
    nothing is approved."""
    user_id = await _authorized(uow, actor, opportunity_id)
    drafted = await repo.drafted_questions_of_open_gaps(uow, opportunity_id)
    current = {q.id: q.row_version for q in drafted}
    listed = {q.id: q.row_version for q in shown}
    if listed != current:
        raise RowVersionMismatchError(
            "The Clarification Questions changed since you opened them. Reload and try again."
        )
    gaps = await repo.gaps_by_id(uow, opportunity_id, [q.gap_id for q in drafted])
    for record in drafted:
        await _approve(
            uow,
            actor,
            opportunity_id,
            record,
            gaps[record.gap_id],
            expected=record.row_version,
            user_id=user_id,
        )
    _log.info(
        "gaps.clarification_questions_approved",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": str(user_id),
            "count": len(drafted),
        },
    )
    return ApproveAllResult(count=len(drafted))
