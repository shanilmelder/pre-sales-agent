"""Gap queries and the detection start command (Story 4.3).

- `list_gaps`: the Opportunity's open Gaps, ranked by impact (mandatory first within an
  impact, Story 4.2), then its answered Gaps (Story
  4.7), then its converted Gaps (Story 8.4), then its dismissed Gaps (Story 4.4), each group
  in the same order, each with the answer to its question and the open answer suggestions
  (Story 4.7), the
  Requirements it relates to, its Clarification Question, its dismissal and its history, and
  its latest detection (anyone who can read the Opportunity; a sales representative sees
  only approved, sent and unanswered questions, Stories 4.5 and 4.6, and no reason or note
  text, Story 4.4).
- `irrelevance_share`: the FR-11 live irrelevance measure (Story 4.4).
- `start_detection`: queue a new detection, e.g. to retry a failed one
  (`gaps.detection.start`: the owner and collaborators except sales representatives; other
  readers 403, everyone else the Opportunity's 404). 409 `gap_detection_in_progress` while
  one is queued or running; one past `stale_after()` is marked failed (`model_timeout`)
  first, so it never blocks.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.adapters.repository import (
    DetectionRecord,
    GapHistoryRecord,
    GapRecord,
    QuestionRecord,
)
from app.modules.gaps.application.detection import (
    CLARIFICATION_AGENT,
    fail_stale,
    queue_detection,
    stale_after,
)
from app.modules.gaps.application.models import (
    GAP_TRIGGER,
    AnswerPassage,
    AnswerSuggestion,
    ClarificationQuestion,
    Detection,
    Gap,
    GapAnswer,
    GapDismissal,
    GapHistoryEntry,
    GapHistoryEntryKind,
    GapList,
    GapRequirement,
    IrrelevanceShare,
)
from app.modules.gaps.domain.gaps import (
    APPROVED_STATUSES,
    IN_PROGRESS,
    OPEN_TO_ANSWER,
    ConvertedTo,
    DetectionErrorCode,
    DetectionStatus,
    DismissReasonKind,
    GapCategory,
    GapOrigin,
    GapStatus,
    Impact,
    QuestionStatus,
    impact_rank,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Role
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.modules.opportunities.application.public import UserRef
from app.modules.registry.application import public as registry
from app.platform.errors import GapDetectionInProgressError
from app.platform.logging import get_logger
from app.platform.storage import BlobStore
from app.platform.uow import UnitOfWork

IN_PROGRESS_DETAIL = "Gaps are already being detected for this Opportunity."
EXCERPT_MAX = 140
PASSAGE_EXCERPT_MAX = 280
INACTIVE_LABEL = "Superseded"
UNKNOWN_USER = "Unknown user"
_log = get_logger(__name__)


def excerpt(text: str, limit: int = EXCERPT_MAX) -> str:
    """At most `limit` code points of `text` on one line, cut at whitespace where possible,
    ending in `…` when cut."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def _detection(record: DetectionRecord | None) -> Detection | None:
    """The read model of the latest detection. One still queued or running past
    `stale_after()` is lost: it reads as failed with `model_timeout`, so it can be retried
    (`start_detection` records that)."""
    if record is None:
        return None
    lost = (
        DetectionStatus(record.status) in IN_PROGRESS
        and datetime.now(UTC) - record.created_at > stale_after()
    )
    if lost:
        return Detection(status=DetectionStatus.FAILED, error_code=DetectionErrorCode.MODEL_TIMEOUT)
    return Detection(
        status=DetectionStatus(record.status),
        error_code=None if record.error_code is None else DetectionErrorCode(record.error_code),
    )


def _ranked(records: list[GapRecord]) -> list[GapRecord]:
    """High, medium, low; mandatory Gaps first within an impact (Story 4.2), then oldest
    first."""
    return sorted(
        records,
        key=lambda g: (
            impact_rank(g.impact),
            g.origin != GapOrigin.MANDATORY_CHECKLIST,
            g.created_at,
            g.id,
        ),
    )


