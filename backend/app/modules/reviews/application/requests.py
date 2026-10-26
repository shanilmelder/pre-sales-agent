"""Review Requests (Story 9.1; AD-28, FR-36).

**Create** (`reviews.review_request.create`: the Opportunity's owner and collaborators except
sales representatives; a reviewer collaborator or any other reader 403, everyone else the
Opportunity's 404), with `If-Match` the Estimate Version's `row_version`:

1. Takes the Opportunity's Estimate lock (`estimates.lock_for_review`, the lock submit
   takes), then reads the version: 404 unless it is the Opportunity's; 409
   `estimate_version_not_submitted` for a draft, `estimate_version_superseded` for a
   superseded one, `estimate_version_rejected` for a rejected one (Story 9.3); then the
   `If-Match` check (428/412).
2. The reviewers: the version's author (`created_by`; no check when unknown) is 422
   `author_cannot_review`; one who doesn't hold the review type's role is 422
   `reviewer_not_authorized_for_type`; the picked Assessments must be current at the version
   seen (422 otherwise).
3. One request per reviewer and picked Assessment (target the Assessment at its version), or
   one per reviewer with the Estimate Version as target when none is picked. A reviewer who
   already has a pending request of that type on the same target is 409
   `review_request_duplicate`. Nothing is written on any error.
4. Writes the requests, moves the version `submitted → in_review`
   (`estimates.mark_in_review`), shares the Opportunity read only with each reviewer
   (`opportunities.grant_reviewer_access`), then traces `reviews.review_request.created` per
   request and gives each reviewer a `review_requested` Inbox item per request (Story 9.2,
   key `review:{id}:requested`).

**Cancel** (`reviews.review_request.cancel`, and only the sender or the Opportunity's owner):
a pending request with a reason (1 to 1,000 characters) and `If-Match` its `row_version`
becomes `cancelled`; the reviewer loses access when they have no pending request left on the
Opportunity; `reviews.review_request.cancelled`, and a `review_cancelled` Inbox item for the
reviewer (Story 9.2, key `review:{id}:cancelled`); and the version goes back to `submitted`
when no pending request is left for it.

Logs and trace carry ids, types and lengths only, never the message or the reason.
"""

from collections.abc import Sequence
from uuid import UUID

from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.public import ReviewableVersion, VersionStatus
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import (
    Action,
    Principal,
    Resource,
    Role,
    UserSearchResult,
)
from app.modules.notifications.application import public as notifications
from app.modules.notifications.application.public import NotificationKind
from app.modules.opportunities.application import public as opportunities
from app.modules.reviews.adapters import repository as repo
from app.modules.reviews.adapters.repository import NewRequest, RequestRecord
from app.modules.reviews.application.models import (
    AssessmentOption,
    AssessmentRef,
    CreatedReviewRequests,
    OpenReviewRequest,
    ReviewPerson,
    ReviewRequestCancel,
    ReviewRequestCreate,
    ReviewRequestState,
    ReviewRequestsView,
    ReviewRequestView,
    ReviewTarget,
)
from app.modules.reviews.domain.requests import (
    MESSAGE_MAX,
    OPEN_STATUSES,
    REASON_MAX,
    SUBJECT_TYPE,
    RequestStatus,
    ReviewType,
    TargetKind,
    clean_message,
    clean_reason,
    transition,
)
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    AuthorCannotReviewError,
    EstimateVersionNotSubmittedError,
    EstimateVersionRejectedError,
    EstimateVersionSupersededError,
    ForbiddenError,
    NotFoundError,
    ReviewerNotAuthorizedForTypeError,
    ReviewRequestDuplicateError,
    ReviewRequestNotPendingError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import ReviewsReviewRequestCancelled, ReviewsReviewRequestCreated
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
ROLE_FOR_TYPE: dict[ReviewType, Role] = {
    ReviewType.ENGINEERING: Role.ENGINEERING_REVIEWER,
    ReviewType.PM: Role.PM_REVIEWER,
    ReviewType.SECURITY: Role.SECURITY_REVIEWER,
}
AGENT_NAMES = {"engineering_agent": "Engineering", "pm_agent": "PM", "security_agent": "Security"}
VERSION_NOT_FOUND = "No Estimate Version with this id."
REQUEST_NOT_FOUND = "No Review Request with this id."
NOT_SUBMITTED = "Submit this Estimate Version before requesting review"
STALE_VERSION = "The Estimate changed since you opened it. Reload and try again."
STALE_REQUEST = "This Review Request changed since you opened it. Reload and try again."
NOT_PENDING = "Only a pending Review Request can be cancelled."
NOT_SENDER = (
    "Only the person who sent this Review Request, or the Opportunity's owner, can cancel it."
)
MESSAGE_RULE = f"The message can be at most {MESSAGE_MAX:,} characters."
REASON_RULE = f"Give a reason of 1 to {REASON_MAX:,} characters."
DUPLICATE_REVIEWER = "Each reviewer can be named once."
UNKNOWN_USER = "Unknown user"
_log = get_logger(__name__)


