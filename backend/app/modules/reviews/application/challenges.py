"""Challenges (Story 9.5; AD-28, FR-38): raise, confirm the reassessment, decline, and the
reads behind the Challenge dialog.

Every command runs in one Unit of Work: `identity.authorize`, the Opportunity's Estimate lock
(`platform.locks.opportunity_lock`), the rows `for_update`, the state rules, the `If-Match` check
(428/412), the writes, the trace, then the Inbox item.

**Raise** (`reviews.challenge.raise`: the Opportunity's owner, or a reviewer with a `pending`
Review Request on it; a collaborator, a sales representative or another reviewer 403). The
target is the Estimate Version in context, one of the Opportunity's current Assessments, or
a Finding of one (422 otherwise: Critic and Red Team Findings take Evidence, Resolve or
Override instead). The version in context is the Review Request's (`review_request_id`), the
target's for an Estimate Version, else `estimates.current_reviewable_version`: 409
`challenge_needs_estimate` when there is none, `challenge_version_superseded` when a newer
version replaced it. The reason is required (1 to 1,000 characters, 422). The suggestions
(`challenges.suggest`) are stored on the Challenge, which is `awaiting_confirmation`;
`reviews.challenge.raised` is traced. From a Review Request (the caller's, else 403
`reviewer_not_authorized`; `pending`, else 409 `review_request_not_pending`) a `challenged`
Review Decision is recorded and the request becomes `challenged`: its reviewer keeps read
access. A reviewer's Challenge gives the owner a `challenge_raised` Inbox item (key
`challenge:{id}:raised`). The owner may pass `confirmed`, and the same Unit of Work confirms
(below), tracing both events; only the owner may (403).

**Confirm** (`reviews.challenge.confirm`, the owner only; `If-Match` the Challenge's
`row_version`): a Challenge already `reassessing` returns as it is, with its run (no new run,
no new event); one in any other state but `awaiting_confirmation` is 409
`challenge_not_awaiting_confirmation`; a superseded version in context 409
`challenge_version_superseded`; then the `If-Match` check. `confirmed` must be at least one
of the suggested agents (422). Starts the `challenge` Workflow Run
(`workflows.start_run(run_type=challenge, trigger_ref=<id>,
idempotency_key=run:<opp>:challenge:<id>)`: the confirmed Assessments, then the Critic; 409
`assessment_in_progress` while another run is active), stores `confirmed` and the run, sets
`reassessing` and traces `reviews.challenge.confirmed`.

**Decline** (`reviews.challenge.decline`, the owner only; `If-Match`; a required reason):
`declined`, a `challenged` Review Request goes back to `pending`, `reviews.challenge.declined`
is traced and the challenger gets a `challenge_declined` Inbox item (key
`challenge:{id}:declined`). Nothing is written on any error.

Only Story 9.6's run writes `completed` or `failed`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.public import ReviewableVersion, VersionStatus
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.intake.application import public as intake
from app.modules.notifications.application import public as notifications
from app.modules.notifications.application.public import NotificationKind
from app.modules.opportunities.application import public as opportunities
from app.modules.reviews.adapters import repository as repo
from app.modules.reviews.adapters.repository import ChallengeRecord, RequestRecord
from app.modules.reviews.application.models import (
    ChallengeConfirm,
    ChallengeCreate,
    ChallengeDecline,
    ChallengeState,
    ChallengeSuggestions,
    ChallengeSuggestionView,
    ChallengeTargetView,
    ChallengeView,
    ReviewPerson,
)
from app.modules.reviews.application.requests import (
    MAX_ROW_VERSION,
    REQUEST_NOT_FOUND,
    UNKNOWN_USER,
    opportunity_title,
)
from app.modules.reviews.domain.challenges import (
    AGENT_LABELS,
    ALWAYS_RERUN,
    CHALLENGE_STATUS_LABELS,
    SUBJECT_TYPE,
    ChallengeStatus,
    ChallengeTargetKind,
    CitingAssessment,
    Suggestion,
    SuggestionTag,
    clean_challenge_reason,
    suggest,
    transition,
)
from app.modules.reviews.domain.decisions import Decision
from app.modules.reviews.domain.requests import (
    REASON_MAX,
    RequestStatus,
)
from app.modules.reviews.domain.requests import (
    SUBJECT_TYPE as REQUEST_SUBJECT_TYPE,
)
from app.modules.reviews.domain.requests import (
    transition as request_transition,
)
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ChallengeNeedsEstimateError,
    ChallengeNotAwaitingConfirmationError,
    ChallengeVersionSupersededError,
    ForbiddenError,
    NotFoundError,
    ReviewerNotAuthorizedError,
    ReviewRequestNotPendingError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.locks import opportunity_lock
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    ReviewsChallengeConfirmed,
    ReviewsChallengeDeclined,
    ReviewsChallengeRaised,
    ReviewsReviewDecisionRecorded,
)
from app.platform.uow import UnitOfWork

CHALLENGE_NOT_FOUND = "No Challenge with this id."
VERSION_NOT_FOUND = "No Estimate Version with this id."
NEEDS_ESTIMATE = "There is no Estimate Version to challenge yet."
NOT_ALLOWED = (
    "Only the Opportunity's owner, or a reviewer with a pending Review Request on it, can "
    "raise a Challenge."
)
OWNER_ONLY_CONFIRM = "Only the Opportunity's owner can confirm a reassessment."
OWNER_ONLY_DECLINE = "Only the Opportunity's owner can decline a Challenge."
NOT_THE_REVIEWER = "Only this Review Request's reviewer can challenge it."
REQUEST_NOT_PENDING = "Only a pending Review Request can be challenged."
NOT_AWAITING = "This Challenge is no longer awaiting confirmation."
REASON_RULE = f"Give a reason of 1 to {REASON_MAX:,} characters."
DECLINE_REASON_RULE = f"Give a reason for declining of 1 to {REASON_MAX:,} characters."
NONE_TICKED = "Tick at least one Assessment to rerun."
NOT_SUGGESTED = "Pick the Assessments to rerun from the suggestions."
NOT_CURRENT = (
    "Only the Estimate Version in context, a current Assessment or one of its Findings can be "
    "challenged."
)
NOT_SPECIALIST = (
    "Only a Finding of a current specialist Assessment can be challenged. Critic and Red Team "
    "Findings take Supply evidence, Resolve or Override instead."
)
STALE = "This Challenge changed since you opened it. Reload and try again."
WHY_FINDING = "Holds the challenged Finding"
WHY_ASSESSMENT = "The challenged Assessment"
NOT_ASSESSED = "Not assessed yet"
AGENT_SHORT = {"engineering_agent": "Engineering", "pm_agent": "PM", "security_agent": "Security"}
_log = get_logger(__name__)


def superseded_detail(version: ReviewableVersion) -> str:
    """E.g. "v2 is superseded by v3. Raise the Challenge again on v3 if it still applies."."""
    newer = version.superseded_by_version
    if newer is None:
        return f"v{version.version} is superseded."
    return (
        f"v{version.version} is superseded by v{newer}. Raise the Challenge again on v{newer} "
        "if it still applies."
    )


def challenge_key(opportunity_id: UUID, challenge_id: UUID) -> str:
    """The idempotency key of a Challenge's reassessment run."""
    return f"run:{opportunity_id}:challenge:{challenge_id}"


