"""Human changes of Gaps (Story 4.4, demo slice): change impact, dismiss and reopen.

Every command follows the AD-3 path: `identity.authorize` (`gaps.gap.edit`: the
Opportunity's owner and collaborators except sales representatives; other readers 403,
everyone else the Opportunity's 404), validate, write, then a history entry and a trace
event, in the caller's Unit of Work. Each takes the Opportunity's shared lock
(`platform.locks.opportunity_lock`, which detection takes too): dismiss and reopen change
submission blockers (AD-26), and an impact change must not race a detection, which keeps Gaps
a person touched.

Order of checks: authorize (403/404) → Gap in this Opportunity (404) → body (422) →
`If-Match` (428) → status (409 `gap_not_open` / `gap_not_reopenable`; `gap_mandatory` for a
mandatory Gap whose Checklist still applies, Story 4.2) → stale (412) → no-op or write.

- `change_impact`: an `open` Gap's impact, with a reason; sets `touched_by_human`. The same
  impact: 200 with nothing written (a stale `If-Match` is still 412). Trace
  `gaps.gap.impact_changed`.
- `dismiss_gap`: an `open` Gap `dismissed` with `not_relevant` (note optional) or `other`
  (note required). A mandatory Gap only once its Checklist no longer applies (409
  `gap_mandatory`, Story 4.2). Trace `gaps.gap.dismissed`.
- `reopen_gap`: a `dismissed` or `answered` (Story 4.7) Gap `open` again, its dismissal or
  answer cleared, with a reason; sets `touched_by_human`. The question of an answered Gap is
  `sent` again, its answer cleared. Trace `gaps.gap.reopened`.

Every write notifies the Opportunity's event stream (`gaps.changed`, Story 4.7).

Reasons and notes are kept in the Gap's history only; trace and logs carry ids, impacts,
the reason kind and versions, never their text.
"""

from datetime import UTC, datetime
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.adapters.repository import GapRecord
from app.modules.gaps.application.gaps import gap_views
from app.modules.gaps.application.models import (
    Gap,
    GapDismissalRequest,
    GapReopening,
    ImpactChange,
)
from app.modules.gaps.domain import gaps as rules
from app.modules.gaps.domain.gaps import (
    GAP_SUBJECT_TYPE,
    DismissReasonKind,
    GapHistoryKind,
    GapOrigin,
    GapState,
    GapStatus,
    Impact,
    QuestionState,
    QuestionStatus,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ForbiddenError,
    GapMandatoryError,
    GapNotOpenError,
    GapNotReopenableError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.locks import opportunity_lock
from app.platform.logging import get_logger
from app.platform.trace.catalogue import GapsGapDismissed, GapsGapImpactChanged, GapsGapReopened
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Gap with this id."
NOT_OPEN_DETAIL = (
    "The Gap is no longer open: it was dismissed, converted or replaced by a newer Gap detection."
)
NOT_REOPENABLE_DETAIL = "The Gap is neither dismissed nor answered, so it can't be reopened."
_log = get_logger(__name__)


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Gap was changed by someone else since you opened it. Reload and try again."
    )