def superseded_detail(version: ReviewableVersion) -> str:
    """The 409 sentence, e.g. "v2 is superseded by v3"."""
    newer = version.superseded_by_version
    return f"v{version.version} is superseded" + ("" if newer is None else f" by v{newer}")


def author_detail(version: ReviewableVersion) -> str:
    return f"The author of v{version.version} can't review it"


def wrong_role_detail(review_type: ReviewType, names: Sequence[str]) -> str:
    who = ", ".join(names)
    role = ROLE_FOR_TYPE[review_type].value.replace("_", " ")
    return f"{who} can't do this review: it needs the {role} role."


def duplicate_detail(names: Sequence[str], review_type: ReviewType) -> str:
    who = ", ".join(names)
    return f"{who} already has a pending {review_type.value} review of this."


def _check_reviewable(version: ReviewableVersion) -> None:
    if version.status in estimates.REVIEWABLE:
        return
    if version.status == VersionStatus.SUPERSEDED:
        raise EstimateVersionSupersededError(superseded_detail(version))
    if version.status.value == "rejected":  # pragma: no cover - the status arrives in 9.3
        raise EstimateVersionRejectedError(f"v{version.version} was rejected")
    raise EstimateVersionNotSubmittedError(NOT_SUBMITTED)


def _check_if_match(if_match: str | None, row_version: int, detail: str) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or row_version != expected:
        raise RowVersionMismatchError(detail)
    return expected


async def _version_of(uow: UnitOfWork, opportunity_id: UUID, version_id: UUID) -> ReviewableVersion:
    version = await estimates.reviewable_version(uow, version_id)
    if version is None or version.opportunity_id != opportunity_id:
        raise NotFoundError(VERSION_NOT_FOUND)
    return version


async def _current_assessments(uow: UnitOfWork, opportunity_id: UUID) -> list[AssessmentOption]:
    # Imported here: assessments imports estimates' public API, which reads this module's
    # public API lazily for the blockers.
    from app.modules.assessments.application import public as assessments

    return [
        AssessmentOption(
            id=str(s.assessment_id),
            agent=s.agent,
            version=s.version,
            label=f"{AGENT_NAMES.get(s.agent, s.agent)} Assessment v{s.version}",
        )
        for s in await assessments.current_assessment_snapshots(uow, opportunity_id)
    ]


async def _targets(
    uow: UnitOfWork, version: ReviewableVersion, refs: Sequence[AssessmentRef]
) -> list[tuple[TargetKind, UUID, int]]:
    if not refs:
        return [(TargetKind.ESTIMATE_VERSION, version.id, version.version)]
    current = {UUID(a.id): a for a in await _current_assessments(uow, version.opportunity_id)}
    targets: list[tuple[TargetKind, UUID, int]] = []
    for ref in dict.fromkeys((r.id, r.version) for r in refs):
        found = current.get(ref[0])
        if found is None or found.version != ref[1]:
            raise UnprocessableError(
                "An Assessment you picked changed or is no longer current. Reload and pick again."
            )
        targets.append((TargetKind.ASSESSMENT, ref[0], ref[1]))
    return targets