def _is_owner(actor: Principal, resource: Resource) -> bool:
    return actor.user_id is not None and actor.user_id == resource.owner_id


def _user(actor: Principal) -> UUID:
    user_id = actor.user_id
    if user_id is None:
        raise ForbiddenError(NOT_ALLOWED)
    return user_id


# --- the target and its suggestions ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Target:
    kind: ChallengeTargetKind
    id: UUID
    version: int
    assessment_id: UUID | None
    label: str
    suggestions: list[Suggestion]


async def _version_in_context(
    uow: UnitOfWork,
    opportunity_id: UUID,
    kind: ChallengeTargetKind,
    target_id: UUID,
    request: RequestRecord | None,
) -> ReviewableVersion:
    if request is not None:
        version = await estimates.reviewable_version(uow, request.estimate_version_id)
    elif kind is ChallengeTargetKind.ESTIMATE_VERSION:
        version = await estimates.reviewable_version(uow, target_id)
        if version is None or version.opportunity_id != opportunity_id:
            raise UnprocessableError(NOT_CURRENT)
    else:
        version = await estimates.current_reviewable_version(uow, opportunity_id)
    if version is None:
        raise ChallengeNeedsEstimateError(NEEDS_ESTIMATE)
    return version


def _assessment_label(agent: str, version: int) -> str:
    return f"{AGENT_SHORT.get(agent, agent)} Assessment v{version}"


