"""Superseding open Review Requests when a newer Estimate Version is submitted (Story 9.4;
AD-28).

`supersede_open_requests(uow, old_version_id, new_version_id, actor=...)` runs inside
`estimates.submit_version`'s Unit of Work (which holds the Opportunity's Estimate lock), once
per version that submit superseded:

1. Every `pending` or `challenged` request counting towards the old version becomes
   `superseded` (its `row_version` bumped). Superseded requests get no reminders, and their
   approvals never count: approvals are counted per version.
2. A request whose latest reply naming an alternative named a version above the old one and
   at most the new one (the new version, or a draft it re-drafted) gets a linked request on
   the new version: same reviewer, review type, sender and message, with
   `linked_request_id` the original; the new version moves to `in_review`, the reviewer keeps
   read access, `reviews.review_request.created` is traced and the reviewer gets a
   `review_requested` Inbox item (key `review:{id}:requested`). It counts as one of the new
   version's requests. No link is made when the reviewer authored the new version.
3. One `reviews.review_request.superseded` per request (with the new version and any linked
   request); then each earlier reviewer loses read access once they have nothing pending.

No authorization: the caller authorized the submit. Logs carry ids and counts only.
"""

from uuid import UUID

from app.modules.estimates.application import public as estimates
from app.modules.notifications.application.public import NotificationKind
from app.modules.opportunities.application import public as opportunities
from app.modules.reviews.adapters import repository as repo
from app.modules.reviews.adapters.repository import NewRequest, RequestRecord
from app.modules.reviews.application.requests import (
    notify_reviewer,
    opportunity_title,
    target_labels,
)
from app.modules.reviews.domain.requests import (
    SUBJECT_TYPE,
    RequestStatus,
    TargetKind,
    transition,
)
from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    ReviewsReviewRequestCreated,
    ReviewsReviewRequestSuperseded,
)
from app.platform.uow import UnitOfWork

SUPERSEDABLE = (RequestStatus.PENDING.value, RequestStatus.CHALLENGED.value)
_log = get_logger(__name__)


async def _link(
    uow: UnitOfWork, original: RequestRecord, new: estimates.ReviewableVersion
) -> NewRequest | None:
    if new.created_by is not None and new.created_by == original.reviewer_id:
        return None
    candidate = NewRequest(
        id=new_id(),
        review_type=original.review_type,
        target_kind=TargetKind.ESTIMATE_VERSION.value,
        target_id=new.id,
        target_version=new.version,
        reviewer_id=original.reviewer_id,
        linked_request_id=original.id,
    )
    if await repo.pending_duplicates(uow, [candidate]):  # pragma: no cover - a fresh version
        return None
    await repo.insert_requests(
        uow,
        opportunity_id=original.opportunity_id,
        estimate_version_id=new.id,
        requested_by=original.requested_by,
        message=original.message,
        requests=[candidate],
    )
    return candidate


async def supersede_open_requests(
    uow: UnitOfWork, old_version_id: UUID, new_version_id: UUID, *, actor: Actor
) -> int:
    """Supersede the old version's open requests, linking alternatives (module docstring);
    how many were superseded."""
    records = await repo.of_version(uow, old_version_id, statuses=SUPERSEDABLE)
    if not records:
        return 0
    new = await estimates.reviewable_version(uow, new_version_id)
    if new is None:  # pragma: no cover - the caller just submitted it
        raise LookupError(f"No Estimate Version {new_version_id}")
    opportunity_id = records[0].opportunity_id
    old = await estimates.reviewable_version(uow, old_version_id)
    old_number = 0 if old is None else old.version
    alternatives = await repo.latest_alternatives(uow, [r.id for r in records])
    numbers: dict[UUID, int] = {}
    for reply in alternatives.values():
        assert reply.alternative_version_id is not None
        found = await estimates.reviewable_version(uow, reply.alternative_version_id)
        if found is not None:
            numbers[reply.alternative_version_id] = found.version

    superseded: list[tuple[RequestRecord, RequestRecord]] = []
    for record in records:
        status = transition(RequestStatus(record.status), RequestStatus.SUPERSEDED)
        updated = await repo.set_status(
            uow,
            record.id,
            from_status=record.status,
            to_status=status.value,
            expected_row_version=record.row_version,
        )
        if updated is None:  # pragma: no cover - the Estimate lock serialises changes
            continue
        superseded.append((record, updated))

    linked: dict[UUID, NewRequest] = {}
    for record, _ in superseded:
        # The latest reply naming an alternative counts, even when that draft was re-drafted
        # before this submit (v4 offered, v5 submitted).
        latest = alternatives.get(record.id)
        number = (
            None
            if latest is None or latest.alternative_version_id is None
            else numbers.get(latest.alternative_version_id)
        )
        if number is None or not old_number < number <= new.version:
            continue
        made = await _link(uow, record, new)
        if made is not None:
            linked[record.id] = made

    if linked:
        await estimates.mark_in_review(uow, new.id, actor=actor)
        for made in linked.values():
            await opportunities.grant_reviewer_access(
                uow, opportunity_id, made.reviewer_id, actor=actor
            )
        for record, _ in superseded:
            made = linked.get(record.id)
            if made is None:
                continue
            await trace.append(
                uow,
                actor=actor,
                payload=ReviewsReviewRequestCreated(
                    request_id=str(made.id),
                    review_type=made.review_type,
                    target_kind=made.target_kind,
                    target_id=str(made.target_id),
                    target_version=made.target_version,
                    estimate_version_id=str(new.id),
                    reviewer_id=str(made.reviewer_id),
                    message_length=len(record.message or ""),
                    linked_request_id=str(record.id),
                ),
                subject_type=SUBJECT_TYPE,
                subject_id=made.id,
                opportunity_id=opportunity_id,
                subject_version=1,
            )

    for record, updated in superseded:
        made = linked.get(record.id)
        await trace.append(
            uow,
            actor=actor,
            payload=ReviewsReviewRequestSuperseded(
                request_id=str(record.id),
                from_status=record.status,
                estimate_version_id=str(old_version_id),
                superseded_by_version_id=str(new.id),
                superseded_by_version=new.version,
                reviewer_id=str(record.reviewer_id),
                linked_request_id=None if made is None else str(made.id),
            ),
            subject_type=SUBJECT_TYPE,
            subject_id=record.id,
            opportunity_id=opportunity_id,
            subject_version=updated.row_version,
        )

    for reviewer in dict.fromkeys(record.reviewer_id for record, _ in superseded):
        await opportunities.revoke_reviewer_access(
            uow,
            opportunity_id,
            reviewer,
            has_pending=await repo.has_pending_for_reviewer(uow, opportunity_id, reviewer),
            actor=actor,
        )

    if linked:
        created = await repo.of_ids(uow, [m.id for m in linked.values()])
        labels = await target_labels(uow, created)
        title = await opportunity_title(uow, opportunity_id)
        for request in created:
            await notify_reviewer(
                uow,
                kind=NotificationKind.REVIEW_REQUESTED,
                request_id=request.id,
                reviewer_id=request.reviewer_id,
                row_version=request.row_version,
                target_label=labels[request.id],
                opportunity_id=opportunity_id,
                title=title,
                dedupe_key=f"review:{request.id}:requested",
            )
    _log.info(
        "reviews.review_requests_superseded",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": str(old_version_id),
            "superseded_by_version_id": str(new.id),
            "superseded_count": len(superseded),
            "linked_count": len(linked),
        },
    )
    return len(superseded)