def _sender(actor: Principal) -> UUID:
    user_id = actor.user_id
    if user_id is None:
        raise ForbiddenError("Only a signed-in user can send a Review Request.")
    return user_id


async def create_review_request(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    version_id: UUID,
    review_type: ReviewType,
    reviewer_ids: Sequence[UUID],
    assessment_refs: Sequence[AssessmentRef],
    message: str | None,
    if_match: str | None,
) -> CreatedReviewRequests:
    """Send Review Requests (module docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.REVIEW_REQUEST_CREATE, resource)
    sender = _sender(actor)
    if len(set(reviewer_ids)) != len(reviewer_ids):
        raise UnprocessableError(DUPLICATE_REVIEWER)
    try:
        text = clean_message(message)
    except ValueError:
        raise UnprocessableError(MESSAGE_RULE) from None

    await estimates.lock_for_review(uow, opportunity_id)
    version = await _version_of(uow, opportunity_id, version_id)
    _check_reviewable(version)
    _check_if_match(if_match, version.row_version, STALE_VERSION)

    names = await identity.user_names(uow, set(reviewer_ids))
    if version.created_by is not None and version.created_by in reviewer_ids:
        raise AuthorCannotReviewError(author_detail(version))
    qualified = await identity.users_with_role(uow, set(reviewer_ids), ROLE_FOR_TYPE[review_type])
    unqualified = [r for r in reviewer_ids if r not in qualified]
    if unqualified:
        raise ReviewerNotAuthorizedForTypeError(
            wrong_role_detail(review_type, [names.get(r, UNKNOWN_USER) for r in unqualified])
        )
    targets = await _targets(uow, version, assessment_refs)
    candidates = [
        NewRequest(
            id=new_id(),
            review_type=review_type.value,
            target_kind=kind.value,
            target_id=target_id,
            target_version=target_version,
            reviewer_id=reviewer,
        )
        for reviewer in reviewer_ids
        for kind, target_id, target_version in targets
    ]
    duplicates = await repo.pending_duplicates(uow, candidates)
    if duplicates:
        who = list(dict.fromkeys(names.get(d.reviewer_id, UNKNOWN_USER) for d in duplicates))
        raise ReviewRequestDuplicateError(duplicate_detail(who, review_type))

    await repo.insert_requests(
        uow,
        opportunity_id=opportunity_id,
        estimate_version_id=version.id,
        requested_by=sender,
        message=text,
        requests=candidates,
    )
    marked = await estimates.mark_in_review(uow, version.id, actor=actor.actor)
    for reviewer in reviewer_ids:
        await opportunities.grant_reviewer_access(uow, opportunity_id, reviewer, actor=actor.actor)
    for c in candidates:
        await trace.append(
            uow,
            actor=actor.actor,
            payload=ReviewsReviewRequestCreated(
                request_id=str(c.id),
                review_type=review_type.value,
                target_kind=c.target_kind,
                target_id=str(c.target_id),
                target_version=c.target_version,
                estimate_version_id=str(version.id),
                reviewer_id=str(c.reviewer_id),
                message_length=len(text or ""),
            ),
            subject_type=SUBJECT_TYPE,
            subject_id=c.id,
            opportunity_id=opportunity_id,
            subject_version=1,
        )
    _log.info(
        "reviews.review_requests_created",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": str(version.id),
            "review_type": review_type.value,
            "request_count": len(candidates),
            "actor_id": actor.actor.id,
        },
    )
    records = await repo.of_ids(uow, [c.id for c in candidates])
    views = await _views(uow, actor, resource, records)
    title = await opportunity_title(uow, opportunity_id)
    for view in views:
        await _notify_view(
            uow, view, NotificationKind.REVIEW_REQUESTED, opportunity_id, title, "requested"
        )
    return CreatedReviewRequests(
        items=views, version_status=marked.status.value, version_row_version=marked.row_version
    )


async def create_from_body(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    body: ReviewRequestCreate,
    if_match: str | None,
) -> CreatedReviewRequests:
    return await create_review_request(
        uow,
        actor,
        opportunity_id,
        body.version_id,
        body.review_type,
        body.reviewer_ids,
        body.assessment_refs,
        body.message,
        if_match,
    )


async def cancel_review_request(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    request_id: UUID,
    body: ReviewRequestCancel,
    if_match: str | None,
) -> ReviewRequestView:
    """Cancel a pending Review Request (module docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.REVIEW_REQUEST_CANCEL, resource)
    await estimates.lock_for_review(uow, opportunity_id)
    record = await repo.get(uow, request_id, for_update=True)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(REQUEST_NOT_FOUND)
    user_id = actor.user_id
    if user_id is None or user_id not in (record.requested_by, resource.owner_id):
        raise ForbiddenError(NOT_SENDER)
    reason = clean_reason(body.reason)
    if reason is None:
        raise UnprocessableError(REASON_RULE)
    if record.status != RequestStatus.PENDING:
        raise ReviewRequestNotPendingError(NOT_PENDING)
    expected = _check_if_match(if_match, record.row_version, STALE_REQUEST)

    status = transition(RequestStatus(record.status), RequestStatus.CANCELLED)
    cancelled = await repo.set_status(
        uow,
        request_id,
        from_status=RequestStatus.PENDING.value,
        to_status=status.value,
        expected_row_version=expected,
        cancel_reason=reason,
    )
    if cancelled is None:  # pragma: no cover - the row lock serialises changes
        raise RowVersionMismatchError(STALE_REQUEST)
    await opportunities.revoke_reviewer_access(
        uow,
        opportunity_id,
        cancelled.reviewer_id,
        has_pending=await repo.has_pending_for_reviewer(uow, opportunity_id, cancelled.reviewer_id),
        actor=actor.actor,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ReviewsReviewRequestCancelled(
            request_id=str(cancelled.id),
            review_type=cancelled.review_type,
            target_kind=cancelled.target_kind,
            target_id=str(cancelled.target_id),
            target_version=cancelled.target_version,
            estimate_version_id=str(cancelled.estimate_version_id),
            reviewer_id=str(cancelled.reviewer_id),
            reason_length=len(reason),
        ),
        subject_type=SUBJECT_TYPE,
        subject_id=cancelled.id,
        opportunity_id=opportunity_id,
        subject_version=cancelled.row_version,
    )
    if not await repo.has_pending_for_version(uow, cancelled.estimate_version_id):
        await estimates.mark_submitted_from_review(
            uow, cancelled.estimate_version_id, actor=actor.actor
        )
    _log.info(
        "reviews.review_request_cancelled",
        extra={
            "opportunity_id": str(opportunity_id),
            "request_id": str(request_id),
            "actor_id": actor.actor.id,
        },
    )
    (view,) = await _views(uow, actor, resource, [cancelled])
    await _notify_view(
        uow,
        view,
        NotificationKind.REVIEW_CANCELLED,
        opportunity_id,
        await opportunity_title(uow, opportunity_id),
        "cancelled",
    )
    return view