def _title(target: ChallengeTargetView) -> str:
    return f"Challenge {target.label}"


async def _resolve_target(
    uow: UnitOfWork,
    opportunity_id: UUID,
    kind: ChallengeTargetKind,
    target_id: UUID,
    version: ReviewableVersion,
) -> _Target:
    """The target, with the version it is challenged at and the deterministic suggestions;
    422 when it is not a current Assessment (or one of its Findings) or the version in
    context."""
    # Imported here: assessments imports estimates' public API, which reads this module's
    # public API lazily for the blockers.
    from app.modules.assessments.application import public as assessments

    citations = await assessments.current_citations(uow, opportunity_id)
    numbers: dict[UUID, int] = {}
    for c in citations:
        numbers.update(c.requirement_numbers)
    all_requirements = sorted({r for c in citations for r in c.requirement_ids}, key=str)
    tagged = await intake.integration_types_by_requirement(uow, all_requirements)
    types = {rid: [(UUID(t.id), t.name) for t in found] for rid, found in tagged.items()}

    holders: list[tuple[str, str]]
    target_requirements: frozenset[UUID] = frozenset()
    assessment_id: UUID | None = None
    holder_agent: str | None = None
    if kind is ChallengeTargetKind.ESTIMATE_VERSION:
        if target_id != version.id:
            raise UnprocessableError(NOT_CURRENT)
        number = version.version
        label = f"Estimate v{number}"
        holders = [(c.agent, f"Feeds Estimate v{number}") for c in citations]
        if not holders:  # nothing assessed yet: every specialist may run
            holders = [(agent.value, NOT_ASSESSED) for agent in assessments.AGENTS]
        target_version = number
    elif kind is ChallengeTargetKind.ASSESSMENT:
        found = next((c for c in citations if c.assessment_id == target_id), None)
        if found is None:
            raise UnprocessableError(NOT_CURRENT)
        label = _assessment_label(found.agent, found.version)
        holders = [(found.agent, WHY_ASSESSMENT)]
        target_requirements = found.requirement_ids
        assessment_id, holder_agent = found.assessment_id, found.agent
        target_version = found.version
    else:
        hit = next(((c, f) for c in citations for f in c.findings if f.id == target_id), None)
        if hit is None:
            raise UnprocessableError(NOT_SPECIALIST)
        holder, finding = hit
        label = f"Finding: {finding.title}"
        holders = [(holder.agent, WHY_FINDING)]
        target_requirements = finding.requirement_ids
        assessment_id, holder_agent = holder.assessment_id, holder.agent
        target_version = holder.version
    suggestions = suggest(
        holders=holders,
        target_requirements=target_requirements,
        requirement_numbers=numbers,
        requirement_types=types,
        others=[
            CitingAssessment(agent=c.agent, requirement_ids=c.requirement_ids)
            for c in citations
            if c.agent != holder_agent
        ],
    )
    return _Target(
        kind=kind,
        id=target_id,
        version=target_version,
        assessment_id=assessment_id,
        label=label,
        suggestions=suggestions,
    )


def _suggestion_views(stored: Sequence[dict[str, object]]) -> list[ChallengeSuggestionView]:
    views: list[ChallengeSuggestionView] = []
    for item in stored:
        agent = str(item.get("agent", ""))
        tag = SuggestionTag(str(item.get("tag", SuggestionTag.OPTIONAL.value)))
        views.append(
            ChallengeSuggestionView(
                agent=agent,
                label=AGENT_LABELS.get(agent, agent),
                why=str(item.get("why", "")),
                tag=tag,
                preselected=tag is SuggestionTag.SUGGESTED,
            )
        )
    return views


def _stored(suggestions: Sequence[Suggestion]) -> list[dict[str, object]]:
    return [{"agent": s.agent, "why": s.why, "tag": s.tag.value} for s in suggestions]


def _clean_confirmed(raw: Sequence[str], suggested: Sequence[dict[str, object]]) -> list[str]:
    picked = list(dict.fromkeys(a.strip() for a in raw))
    if not picked:
        raise UnprocessableError(NONE_TICKED)
    allowed = [str(s.get("agent")) for s in suggested]
    if any(a not in allowed for a in picked):
        raise UnprocessableError(NOT_SUGGESTED)
    return [a for a in allowed if a in picked]


# --- views -----------------------------------------------------------------------------------