def question_view(question: QuestionRecord, names: Mapping[UUID, str]) -> ClarificationQuestion:
    def ref(user_id: UUID | None) -> UserRef | None:
        if user_id is None:
            return None
        return UserRef(id=str(user_id), name=names.get(user_id, UNKNOWN_USER))

    return ClarificationQuestion(
        id=str(question.id),
        text=question.text,
        topic=question.topic,
        status=QuestionStatus(question.status),
        status_changed_at=question.status_changed_at,
        row_version=question.row_version,
        approved_by=ref(question.approved_by),
        approved_at=question.approved_at,
        edited_by_human=question.edited_by_human,
        last_changed_by=ref(question.changed_by),
        sent_on=question.sent_on,
        sent_by=ref(question.sent_by),
        answered_on=question.answered_on,
        answered_by=ref(question.answered_by),
        from_checklist=question.from_checklist,
    )


async def question_names(
    uow: UnitOfWork, questions: Iterable[QuestionRecord], *, also: Iterable[UUID] = ()
) -> dict[UUID, str]:
    """The names of the people who approved, sent or last changed these questions, and of
    `also`."""
    wanted = {
        user_id
        for q in questions
        for user_id in (q.approved_by, q.changed_by, q.sent_by, q.answered_by)
        if user_id is not None
    } | set(also)
    return await identity.user_names(uow, wanted) if wanted else {}


def _user_ref(user_id: UUID, names: Mapping[UUID, str]) -> UserRef:
    return UserRef(id=str(user_id), name=names.get(user_id, UNKNOWN_USER))


def _history(
    gap: GapRecord,
    entries: list[GapHistoryRecord],
    names: Mapping[UUID, str],
    *,
    redacted: bool,
) -> list[GapHistoryEntry]:
    """The Gap's history, opened by the Clarification Agent raising it."""
    history = [
        GapHistoryEntry(
            kind="raised",
            at=gap.created_at,
            actor="agent",
            old_impact=None,
            new_impact=None,
            reason_kind=None,
            reason=None,
        )
    ]
    for entry in entries:
        history.append(
            GapHistoryEntry(
                kind=cast(GapHistoryEntryKind, entry.kind),  # the table's check
                at=entry.at,
                actor="agent" if entry.actor_id is None else _user_ref(entry.actor_id, names),
                old_impact=None if entry.old_impact is None else Impact(entry.old_impact),
                new_impact=None if entry.new_impact is None else Impact(entry.new_impact),
                reason_kind=None
                if entry.reason_kind is None
                else DismissReasonKind(entry.reason_kind),
                reason=None if redacted else entry.reason,
            )
        )
    return history


def _dismissal(gap: GapRecord, names: Mapping[UUID, str], *, redacted: bool) -> GapDismissal | None:
    if (
        gap.status != GapStatus.DISMISSED
        or gap.dismiss_reason_kind is None
        or gap.dismissed_by is None
        or gap.dismissed_at is None
    ):
        return None
    return GapDismissal(
        reason_kind=DismissReasonKind(gap.dismiss_reason_kind),
        note=None if redacted else gap.dismiss_note,
        by=_user_ref(gap.dismissed_by, names),
        at=gap.dismissed_at,
    )


def _answer_passage(ref: intake.PassageRef) -> AnswerPassage:
    return AnswerPassage(
        passage_id=str(ref.passage_id),
        source_id=str(ref.source_id),
        source_version=ref.source_version,
        filename=ref.filename,
        label=ref.label,
        excerpt=excerpt(ref.text, PASSAGE_EXCERPT_MAX),
    )


def _answer_of(gap: GapRecord, question: QuestionRecord | None) -> tuple[date, UUID, UUID] | None:
    """When, by whom and with which passage the Gap (or, when the answer did not settle it,
    its question) was answered."""
    if gap.answered_on is not None and gap.answered_by and gap.answer_passage_id:
        return gap.answered_on, gap.answered_by, gap.answer_passage_id
    if (
        question is not None
        and question.status == QuestionStatus.ANSWERED
        and question.answered_on is not None
        and question.answered_by is not None
        and question.answer_passage_id is not None
    ):
        return question.answered_on, question.answered_by, question.answer_passage_id
    return None


