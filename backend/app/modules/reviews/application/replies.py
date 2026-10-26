"""Replies to a reviewer's request for evidence or an alternative (Story 9.4; AD-28, FR-37).

**Reply** (`reviews.review_request.reply`: the Opportunity's owner and collaborators except
sales representatives, so never a reviewer collaborator; everyone else the Opportunity's
404), with `If-Match` the request's `row_version`, in one Unit of Work:

1. `identity.authorize`, the Opportunity's Estimate lock (`estimates.lock_for_review`), then
   the request `for_update` (404 unless it is the Opportunity's).
2. Only its sender or the Opportunity's owner, never its reviewer (403 otherwise); a blank
   message, or one over 2,000 characters, is 422.
3. The request must be `pending` on a version that isn't superseded (409
   `review_request_not_pending`) and its latest decision
   `evidence_requested` or `alternative_requested` (409 `review_reply_not_expected`); then the
   `If-Match` check (428/412, "Changed by {name} since you opened it.").
4. Every Evidence reference must resolve (`evidence.resolve_all`) and be this Opportunity's
   (`intake.foreign_evidence`), else 422 `evidence_unresolvable` naming it. An alternative is
   allowed only after `alternative_requested`, and must be this Opportunity's draft Estimate
   Version numbered above the one under review (422 otherwise).
5. Appends the reply, bumps the request's `row_version` (it stays `pending`), traces
   `reviews.review_request.replied` (the Evidence references, whether an alternative is named
   and the message's length, never its text) and gives the reviewer a `review_replied` Inbox
   item, "Reply on Estimate v3" (key `review:{id}:reply:{reply_id}`).

The alternative takes effect when that draft is submitted: `supersede_open_requests` then
creates the linked request on it (the hook is the only point where both requests exist in one
Unit of Work).
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.public import ReviewableVersion, VersionStatus
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.application import public as intake
from app.modules.notifications.application.public import NotificationKind
from app.modules.opportunities.application import public as opportunities
from app.modules.reviews.adapters import repository as repo
from app.modules.reviews.adapters.repository import ReplyRecord, RequestRecord
from app.modules.reviews.application.models import (
    RecordedReply,
    ReviewEvidence,
    ReviewPerson,
    ReviewReplyCreate,
    ReviewReplyView,
    VersionRef,
)
from app.modules.reviews.application.requests import (
    MAX_ROW_VERSION,
    REQUEST_NOT_FOUND,
    UNKNOWN_USER,
    notify_reviewer,
    opportunity_title,
    request_views,
    target_labels,
)
from app.modules.reviews.domain.decisions import Decision
from app.modules.reviews.domain.replies import (
    REPLY_MAX,
    clean_reply_message,
    may_link_alternative,
    may_reply,
)
from app.modules.reviews.domain.requests import SUBJECT_TYPE, RequestStatus
from app.platform import evidence, trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    EvidenceUnresolvableError,
    ForbiddenError,
    NotFoundError,
    ReviewReplyNotExpectedError,
    ReviewRequestNotPendingError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import ReplyEvidenceRef, ReviewsReviewRequestReplied
from app.platform.uow import UnitOfWork

NOT_AUTHOR = "Only the person who sent this Review Request, or the Opportunity's owner, can reply."
NOT_PENDING = "Only a pending Review Request can be replied to."
NOT_EXPECTED = (
    "The reviewer hasn't asked for evidence or an alternative, so there is nothing to reply to."
)
MESSAGE_RULE = f"Write a reply of 1 to {REPLY_MAX:,} characters."
NO_ALTERNATIVE = "Only a reply to a request for an alternative can link one."
BAD_ALTERNATIVE = (
    "The alternative must be this Opportunity's draft Estimate Version, newer than the one "
    "under review."
)
SOMEONE_ELSE = "someone else"
_log = get_logger(__name__)


def reply_summary(target_label: str) -> str:
    """The reviewer's Inbox item: "Reply on Estimate v3"."""
    return f"Reply on {target_label}"


def changed_detail(name: str) -> str:
    return f"Changed by {name} since you opened it."


async def latest_change_by(uow: UnitOfWork, record: RequestRecord) -> str:
    """Who last changed the request (its latest decision or reply), for the 412 sentence."""
    decision = (await repo.latest_decisions(uow, [record.id])).get(record.id)
    reply = (await repo.latest_replies(uow, [record.id])).get(record.id)
    who = None
    if decision is not None and (reply is None or decision.decided_at >= reply.replied_at):
        who = decision.decided_by
    elif reply is not None:
        who = reply.replied_by
    if who is None:
        return SOMEONE_ELSE
    return (await identity.user_names(uow, {who})).get(who, SOMEONE_ELSE)


type EvidenceKey = tuple[str, UUID, int | None]


def _key(row: dict[str, Any]) -> EvidenceKey:
    version = row.get("version")
    return (str(row["kind"]), UUID(str(row["id"])), version if isinstance(version, int) else None)


async def _check_evidence(uow: UnitOfWork, opportunity_id: UUID, body: ReviewReplyCreate) -> None:
    if not body.evidence:
        return
    await evidence.resolve_all(uow, body.evidence)
    foreign = await intake.foreign_evidence(uow, opportunity_id, body.evidence)
    if foreign is not None:
        raise EvidenceUnresolvableError(
            f"Evidence {evidence.describe(foreign)} does not resolve: "
            "it belongs to another Opportunity."
        )