async def _target_view(uow: UnitOfWork, record: ChallengeRecord) -> ChallengeTargetView:
    from app.modules.assessments.application import public as assessments

    kind = ChallengeTargetKind(record.target_kind)
    if kind is ChallengeTargetKind.ESTIMATE_VERSION:
        label = f"Estimate v{record.target_version}"
    else:
        found = (
            None
            if record.assessment_id is None
            else await assessments.assessment_at(uow, record.assessment_id, record.target_version)
        )
        if kind is ChallengeTargetKind.ASSESSMENT:
            agent = found.agent.value if found is not None else ""
            label = _assessment_label(agent, record.target_version) if agent else "Assessment"
        else:
            findings = found.findings if found is not None else []
            title = next((f.title for f in findings if f.id == str(record.target_id)), None)
            label = f"Finding: {title}" if title else "Finding"
    return ChallengeTargetView(
        kind=kind, id=str(record.target_id), version=record.target_version, label=label
    )


def _may(actor: Principal, resource: Resource, action: Action, record: ChallengeRecord) -> bool:
    return (
        record.status == ChallengeStatus.AWAITING_CONFIRMATION
        and _is_owner(actor, resource)
        and identity.can(actor, action, resource)
    )


async def _view(
    uow: UnitOfWork, actor: Principal, resource: Resource, record: ChallengeRecord
) -> ChallengeView:
    from app.modules.workflows.application import public as workflows

    version = await estimates.reviewable_version(uow, record.estimate_version_id)
    names = await identity.user_names(uow, {record.challenger_id})
    target = await _target_view(uow, record)
    status = ChallengeStatus(record.status)
    run_number = (
        None
        if record.workflow_run_id is None
        else await workflows.run_number(uow, record.opportunity_id, record.workflow_run_id)
    )
    assert record.created_at is not None and record.updated_at is not None  # read from the DB
    superseded_by = _superseded_by(version)
    superseded_by_id: str | None = None
    if superseded_by is not None:
        current = await estimates.current_reviewable_version(uow, record.opportunity_id)
        superseded_by_id = None if current is None else str(current.id)
    return ChallengeView(
        id=str(record.id),
        title=_title(target),
        target=target,
        estimate_version_id=str(record.estimate_version_id),
        estimate_version=0 if version is None else version.version,
        superseded_by=superseded_by,
        superseded_by_id=superseded_by_id,
        review_request_id=(
            None if record.review_request_id is None else str(record.review_request_id)
        ),
        challenger=ReviewPerson(
            id=str(record.challenger_id), name=names.get(record.challenger_id, UNKNOWN_USER)
        ),
        reason=record.reason,
        status=status,
        status_label=CHALLENGE_STATUS_LABELS[status],
        suggested=_suggestion_views(record.suggested),
        confirmed=record.confirmed,
        always_rerun=list(ALWAYS_RERUN),
        decline_reason=record.decline_reason,
        workflow_run_id=None if record.workflow_run_id is None else str(record.workflow_run_id),
        run_number=run_number,
        row_version=record.row_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        can_confirm=_may(actor, resource, Action.CHALLENGE_CONFIRM, record),
        can_decline=_may(actor, resource, Action.CHALLENGE_DECLINE, record),
    )


def _superseded_by(version: ReviewableVersion | None) -> int | None:
    if version is None or version.status != VersionStatus.SUPERSEDED:
        return None
    return version.superseded_by_version


def _check_superseded(version: ReviewableVersion | None) -> None:
    if version is not None and version.status == VersionStatus.SUPERSEDED:
        raise ChallengeVersionSupersededError(superseded_detail(version))


async def _load(
    uow: UnitOfWork, opportunity_id: UUID, challenge_id: UUID, *, for_update: bool = False
) -> ChallengeRecord:
    record = await repo.get_challenge(uow, challenge_id, for_update=for_update)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(CHALLENGE_NOT_FOUND)
    return record


def _check_if_match(if_match: str | None, record: ChallengeRecord) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or record.row_version != expected:
        raise RowVersionMismatchError(STALE)
    return expected


# --- Inbox items ------------------------------------------------------------------------------


def challenge_summary(kind: NotificationKind, target_label: str, title: str | None) -> str:
    """E.g. "Challenge: Estimate v3 — {Opportunity}": the target and the Opportunity's title
    only, never the reason."""
    head = (
        f"Challenge: {target_label}"
        if kind is NotificationKind.CHALLENGE_RAISED
        else f"Challenge declined: {target_label}"
    )
    return f"{head} — {title}" if title else head