async def _authorized(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> UUID:
    """Authorize `gaps.gap.edit` on the Opportunity, then take its detection lock; the acting
    user's id."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.GAP_EDIT, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants this action to users only
        raise ForbiddenError("Only people can change Gaps.")
    await opportunity_lock(uow, opportunity_id)
    return user_id


async def _load(uow: UnitOfWork, opportunity_id: UUID, gap_id: UUID) -> GapRecord:
    found = (await repo.gaps_by_id(uow, opportunity_id, [gap_id])).get(gap_id)
    if found is None:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return found


def _expected(if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        # The stored version can't be this large, or bumping it would overflow int4.
        raise _stale()
    return expected


def _reason(raw: str) -> str:
    try:
        return rules.reason_text(raw)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None


def _state(record: GapRecord) -> GapState:
    return GapState(
        status=GapStatus(record.status),
        impact=Impact(record.impact),
        dismiss_reason_kind=None
        if record.dismiss_reason_kind is None
        else DismissReasonKind(record.dismiss_reason_kind),
        dismiss_note=record.dismiss_note,
        dismissed_by=record.dismissed_by,
        dismissed_at=record.dismissed_at,
        touched_by_human=record.touched_by_human,
        answered_on=record.answered_on,
        answered_by=record.answered_by,
        answer_passage_id=record.answer_passage_id,
    )


def _mandatory_applies(record: GapRecord) -> bool:
    """A mandatory Gap whose Checklist item still applies (Story 4.2): it can't be
    dismissed."""
    return record.origin == GapOrigin.MANDATORY_CHECKLIST and record.checklist_applies


async def _write(
    uow: UnitOfWork,
    record: GapRecord,
    state: GapState,
    *,
    expected: int,
    user_id: UUID,
    not_in_state: Exception,
) -> GapRecord:
    updated = await repo.update_gap(
        uow,
        record.id,
        expected_row_version=expected,
        from_status=record.status,
        status=state.status.value,
        impact=state.impact.value,
        dismiss_reason_kind=None
        if state.dismiss_reason_kind is None
        else state.dismiss_reason_kind.value,
        dismiss_note=state.dismiss_note,
        dismissed_by=state.dismissed_by,
        dismissed_at=state.dismissed_at,
        touched_by_human=state.touched_by_human,
        changed_by=user_id,
        answered_on=state.answered_on,
        answered_by=state.answered_by,
        answer_passage_id=state.answer_passage_id,
    )
    if updated is None:
        current = await repo.get_gap(uow, record.id)
        if current is None or current.status != record.status:
            raise not_in_state
        raise _stale()
    await repo.notify_gaps_changed(uow, record.opportunity_id)
    return updated


async def _history(
    uow: UnitOfWork,
    gap_id: UUID,
    kind: GapHistoryKind,
    *,
    user_id: UUID,
    at: datetime,
    old_impact: str | None = None,
    new_impact: str | None = None,
    reason_kind: str | None = None,
    reason: str | None = None,
) -> None:
    await repo.insert_history(
        uow,
        history_id=new_id(),
        gap_id=gap_id,
        kind=kind.value,
        actor_id=user_id,
        at=at,
        old_impact=old_impact,
        new_impact=new_impact,
        reason_kind=reason_kind,
        reason=reason,
    )


async def _view(uow: UnitOfWork, record: GapRecord) -> Gap:
    (view,) = await gap_views(uow, record.opportunity_id, [record])
    return view


def _log_change(event: str, record: GapRecord, user_id: UUID, row_version: int) -> None:
    _log.info(
        event,
        extra={
            "opportunity_id": str(record.opportunity_id),
            "gap_id": str(record.id),
            "actor_id": str(user_id),
            "row_version": row_version,
        },
    )


async def change_impact(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    gap_id: UUID,
    body: ImpactChange,
    if_match: str | None,
) -> Gap:
    """Change an open Gap's impact, with a reason. `if_match` is the raw `If-Match` header
    (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record = await _load(uow, opportunity_id, gap_id)
    reason = _reason(body.reason)
    expected = _expected(if_match)
    try:
        state = rules.change_impact(_state(record), body.impact)
    except rules.GapNotOpenTransitionError:
        raise GapNotOpenError(NOT_OPEN_DETAIL) from None
    if record.row_version != expected:
        raise _stale()
    if state.impact == record.impact:
        return await _view(uow, record)
    updated = await _write(
        uow,
        record,
        state,
        expected=expected,
        user_id=user_id,
        not_in_state=GapNotOpenError(NOT_OPEN_DETAIL),
    )
    await _history(
        uow,
        gap_id,
        GapHistoryKind.IMPACT_CHANGED,
        user_id=user_id,
        at=datetime.now(UTC),
        old_impact=record.impact,
        new_impact=state.impact.value,
        reason=reason,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsGapImpactChanged(
            old_impact=Impact(record.impact).value,
            new_impact=state.impact.value,
            row_version=updated.row_version,
        ),
        subject_type=GAP_SUBJECT_TYPE,
        subject_id=gap_id,
        opportunity_id=opportunity_id,
    )
    _log_change("gaps.gap_impact_changed", record, user_id, updated.row_version)
    return await _view(uow, updated)


async def dismiss_gap(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    gap_id: UUID,
    body: GapDismissalRequest,
    if_match: str | None,
) -> Gap:
    """Dismiss an open Gap with a reason kind (and note). `if_match` is the raw `If-Match`
    header (428/412)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record = await _load(uow, opportunity_id, gap_id)
    try:
        note = rules.dismiss_note(body.reason_kind, body.note)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    expected = _expected(if_match)
    at = datetime.now(UTC)
    try:
        state = rules.dismiss_gap(
            _state(record),
            kind=body.reason_kind,
            note=note,
            user_id=user_id,
            at=at,
            mandatory_applies=_mandatory_applies(record),
        )
    except rules.GapNotOpenTransitionError:
        raise GapNotOpenError(NOT_OPEN_DETAIL) from None
    except rules.GapMandatoryError:
        raise GapMandatoryError(rules.MANDATORY_DISMISS_DETAIL) from None
    if record.row_version != expected:
        raise _stale()
    updated = await _write(
        uow,
        record,
        state,
        expected=expected,
        user_id=user_id,
        not_in_state=GapNotOpenError(NOT_OPEN_DETAIL),
    )
    await _history(
        uow,
        gap_id,
        GapHistoryKind.DISMISSED,
        user_id=user_id,
        at=at,
        reason_kind=body.reason_kind.value,
        reason=note,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsGapDismissed(
            reason_kind=body.reason_kind.value,
            row_version=updated.row_version,
        ),
        subject_type=GAP_SUBJECT_TYPE,
        subject_id=gap_id,
        opportunity_id=opportunity_id,
    )
    _log_change("gaps.gap_dismissed", record, user_id, updated.row_version)
    return await _view(uow, updated)


async def reopen_gap(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    gap_id: UUID,
    body: GapReopening,
    if_match: str | None,
) -> Gap:
    """Reopen a dismissed or answered Gap, with a reason. `if_match` is the raw `If-Match`
    header (428/412). An answered Gap's question is `sent` again."""
    user_id = await _authorized(uow, actor, opportunity_id)
    record = await _load(uow, opportunity_id, gap_id)
    reason = _reason(body.reason)
    expected = _expected(if_match)
    try:
        state = rules.reopen_gap(_state(record))
    except rules.GapNotReopenableTransitionError:
        raise GapNotReopenableError(NOT_REOPENABLE_DETAIL) from None
    if record.row_version != expected:
        raise _stale()
    updated = await _write(
        uow,
        record,
        state,
        expected=expected,
        user_id=user_id,
        not_in_state=GapNotReopenableError(NOT_REOPENABLE_DETAIL),
    )
    if record.status == GapStatus.ANSWERED:
        await _reopen_question(uow, record, user_id=user_id)
    await _history(
        uow, gap_id, GapHistoryKind.REOPENED, user_id=user_id, at=datetime.now(UTC), reason=reason
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=GapsGapReopened(row_version=updated.row_version),
        subject_type=GAP_SUBJECT_TYPE,
        subject_id=gap_id,
        opportunity_id=opportunity_id,
    )
    _log_change("gaps.gap_reopened", record, user_id, updated.row_version)
    return await _view(uow, updated)


async def _reopen_question(uow: UnitOfWork, gap: GapRecord, *, user_id: UUID) -> None:
    """The answered question of a reopened Gap is `sent` again, its answer cleared."""
    question = (await repo.questions_for(uow, [gap.id])).get(gap.id)
    if question is None or question.status != QuestionStatus.ANSWERED:
        return
    state = rules.reopen_question(
        QuestionState(
            text=question.text,
            topic=question.topic,
            status=QuestionStatus(question.status),
            approved_by=question.approved_by,
            approved_at=question.approved_at,
            edited_by_human=question.edited_by_human,
            sent_on=question.sent_on,
            sent_by=question.sent_by,
            answered_on=question.answered_on,
            answered_by=question.answered_by,
            answer_passage_id=question.answer_passage_id,
        )
    )
    updated = await repo.update_question(
        uow,
        question.id,
        expected_row_version=question.row_version,
        text_=state.text,
        topic=state.topic,
        status=state.status.value,
        approved_by=state.approved_by,
        approved_at=state.approved_at,
        edited_by_human=state.edited_by_human,
        changed_by=user_id,
        status_changed_at=datetime.now(UTC),
        sent_on=state.sent_on,
        sent_by=state.sent_by,
    )
    if updated is None:  # pragma: no cover - the Opportunity's lock is held
        raise _stale()
