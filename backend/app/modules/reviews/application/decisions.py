"""Review Decisions (Story 9.3; AD-28, FR-37) and the review panel read.

**Decide** (`reviews.review_request.decide`: owners, collaborators and reviewer
collaborators, never a sales representative; the Opportunity's 404 for everyone else), with
`If-Match` the request's `row_version`, in one Unit of Work:

1. `identity.authorize`, then the Opportunity's Estimate lock (`estimates.lock_for_review`),
   then the request `for_update` (404 unless it is the Opportunity's).
2. The actor: the request's current reviewer, still holding the review type's role (from
   the token), else 403 `reviewer_not_authorized`; the version's author approving is 403
   `self_approval_forbidden`. A decision on a superseded version is 409
   `estimate_version_superseded`. A Challenge (Story 9.5), a missing reason (every decision but
   Approve) or a reason over 1,000 characters is 422.
3. The state: only a `pending` request (409 `review_request_not_pending`); then the
   `If-Match` check (428/412, "Changed by {name} since you opened it.").
4. An escalation's target must hold the type's role (422 `reviewer_not_authorized_for_type`),
   not be the version's author (422 `author_cannot_review`) nor the current reviewer (422),
   and have no pending request of that type on the same target (409
   `review_request_duplicate`). Nothing is written on any error.
5. Appends the decision (with the request's target version), then:
   - `approved`: the request is `approved`; once every non-cancelled request counting towards
     its Estimate Version is approved, an `in_review` version becomes `approved`.
   - `rejected`: the request is `rejected` and an `in_review` version `rejected`.
   - `evidence_requested`, `alternative_requested`: the request stays `pending`.
   - `escalated`: the request stays `pending` with the new reviewer, who gets read access
     and a `review_requested` Inbox item (key `review:{id}:escalated:{decision_id}`).

   Every decision bumps the request's `row_version`. The previous reviewer loses read access
   once they have no pending request left on the Opportunity. Then
   `reviews.review_decision.recorded` is traced.

**Panel** (anyone who can read the Opportunity): the request, its decisions, what the
caller may do, the escalation candidates and the target (an Estimate Version with its diff
against the version before, or an Assessment at its version).
"""

from uuid import UUID

from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.public import ReviewableVersion, VersionStatus
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.notifications.application.public import NotificationKind
from app.modules.opportunities.application import public as opportunities
from app.modules.reviews.adapters import repository as repo
from app.modules.reviews.adapters.repository import RequestRecord
from app.modules.reviews.application.models import (
    RecordedDecision,
    ReviewDecisionCreate,
    ReviewPanel,
    ReviewPerson,
)
from app.modules.reviews.application.requests import (
    MAX_ROW_VERSION,
    REQUEST_NOT_FOUND,
    ROLE_FOR_TYPE,
    UNKNOWN_USER,
    author_detail,
    decision_people,
    decision_view,
    duplicate_detail,
    notify_reviewer,
    opportunity_title,
    request_views,
    superseded_detail,
    target_labels,
    wrong_role_detail,
)
from app.modules.reviews.domain.decisions import (
    RECORDABLE,
    Decision,
    clean_decision_reason,
    status_after,
)
from app.modules.reviews.domain.requests import (
    REASON_MAX,
    SUBJECT_TYPE,
    RequestStatus,
    ReviewType,
    TargetKind,
    transition,
)
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    AuthorCannotReviewError,
    EstimateVersionSupersededError,
    NotFoundError,
    ReviewerNotAuthorizedError,
    ReviewerNotAuthorizedForTypeError,
    ReviewRequestDuplicateError,
    ReviewRequestNotPendingError,
    RowVersionMismatchError,
    SelfApprovalForbiddenError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import ReviewsReviewDecisionRecorded
from app.platform.uow import UnitOfWork

NOT_REVIEWER = "Only this Review Request's reviewer, holding its review role, can decide it."
NOT_PENDING = "Only a pending Review Request can be decided."
REASON_RULE = f"Give a reason of 1 to {REASON_MAX:,} characters."
APPROVE_REASON_RULE = f"The reason can be at most {REASON_MAX:,} characters."
CHALLENGE_LATER = "Challenge arrives with Story 9.5."
ESCALATE_TARGET = "Choose who to escalate to."
NOT_ESCALATING = "Only an escalation names who it goes to."
ESCALATE_SELF = "Escalate to another reviewer, not the current one."
SOMEONE_ELSE = "someone else"
_log = get_logger(__name__)


def self_approval_detail(version: ReviewableVersion) -> str:
    """E.g. "You authored v3, so you can't approve it."."""
    return f"You authored v{version.version}, so you can't approve it."


def changed_detail(name: str) -> str:
    return f"Changed by {name} since you opened it."


def _is_author(version: ReviewableVersion | None, user_id: UUID | None) -> bool:
    return version is not None and user_id is not None and version.created_by == user_id


def _holds_role(actor: Principal, record: RequestRecord) -> bool:
    return ROLE_FOR_TYPE[ReviewType(record.review_type)] in actor.roles