async def _notify(
    uow: UnitOfWork,
    *,
    kind: NotificationKind,
    recipient_id: UUID,
    record: ChallengeRecord,
    target_label: str,
    suffix: str,
) -> None:
    await notifications.notify(
        uow,
        recipient_id=recipient_id,
        kind=kind,
        opportunity_id=record.opportunity_id,
        subject_type=SUBJECT_TYPE,
        subject_id=record.id,
        subject_version=record.row_version,
        summary=challenge_summary(
            kind, target_label, await opportunity_title(uow, record.opportunity_id)
        ),
        dedupe_key=f"challenge:{record.id}:{suffix}",
    )


# --- commands --------------------------------------------------------------------------------


async def _confirm(
    uow: UnitOfWork,
    actor: Principal,
    record: ChallengeRecord,
    confirmed: list[str],
    expected: int,
) -> ChallengeRecord:
    """Start the reassessment run and move the Challenge to `reassessing` (the caller holds
    the lock and checked the state, the version and `If-Match`)."""
    from app.modules.workflows.application import public as workflows

    run = await workflows.start_run(
        uow,
        actor,
        record.opportunity_id,
        run_type=workflows.RunType.CHALLENGE,
        trigger_ref=record.id,
        idempotency_key=challenge_key(record.opportunity_id, record.id),
        agents=confirmed,
    )
    status = transition(ChallengeStatus(record.status), ChallengeStatus.REASSESSING)
    updated = await repo.update_challenge(
        uow,
        record.id,
        from_status=ChallengeStatus.AWAITING_CONFIRMATION.value,
        expected_row_version=expected,
        status=status.value,
        confirmed=confirmed,
        workflow_run_id=UUID(run.id),
    )
    if updated is None:  # pragma: no cover - the row lock serialises changes
        raise RowVersionMismatchError(STALE)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ReviewsChallengeConfirmed(
            challenge_id=str(record.id), confirmed=confirmed, workflow_run_id=run.id
        ),
        subject_type=SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=record.opportunity_id,
        subject_version=updated.row_version,
    )
    _log.info(
        "reviews.challenge_confirmed",
        extra={
            "opportunity_id": str(record.opportunity_id),
            "challenge_id": str(record.id),
            "run_id": run.id,
            "confirmed_count": len(confirmed),
            "actor_id": actor.actor.id,
        },
    )
    return updated


async def _challenge_request(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    request: RequestRecord,
    reason: str,
) -> None:
    """Record the `challenged` decision and move the request to `challenged`."""
    decision = await repo.insert_decision(
        uow,
        decision_id=new_id(),
        review_request_id=request.id,
        decision=Decision.CHALLENGED.value,
        reason=reason,
        decided_by=request.reviewer_id,
        target_version=request.target_version,
        escalated_to=None,
    )
    updated = await repo.set_status(
        uow,
        request.id,
        from_status=RequestStatus.PENDING.value,
        to_status=request_transition(RequestStatus(request.status), RequestStatus.CHALLENGED).value,
        expected_row_version=request.row_version,
    )
    if updated is None:  # pragma: no cover - the row lock serialises changes
        raise RowVersionMismatchError(STALE)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ReviewsReviewDecisionRecorded(
            request_id=str(request.id),
            decision_id=str(decision.id),
            decision=Decision.CHALLENGED.value,
            reason=reason,
            target_kind=request.target_kind,
            target_id=str(request.target_id),
            target_version=request.target_version,
        ),
        subject_type=REQUEST_SUBJECT_TYPE,
        subject_id=request.id,
        opportunity_id=opportunity_id,
        subject_version=updated.row_version,
    )