# --- Inbox items (Story 9.2) ----------------------------------------------------------------

SUMMARY_HEAD: dict[NotificationKind, str] = {
    NotificationKind.REVIEW_REQUESTED: "Review: {target}",
    NotificationKind.REVIEW_REMINDER: "Reminder: review {target}",
    NotificationKind.REVIEW_CANCELLED: "Review cancelled: {target}",
}


def review_summary(kind: NotificationKind, target_label: str, title: str | None) -> str:
    """E.g. "Review: Estimate v3 — {Opportunity}": the target label and the Opportunity's
    title only, never the message or a reason."""
    head = SUMMARY_HEAD[kind].format(target=target_label)
    return f"{head} — {title}" if title else head


async def opportunity_title(uow: UnitOfWork, opportunity_id: UUID) -> str | None:
    return (await opportunities.opportunity_titles(uow, {opportunity_id})).get(opportunity_id)


async def notify_reviewer(
    uow: UnitOfWork,
    *,
    kind: NotificationKind,
    request_id: UUID,
    reviewer_id: UUID,
    row_version: int,
    target_label: str,
    opportunity_id: UUID,
    title: str | None,
    dedupe_key: str,
) -> bool:
    """The reviewer's Inbox item about the request; whether one was written."""
    return await notifications.notify(
        uow,
        recipient_id=reviewer_id,
        kind=kind,
        opportunity_id=opportunity_id,
        subject_type=SUBJECT_TYPE,
        subject_id=request_id,
        subject_version=row_version,
        summary=review_summary(kind, target_label, title),
        dedupe_key=dedupe_key,
    )