def _is_reviewer(actor: Principal, record: RequestRecord) -> bool:
    return actor.user_id is not None and actor.user_id == record.reviewer_id


async def _stale(uow: UnitOfWork, record: RequestRecord) -> RowVersionMismatchError:
    latest = (await repo.latest_decisions(uow, [record.id])).get(record.id)
    name = SOMEONE_ELSE
    if latest is not None:
        name = (await identity.user_names(uow, {latest.decided_by})).get(
            latest.decided_by, SOMEONE_ELSE
        )
    return RowVersionMismatchError(changed_detail(name))


async def _check_if_match(uow: UnitOfWork, if_match: str | None, record: RequestRecord) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or record.row_version != expected:
        raise await _stale(uow, record)
    return expected


def _clean_reason(body: ReviewDecisionCreate) -> str | None:
    if body.decision not in RECORDABLE:
        raise UnprocessableError(CHALLENGE_LATER)
    try:
        return clean_decision_reason(body.decision, body.reason)
    except ValueError:
        rule = APPROVE_REASON_RULE if body.decision is Decision.APPROVED else REASON_RULE
        raise UnprocessableError(rule) from None


async def _check_escalation(
    uow: UnitOfWork,
    body: ReviewDecisionCreate,
    record: RequestRecord,
    version: ReviewableVersion | None,
) -> UUID | None:
    if body.decision is not Decision.ESCALATED:
        if body.escalated_to is not None:
            raise UnprocessableError(NOT_ESCALATING)
        return None
    target = body.escalated_to
    if target is None:
        raise UnprocessableError(ESCALATE_TARGET)
    if target == record.reviewer_id:
        raise UnprocessableError(ESCALATE_SELF)
    if version is not None and version.created_by == target:
        raise AuthorCannotReviewError(author_detail(version))
    review_type = ReviewType(record.review_type)
    if not await identity.users_with_role(uow, {target}, ROLE_FOR_TYPE[review_type]):
        names = await identity.user_names(uow, {target})
        raise ReviewerNotAuthorizedForTypeError(
            wrong_role_detail(review_type, [names.get(target, UNKNOWN_USER)])
        )
    duplicates = await repo.pending_duplicates(
        uow,
        [
            repo.NewRequest(
                id=record.id,
                review_type=record.review_type,
                target_kind=record.target_kind,
                target_id=record.target_id,
                target_version=record.target_version,
                reviewer_id=target,
            )
        ],
    )
    if duplicates:
        names = await identity.user_names(uow, {target})
        raise ReviewRequestDuplicateError(
            duplicate_detail([names.get(target, UNKNOWN_USER)], review_type)
        )
    return target