async def raise_challenge(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, body: ChallengeCreate
) -> ChallengeView:
    """`reviews.raise_challenge` (module docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.CHALLENGE_RAISE, resource)
    challenger = _user(actor)
    owner = _is_owner(actor, resource)
    await opportunity_lock(uow, opportunity_id)

    request: RequestRecord | None = None
    if body.review_request_id is not None:
        request = await repo.get(uow, body.review_request_id, for_update=True)
        if request is None or request.opportunity_id != opportunity_id:
            raise NotFoundError(REQUEST_NOT_FOUND)
        if request.reviewer_id != challenger:
            raise ReviewerNotAuthorizedError(NOT_THE_REVIEWER)
    elif not owner and not await repo.pending_of_reviewer(uow, opportunity_id, challenger):
        raise ForbiddenError(NOT_ALLOWED)
    if body.confirmed is not None and not owner:
        raise ForbiddenError(OWNER_ONLY_CONFIRM)
    reason = clean_challenge_reason(body.reason)
    if reason is None:
        raise UnprocessableError(REASON_RULE)
    if request is not None and request.status != RequestStatus.PENDING:
        raise ReviewRequestNotPendingError(REQUEST_NOT_PENDING)

    version = await _version_in_context(
        uow, opportunity_id, body.target_kind, body.target_id, request
    )
    _check_superseded(version)
    target = await _resolve_target(uow, opportunity_id, body.target_kind, body.target_id, version)
    suggested = _stored(target.suggestions)
    confirmed = None if body.confirmed is None else _clean_confirmed(body.confirmed, suggested)

    record = await repo.insert_challenge(
        uow,
        challenge_id=new_id(),
        opportunity_id=opportunity_id,
        target_kind=target.kind.value,
        target_id=target.id,
        target_version=target.version,
        assessment_id=target.assessment_id,
        estimate_version_id=version.id,
        review_request_id=None if request is None else request.id,
        challenger_id=challenger,
        reason=reason,
        suggested=suggested,
    )
    if request is not None:
        await _challenge_request(uow, actor, opportunity_id, request, reason)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ReviewsChallengeRaised(
            challenge_id=str(record.id),
            target_kind=target.kind.value,
            target_id=str(target.id),
            target_version=target.version,
            estimate_version_id=str(version.id),
            review_request_id=None if request is None else str(request.id),
            reason=reason,
            suggested=[s.agent for s in target.suggestions],
        ),
        subject_type=SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=opportunity_id,
        subject_version=record.row_version,
    )
    _log.info(
        "reviews.challenge_raised",
        extra={
            "opportunity_id": str(opportunity_id),
            "challenge_id": str(record.id),
            "target_kind": target.kind.value,
            "suggested_count": len(suggested),
            "actor_id": actor.actor.id,
        },
    )
    if not owner and resource.owner_id is not None:
        await _notify(
            uow,
            kind=NotificationKind.CHALLENGE_RAISED,
            recipient_id=resource.owner_id,
            record=record,
            target_label=target.label,
            suffix="raised",
        )
    if confirmed is not None:
        record = await _confirm(uow, actor, record, confirmed, record.row_version)
    return await _view(uow, actor, resource, record)


async def _owner_resource(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, action: Action, detail: str
) -> Resource:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, action, resource)
    if not _is_owner(actor, resource):
        raise ForbiddenError(detail)
    return resource


async def confirm_reassessment(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    challenge_id: UUID,
    body: ChallengeConfirm,
    if_match: str | None,
) -> ChallengeView:
    """`reviews.confirm_reassessment` (module docstring)."""
    resource = await _owner_resource(
        uow, actor, opportunity_id, Action.CHALLENGE_CONFIRM, OWNER_ONLY_CONFIRM
    )
    await opportunity_lock(uow, opportunity_id)
    record = await _load(uow, opportunity_id, challenge_id, for_update=True)
    if record.status == ChallengeStatus.REASSESSING and record.workflow_run_id is not None:
        return await _view(uow, actor, resource, record)  # confirmed already: the same run
    if record.status != ChallengeStatus.AWAITING_CONFIRMATION:
        raise ChallengeNotAwaitingConfirmationError(NOT_AWAITING)
    _check_superseded(await estimates.reviewable_version(uow, record.estimate_version_id))
    expected = _check_if_match(if_match, record)
    confirmed = _clean_confirmed(body.confirmed, record.suggested)
    updated = await _confirm(uow, actor, record, confirmed, expected)
    return await _view(uow, actor, resource, updated)


async def decline_challenge(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    challenge_id: UUID,
    body: ChallengeDecline,
    if_match: str | None,
) -> ChallengeView:
    """`reviews.decline_challenge` (module docstring)."""
    resource = await _owner_resource(
        uow, actor, opportunity_id, Action.CHALLENGE_DECLINE, OWNER_ONLY_DECLINE
    )
    await opportunity_lock(uow, opportunity_id)
    record = await _load(uow, opportunity_id, challenge_id, for_update=True)
    reason = clean_challenge_reason(body.reason)
    if reason is None:
        raise UnprocessableError(DECLINE_REASON_RULE)
    if record.status != ChallengeStatus.AWAITING_CONFIRMATION:
        raise ChallengeNotAwaitingConfirmationError(NOT_AWAITING)
    expected = _check_if_match(if_match, record)

    status = transition(ChallengeStatus(record.status), ChallengeStatus.DECLINED)
    updated = await repo.update_challenge(
        uow,
        record.id,
        from_status=ChallengeStatus.AWAITING_CONFIRMATION.value,
        expected_row_version=expected,
        status=status.value,
        decline_reason=reason,
    )
    if updated is None:  # pragma: no cover - the row lock serialises changes
        raise RowVersionMismatchError(STALE)
    if record.review_request_id is not None:
        request = await repo.get(uow, record.review_request_id, for_update=True)
        if request is not None and request.status == RequestStatus.CHALLENGED:
            await repo.set_status(
                uow,
                request.id,
                from_status=RequestStatus.CHALLENGED.value,
                to_status=request_transition(
                    RequestStatus(request.status), RequestStatus.PENDING
                ).value,
                expected_row_version=request.row_version,
            )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ReviewsChallengeDeclined(
            challenge_id=str(record.id),
            reason=reason,
            review_request_id=None
            if record.review_request_id is None
            else str(record.review_request_id),
        ),
        subject_type=SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=opportunity_id,
        subject_version=updated.row_version,
    )
    _log.info(
        "reviews.challenge_declined",
        extra={
            "opportunity_id": str(opportunity_id),
            "challenge_id": str(record.id),
            "actor_id": actor.actor.id,
        },
    )
    if record.challenger_id != actor.user_id:
        target = await _target_view(uow, updated)
        await _notify(
            uow,
            kind=NotificationKind.CHALLENGE_DECLINED,
            recipient_id=record.challenger_id,
            record=updated,
            target_label=target.label,
            suffix="declined",
        )
    return await _view(uow, actor, resource, updated)


# --- reads -----------------------------------------------------------------------------------


async def get_challenge(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, challenge_id: UUID
) -> ChallengeView:
    """One Challenge, for anyone who can read the Opportunity; 404 for one that isn't its."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    record = await _load(uow, opportunity_id, challenge_id)
    return await _view(uow, actor, resource, record)