async def _notify_view(
    uow: UnitOfWork,
    view: ReviewRequestView,
    kind: NotificationKind,
    opportunity_id: UUID,
    title: str | None,
    key_suffix: str,
) -> None:
    await notify_reviewer(
        uow,
        kind=kind,
        request_id=UUID(view.id),
        reviewer_id=UUID(view.reviewer.id),
        row_version=view.row_version,
        target_label=view.target.label,
        opportunity_id=opportunity_id,
        title=title,
        dedupe_key=f"review:{view.id}:{key_suffix}",
    )


# --- reads ----------------------------------------------------------------------------------


def _may_cancel(actor: Principal, resource: Resource, record: RequestRecord) -> bool:
    user_id = actor.user_id
    return (
        record.status == RequestStatus.PENDING
        and user_id is not None
        and user_id in (record.requested_by, resource.owner_id)
        and identity.can(actor, Action.REVIEW_REQUEST_CANCEL, resource)
    )


async def target_labels(uow: UnitOfWork, records: Sequence[RequestRecord]) -> dict[UUID, str]:
    """Per request its target's label: "Estimate v3" or "Security Assessment v2"."""
    agents: dict[UUID, dict[UUID, str]] = {}
    for opportunity_id in {r.opportunity_id for r in records}:
        agents[opportunity_id] = {
            UUID(a.id): a.label.rsplit(" v", 1)[0]
            for a in await _current_assessments(uow, opportunity_id)
        }

    def label(r: RequestRecord) -> str:
        if r.target_kind == TargetKind.ESTIMATE_VERSION:
            return f"Estimate v{r.target_version}"
        name = agents[r.opportunity_id].get(r.target_id, "Assessment")
        return f"{name} v{r.target_version}"

    return {r.id: label(r) for r in records}


async def _views(
    uow: UnitOfWork, actor: Principal, resource: Resource, records: Sequence[RequestRecord]
) -> list[ReviewRequestView]:
    if not records:
        return []
    names = await identity.user_names(
        uow, {r.reviewer_id for r in records} | {r.requested_by for r in records}
    )
    labels = await target_labels(uow, records)
    numbers: dict[UUID, int] = {}
    for version_id in {r.estimate_version_id for r in records}:
        found = await estimates.reviewable_version(uow, version_id)
        numbers[version_id] = 0 if found is None else found.version

    return [
        ReviewRequestView(
            id=str(r.id),
            review_type=ReviewType(r.review_type),
            target=ReviewTarget(
                kind=TargetKind(r.target_kind),
                id=str(r.target_id),
                version=r.target_version,
                label=labels[r.id],
            ),
            estimate_version_id=str(r.estimate_version_id),
            estimate_version=numbers[r.estimate_version_id],
            reviewer=ReviewPerson(
                id=str(r.reviewer_id), name=names.get(r.reviewer_id, UNKNOWN_USER)
            ),
            requested_by=ReviewPerson(
                id=str(r.requested_by), name=names.get(r.requested_by, UNKNOWN_USER)
            ),
            message=r.message,
            status=RequestStatus(r.status),
            cancel_reason=r.cancel_reason,
            row_version=r.row_version,
            created_at=r.created_at,
            updated_at=r.updated_at,
            can_cancel=_may_cancel(actor, resource, r),
        )
        for r in records
    ]