async def decide(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    request_id: UUID,
    body: ReviewDecisionCreate,
    if_match: str | None,
) -> RecordedDecision:
    """`reviews.decide`: record a Review Decision (module docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.REVIEW_REQUEST_DECIDE, resource)
    await estimates.lock_for_review(uow, opportunity_id)
    record = await repo.get(uow, request_id, for_update=True)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(REQUEST_NOT_FOUND)
    if not _is_reviewer(actor, record) or not _holds_role(actor, record):
        raise ReviewerNotAuthorizedError(NOT_REVIEWER)
    version = await estimates.reviewable_version(uow, record.estimate_version_id)
    if version is not None and version.status == VersionStatus.SUPERSEDED:
        raise EstimateVersionSupersededError(superseded_detail(version))
    if body.decision is Decision.APPROVED and _is_author(version, actor.user_id):
        assert version is not None
        raise SelfApprovalForbiddenError(self_approval_detail(version))
    reason = _clean_reason(body)
    if record.status != RequestStatus.PENDING:
        raise ReviewRequestNotPendingError(NOT_PENDING)
    expected = await _check_if_match(uow, if_match, record)
    escalated_to = await _check_escalation(uow, body, record, version)
    decider = record.reviewer_id

    decision = await repo.insert_decision(
        uow,
        decision_id=new_id(),
        review_request_id=record.id,
        decision=body.decision.value,
        reason=reason,
        decided_by=decider,
        target_version=record.target_version,
        escalated_to=escalated_to,
    )
    status = status_after(body.decision)
    if status is not None:
        updated = await repo.set_status(
            uow,
            record.id,
            from_status=RequestStatus.PENDING.value,
            to_status=transition(RequestStatus(record.status), status).value,
            expected_row_version=expected,
        )
    elif escalated_to is not None:
        updated = await repo.reassign(
            uow, record.id, reviewer_id=escalated_to, expected_row_version=expected
        )
    else:
        updated = await repo.bump(uow, record.id, expected_row_version=expected)
    if updated is None:  # pragma: no cover - the row lock serialises changes
        raise await _stale(uow, record)

    version_status = version.status if version is not None else None
    if body.decision is Decision.APPROVED and await repo.all_approved(
        uow, record.estimate_version_id
    ):
        moved = await estimates.mark_approved(uow, record.estimate_version_id, actor=actor.actor)
        version_status = moved.status if moved is not None else version_status
    elif body.decision is Decision.REJECTED:
        moved = await estimates.mark_rejected(uow, record.estimate_version_id, actor=actor.actor)
        version_status = moved.status if moved is not None else version_status
    if escalated_to is not None:
        await opportunities.grant_reviewer_access(
            uow, opportunity_id, escalated_to, actor=actor.actor
        )
    if status is not None or escalated_to is not None:
        await opportunities.revoke_reviewer_access(
            uow,
            opportunity_id,
            decider,
            has_pending=await repo.has_pending_for_reviewer(uow, opportunity_id, decider),
            actor=actor.actor,
        )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ReviewsReviewDecisionRecorded(
            request_id=str(record.id),
            decision_id=str(decision.id),
            decision=body.decision.value,
            reason=reason,
            target_kind=record.target_kind,
            target_id=str(record.target_id),
            target_version=record.target_version,
            escalated_to=None if escalated_to is None else str(escalated_to),
        ),
        subject_type=SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=opportunity_id,
        subject_version=updated.row_version,
    )
    if escalated_to is not None:
        labels = await target_labels(uow, [updated])
        await notify_reviewer(
            uow,
            kind=NotificationKind.REVIEW_REQUESTED,
            request_id=updated.id,
            reviewer_id=escalated_to,
            row_version=updated.row_version,
            target_label=labels[updated.id],
            opportunity_id=opportunity_id,
            title=await opportunity_title(uow, opportunity_id),
            dedupe_key=f"review:{updated.id}:escalated:{decision.id}",
        )
    _log.info(
        "reviews.review_decision_recorded",
        extra={
            "opportunity_id": str(opportunity_id),
            "request_id": str(record.id),
            "decision": body.decision.value,
            "actor_id": actor.actor.id,
        },
    )
    (view,) = await request_views(uow, actor, resource, [updated])
    names = await identity.user_names(uow, decision_people([decision]))
    return RecordedDecision(
        decision=decision_view(decision, names),
        request=view,
        version_status="" if version_status is None else version_status.value,
    )


# --- the panel ------------------------------------------------------------------------------


def _may_decide(
    actor: Principal,
    resource: Resource,
    record: RequestRecord,
    version: ReviewableVersion | None,
) -> bool:
    return (
        record.status == RequestStatus.PENDING
        and version is not None
        and version.status != VersionStatus.SUPERSEDED
        and _is_reviewer(actor, record)
        and _holds_role(actor, record)
        and identity.can(actor, Action.REVIEW_REQUEST_DECIDE, resource)
    )


async def _candidates(
    uow: UnitOfWork, record: RequestRecord, version: ReviewableVersion | None
) -> list[ReviewPerson]:
    exclude = {record.reviewer_id}
    if version is not None and version.created_by is not None:
        exclude.add(version.created_by)
    found = await identity.search_users_with_role(
        uow,
        ROLE_FOR_TYPE[ReviewType(record.review_type)],
        "",
        limit=identity.SEARCH_MAX_LIMIT,
        exclude=exclude,
    )
    return [ReviewPerson(id=u.id, name=u.name) for u in found.items]


async def review_panel(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, request_id: UUID
) -> ReviewPanel:
    """The review panel of one Review Request (module docstring). Anyone who can read the
    Opportunity; 404 for a request that isn't the Opportunity's."""
    # Imported here: assessments imports estimates' public API, which reads this module's
    # public API lazily for the blockers.
    from app.modules.assessments.application import public as assessments

    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    record = await repo.get(uow, request_id)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(REQUEST_NOT_FOUND)
    version = await estimates.reviewable_version(uow, record.estimate_version_id)
    (view,) = await request_views(uow, actor, resource, [record])
    decisions = await repo.decisions_of(uow, record.id)
    names = await identity.user_names(uow, decision_people(decisions))
    can_decide = _may_decide(actor, resource, record, version)
    author = _is_author(version, actor.user_id)
    estimate = diff = assessment = None
    if record.target_kind == TargetKind.ESTIMATE_VERSION:
        estimate = await estimates.version_detail(uow, record.target_id)
        diff = await estimates.compare_versions(uow, record.target_id)
    else:
        assessment = await assessments.assessment_at(uow, record.target_id, record.target_version)
    return ReviewPanel(
        request=view,
        opportunity_title=await opportunity_title(uow, opportunity_id),
        decisions=[decision_view(d, names) for d in decisions],
        version_status="" if version is None else version.status.value,
        superseded_by=None if version is None else version.superseded_by_version,
        can_decide=can_decide,
        can_approve=can_decide and not author,
        approve_blocked_reason=self_approval_detail(version)
        if can_decide and author and version is not None
        else None,
        escalation_candidates=await _candidates(uow, record, version) if can_decide else [],
        estimate=estimate,
        diff=diff,
        assessment=assessment,
    )