async def may_raise_challenge(uow: UnitOfWork, actor: Principal, resource: Resource) -> bool:
    """`reviews.public.may_raise_challenge` (the `can_challenge` flag): the Opportunity's
    owner, or a reviewer with a pending Review Request on it. `resource` is the Opportunity
    the caller may read."""
    user_id = actor.user_id
    if user_id is None or not identity.can(actor, Action.CHALLENGE_RAISE, resource):
        return False
    return _is_owner(actor, resource) or bool(
        await repo.pending_of_reviewer(uow, resource.id, user_id)
    )


async def challenge_suggestions(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    target_kind: ChallengeTargetKind,
    target_id: UUID,
) -> ChallengeSuggestions:
    """What the Challenge dialog shows before anything is raised (anyone who can read the
    Opportunity; the flags say what the caller may do)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    version = await _version_in_context(uow, opportunity_id, target_kind, target_id, None)
    target = await _resolve_target(uow, opportunity_id, target_kind, target_id, version)
    view = ChallengeTargetView(
        kind=target.kind, id=str(target.id), version=target.version, label=target.label
    )
    may_raise = await may_raise_challenge(uow, actor, resource)
    return ChallengeSuggestions(
        title=_title(view),
        target=view,
        estimate_version=version.version,
        superseded_by=_superseded_by(version),
        suggested=_suggestion_views(_stored(target.suggestions)),
        always_rerun=list(ALWAYS_RERUN),
        can_raise=may_raise,
        can_confirm=may_raise
        and _is_owner(actor, resource)
        and identity.can(actor, Action.CHALLENGE_CONFIRM, resource),
    )


async def challenge_status(uow: UnitOfWork, challenge_id: UUID) -> ChallengeState | None:
    """`reviews.public.challenge_status` (an Inbox item's subject): the Challenge's status,
    challenger and run, or None when unknown. No authorization."""
    record = await repo.get_challenge(uow, challenge_id)
    if record is None:
        return None
    return ChallengeState(
        id=record.id,
        status=ChallengeStatus(record.status),
        challenger_id=record.challenger_id,
        workflow_run_id=record.workflow_run_id,
    )