async def list_review_requests(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, version_id: UUID | None
) -> ReviewRequestsView:
    """The Review Requests of `version_id` (default: the Opportunity's current Estimate
    Version). Anyone who can read the Opportunity."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    version = (
        await estimates.current_reviewable_version(uow, opportunity_id)
        if version_id is None
        else await _version_of(uow, opportunity_id, version_id)
    )
    if version is None:
        return ReviewRequestsView(
            version_id=None, version=None, items=[], assessments=[], can_create=False
        )
    records = await repo.of_version(uow, version.id)
    return ReviewRequestsView(
        version_id=str(version.id),
        version=version.version,
        items=await _views(uow, actor, resource, records),
        assessments=await _current_assessments(uow, opportunity_id),
        can_create=may_request_review(actor, resource, version.status),
    )


def may_request_review(actor: Principal, resource: Resource, status: VersionStatus) -> bool:
    """Whether the caller may send Review Requests for a version in `status` (the
    `can_request_review` flag)."""
    return status in estimates.REVIEWABLE and identity.can(
        actor, Action.REVIEW_REQUEST_CREATE, resource
    )


async def reviewer_candidates(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    review_type: ReviewType,
    q: str,
    version_id: UUID | None = None,
) -> UserSearchResult:
    """Users who hold the review type's role, minus the author of `version_id` (default: the
    current Estimate Version), whose name or email contains `q`. Callers need
    `reviews.review_request.create`."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.REVIEW_REQUEST_CREATE, resource)
    version = (
        await estimates.current_reviewable_version(uow, opportunity_id)
        if version_id is None
        else await _version_of(uow, opportunity_id, version_id)
    )
    author = None if version is None else version.created_by
    return await identity.search_users_with_role(
        uow, ROLE_FOR_TYPE[review_type], q, exclude={author} if author else set()
    )


async def list_open_requests(uow: UnitOfWork, version_id: UUID) -> list[OpenReviewRequest]:
    """`reviews.public.list_open_requests`: the pending, rejected and challenged requests
    counting towards the version, oldest first. No authorization: callers have checked that
    the actor may read the Opportunity."""
    records = await repo.of_version(uow, version_id, statuses=tuple(s.value for s in OPEN_STATUSES))
    names = await identity.user_names(uow, {r.reviewer_id for r in records})
    return [
        OpenReviewRequest(
            id=r.id,
            review_type=ReviewType(r.review_type),
            reviewer_id=r.reviewer_id,
            reviewer_name=names.get(r.reviewer_id, UNKNOWN_USER),
            status=RequestStatus(r.status),
            target_kind=TargetKind(r.target_kind),
            target_id=r.target_id,
            target_version=r.target_version,
            message=r.message,
            created_at=r.created_at,
        )
        for r in records
    ]


async def request_status(uow: UnitOfWork, request_id: UUID) -> ReviewRequestState | None:
    """`reviews.public.request_status` (Story 9.2: an Inbox item's subject): the request's
    status and sender, or None when unknown. No authorization."""
    record = await repo.get(uow, request_id)
    if record is None:
        return None
    return ReviewRequestState(
        id=record.id,
        status=RequestStatus(record.status),
        requested_by=record.requested_by,
        reviewer_id=record.reviewer_id,
    )