async def gap_views(
    uow: UnitOfWork,
    opportunity_id: UUID,
    records: list[GapRecord],
    *,
    approved_only: bool = False,
    store: BlobStore | None = None,
) -> list[Gap]:
    """The read models of these Gaps, in the given order. With `approved_only` (a sales
    representative's view, Stories 4.5, 4.4 and 4.6), a question that isn't `approved`,
    `sent` or `unanswered` is left out, and the history and dismissal come without their
    reason and note text."""
    gap_ids = [g.id for g in records]
    links = await repo.links_for(uow, gap_ids)
    questions = await repo.questions_for(uow, gap_ids)
    history = await repo.history_for(uow, gap_ids)
    if approved_only:
        questions = {gap_id: q for gap_id, q in questions.items() if q.status in APPROVED_STATUSES}
    people = {
        user_id
        for g in records
        for user_id in (g.dismissed_by, g.changed_by, g.answered_by)
        if user_id is not None
    } | {e.actor_id for entries in history.values() for e in entries if e.actor_id is not None}
    answers = {g.id: _answer_of(g, questions.get(g.id)) for g in records}
    open_questions = {
        q.id: gap_id
        for gap_id, q in questions.items()
        if q.status in OPEN_TO_ANSWER and gap_id in {g.id for g in records if g.status == "open"}
    }
    suggestions = await repo.suggested_matches(uow, list(open_questions))
    passage_ids = [a[2] for a in answers.values() if a is not None] + [
        s.passage_id for s in suggestions
    ]
    passages = await intake.passage_refs(uow, opportunity_id, passage_ids, store=store)
    changes: dict[UUID, list[intake.RequirementChangeRef]] = {}
    for answer in answers.values():
        ref = None if answer is None else passages.get(answer[2])
        if ref is not None and ref.source_id not in changes:
            changes[ref.source_id] = await intake.requirement_changes_for_source(uow, ref.source_id)
    suggested: dict[UUID, list[AnswerSuggestion]] = defaultdict(list)
    for match in suggestions:
        ref = passages.get(match.passage_id)
        if ref is None:
            continue
        suggested[open_questions[match.question_id]].append(
            AnswerSuggestion(
                id=str(match.id),
                question_id=str(match.question_id),
                passage=_answer_passage(ref),
                injection_suspected=match.injection_suspected,
                row_version=match.row_version,
                created_at=match.created_at,
            )
        )
    people |= {a[1] for a in answers.values() if a is not None}
    names = await question_names(uow, questions.values(), also=people)
    active = {
        s.id: s.number for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    texts = await intake.requirement_version_texts(
        uow,
        opportunity_id,
        list({(link.requirement_id, link.requirement_version) for link in links}),
    )
    related: dict[UUID, list[tuple[int, GapRequirement]]] = defaultdict(list)
    for link in links:
        number = active.get(link.requirement_id)
        found = texts.get((link.requirement_id, link.requirement_version))
        related[link.gap_id].append(
            (
                number if number is not None else len(active) + 1,
                GapRequirement(
                    id=str(link.requirement_id),
                    version=link.requirement_version,
                    label=f"R{number}" if number is not None else INACTIVE_LABEL,
                    excerpt="" if found is None else excerpt(found.text),
                ),
            )
        )
    views: list[Gap] = []
    for g in records:
        question = questions.get(g.id)
        views.append(
            Gap(
                id=str(g.id),
                title=g.title,
                category=GapCategory(g.category),
                trigger=GAP_TRIGGER.validate_python(g.trigger),
                why_it_matters=g.why_it_matters,
                impact=Impact(g.impact),
                impact_basis=g.impact_basis,
                origin=GapOrigin(g.origin),
                status=GapStatus(g.status),
                converted_to=None if g.converted_to is None else ConvertedTo(g.converted_to),
                row_version=g.row_version,
                created_at=g.created_at,
                requirements=[
                    r for _, r in sorted(related[g.id], key=lambda pair: (pair[0], pair[1].id))
                ],
                question=None if question is None else question_view(question, names),
                dismissal=_dismissal(g, names, redacted=approved_only),
                history=_history(g, history.get(g.id, []), names, redacted=approved_only),
                last_changed_by=None if g.changed_by is None else _user_ref(g.changed_by, names),
                answer=_gap_answer(answers[g.id], passages, changes, names),
                answer_suggestions=suggested.get(g.id, []),
                checklist_applies=g.checklist_applies,
                why_entry_id=None if g.why_entry_id is None else str(g.why_entry_id),
            )
        )
    return views


def _gap_answer(
    answer: tuple[date, UUID, UUID] | None,
    passages: Mapping[UUID, intake.PassageRef],
    changes: Mapping[UUID, list[intake.RequirementChangeRef]],
    names: Mapping[UUID, str],
) -> GapAnswer | None:
    if answer is None:
        return None
    answered_on, answered_by, passage_id = answer
    ref = passages.get(passage_id)
    return GapAnswer(
        answered_on=answered_on,
        answered_by=_user_ref(answered_by, names),
        passage=None if ref is None else _answer_passage(ref),
        requirement_changes=[] if ref is None else changes.get(ref.source_id, []),
    )


def sees_only_approved_questions(actor: Principal) -> bool:
    """A sales representative (every role they hold is sales representative) sees only
    approved, sent and unanswered Clarification Questions (Stories 4.5, 4.6)."""
    return bool(actor.roles) and actor.roles <= {Role.SALES_REPRESENTATIVE}


async def list_gaps(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    *,
    store: BlobStore | None = None,
) -> GapList:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    records = [
        gap
        for status in (
            GapStatus.OPEN,
            GapStatus.ANSWERED,
            GapStatus.CONVERTED,
            GapStatus.DISMISSED,
        )
        for gap in _ranked(await repo.gaps_in(uow, opportunity_id, status.value))
    ]
    return GapList(
        items=await gap_views(
            uow,
            opportunity_id,
            records,
            approved_only=sees_only_approved_questions(actor),
            store=store,
        ),
        detection=_detection(await repo.latest_detection(uow, opportunity_id)),
        can_start_detection=identity.can(actor, Action.GAP_DETECTION_START, resource),
        can_edit_questions=identity.can(actor, Action.GAP_QUESTION_EDIT, resource),
        can_edit_gaps=identity.can(actor, Action.GAP_EDIT, resource),
        can_send_questions=identity.can(actor, Action.GAP_QUESTION_SEND, resource),
    )


async def irrelevance_share(uow: UnitOfWork, opportunity_id: UUID | None) -> IrrelevanceShare:
    """The FR-11 live irrelevance measure: detected Gaps that are not superseded, and how many
    of them are dismissed as "Not relevant", for one Opportunity or (None) all of them. No
    authorization: for evaluation and reporting code, not the API."""
    raised, dismissed = await repo.irrelevance_counts(uow, opportunity_id)
    return IrrelevanceShare(raised=raised, dismissed_not_relevant=dismissed)


async def start_detection(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> Detection:
    """Queue a new Gap detection of the Opportunity (the Retry of a failed one)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.GAP_DETECTION_START, resource)
    await registry.require_enabled(uow, CLARIFICATION_AGENT)  # 409 while it is disabled
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    busy = await repo.detection_in(uow, opportunity_id, tuple(s.value for s in IN_PROGRESS))
    if busy is not None:
        raise GapDetectionInProgressError(IN_PROGRESS_DETAIL)
    detection_id = await queue_detection(uow, opportunity_id)
    _log.info(
        "gaps.detection_started",
        extra={
            "opportunity_id": str(opportunity_id),
            "detection_id": str(detection_id),
            "actor_id": actor.actor.id,
        },
    )
    return Detection(status=DetectionStatus.QUEUED, error_code=None)