async def _check_alternative(
    uow: UnitOfWork,
    body: ReviewReplyCreate,
    latest: Decision | None,
    version: ReviewableVersion | None,
    opportunity_id: UUID,
) -> UUID | None:
    if body.alternative_version_id is None:
        return None
    if not may_link_alternative(latest):
        raise UnprocessableError(NO_ALTERNATIVE)
    alternative = await estimates.reviewable_version(uow, body.alternative_version_id)
    if (
        alternative is None
        or version is None
        or alternative.opportunity_id != opportunity_id
        or alternative.status != VersionStatus.DRAFT
        or alternative.version <= version.version
    ):
        raise UnprocessableError(BAD_ALTERNATIVE)
    return alternative.id


async def reply_views(
    uow: UnitOfWork, opportunity_id: UUID, replies: Sequence[ReplyRecord]
) -> list[ReviewReplyView]:
    """The replies with their people's names, Evidence labels and alternative numbers."""
    if not replies:
        return []
    names = await identity.user_names(uow, {r.replied_by for r in replies})
    refs = list(dict.fromkeys(_key(e) for r in replies for e in r.evidence))
    labels = await intake.evidence_labels(uow, opportunity_id, refs)
    numbers: dict[UUID, int] = {}
    for version_id in {r.alternative_version_id for r in replies} - {None}:
        assert version_id is not None
        found = await estimates.reviewable_version(uow, version_id)
        if found is not None:
            numbers[version_id] = found.version

    def cited(e: dict[str, Any]) -> ReviewEvidence:
        kind, ref_id, version = key = _key(e)
        return ReviewEvidence(
            kind=kind, id=str(ref_id), version=version, label=labels.get(key, "Unknown")
        )

    return [
        ReviewReplyView(
            id=str(r.id),
            message=r.message,
            evidence=[cited(e) for e in r.evidence],
            alternative=None
            if r.alternative_version_id is None or r.alternative_version_id not in numbers
            else VersionRef(
                id=str(r.alternative_version_id), version=numbers[r.alternative_version_id]
            ),
            replied_by=ReviewPerson(
                id=str(r.replied_by), name=names.get(r.replied_by, UNKNOWN_USER)
            ),
            replied_at=r.replied_at,
        )
        for r in replies
    ]


async def reply(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    request_id: UUID,
    body: ReviewReplyCreate,
    if_match: str | None,
) -> RecordedReply:
    """`reviews.reply`: reply to the reviewer's request for evidence or an alternative
    (module docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.REVIEW_REQUEST_REPLY, resource)
    await estimates.lock_for_review(uow, opportunity_id)
    record = await repo.get(uow, request_id, for_update=True)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(REQUEST_NOT_FOUND)
    user_id = actor.user_id
    if (
        user_id is None
        or user_id not in (record.requested_by, resource.owner_id)
        or user_id == record.reviewer_id
    ):
        raise ForbiddenError(NOT_AUTHOR)
    try:
        message = clean_reply_message(body.message)
    except ValueError:
        raise UnprocessableError(MESSAGE_RULE) from None
    version = await estimates.reviewable_version(uow, record.estimate_version_id)
    if (
        record.status != RequestStatus.PENDING
        or version is None
        or version.status == VersionStatus.SUPERSEDED
    ):
        raise ReviewRequestNotPendingError(NOT_PENDING)
    found = (await repo.latest_decisions(uow, [record.id])).get(record.id)
    latest = None if found is None else Decision(found.decision)
    if not may_reply(latest):
        raise ReviewReplyNotExpectedError(NOT_EXPECTED)
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or record.row_version != expected:
        raise RowVersionMismatchError(changed_detail(await latest_change_by(uow, record)))
    await _check_evidence(uow, opportunity_id, body)
    alternative = await _check_alternative(uow, body, latest, version, opportunity_id)

    refs = list(dict.fromkeys((r.kind, r.id, r.version) for r in body.evidence))
    rows: list[dict[str, Any]] = [{"kind": k, "id": str(i), "version": v} for k, i, v in refs]
    stored = await repo.insert_reply(
        uow,
        reply_id=new_id(),
        review_request_id=record.id,
        message=message,
        evidence=rows,
        alternative_version_id=alternative,
        replied_by=user_id,
    )
    updated = await repo.bump(uow, record.id, expected_row_version=expected)
    if updated is None:  # pragma: no cover - the row lock serialises changes
        raise RowVersionMismatchError(changed_detail(SOMEONE_ELSE))
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ReviewsReviewRequestReplied(
            request_id=str(record.id),
            reply_id=str(stored.id),
            evidence=[ReplyEvidenceRef(kind=k, id=str(i), version=v) for k, i, v in refs],
            has_alternative=alternative is not None,
            alternative_version_id=None if alternative is None else str(alternative),
            message_length=len(message),
        ),
        subject_type=SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=opportunity_id,
        subject_version=updated.row_version,
    )
    labels = await target_labels(uow, [updated])
    await notify_reviewer(
        uow,
        kind=NotificationKind.REVIEW_REPLIED,
        request_id=updated.id,
        reviewer_id=updated.reviewer_id,
        row_version=updated.row_version,
        target_label=labels[updated.id],
        opportunity_id=opportunity_id,
        title=await opportunity_title(uow, opportunity_id),
        dedupe_key=f"review:{updated.id}:reply:{stored.id}",
        summary=reply_summary(labels[updated.id]),
    )
    _log.info(
        "reviews.review_request_replied",
        extra={
            "opportunity_id": str(opportunity_id),
            "request_id": str(record.id),
            "evidence_count": len(rows),
            "has_alternative": alternative is not None,
            "actor_id": actor.actor.id,
        },
    )
    (view,) = await request_views(uow, actor, resource, [updated])
    (reply_view,) = await reply_views(uow, opportunity_id, [stored])
    return RecordedReply(reply=reply_view, request=view)
