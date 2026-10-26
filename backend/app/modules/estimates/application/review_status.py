"""An Estimate Version's review status (Story 9.1), for `reviews` through `public.py`.

`reviews` sends Review Requests for a `submitted` or `in_review` version and calls, in its own
command's Unit of Work (holding `lock_opportunity`):

- `mark_in_review`: `submitted` → `in_review` (traced `estimates.estimate_version.review_started`);
  an `in_review` version stays as it is.
- `mark_submitted_from_review`: `in_review` → `submitted` once its last pending request is
  cancelled (traced `estimates.estimate_version.review_ended`).
- Story 9.3: `mark_approved`: `in_review` → `approved` once every non-cancelled request is
  approved (traced `estimates.estimate_version.approved`); `mark_rejected`: `in_review` →
  `rejected` when a reviewer rejects (traced `estimates.estimate_version.rejected`). Either
  leaves a version in any other status as it is.

`reviewable_version` reads what the review rules need: the status, the `row_version`
(`If-Match`), the author (`created_by`, null when unknown) and, for a superseded version, the
number of the version that replaced it. No authorization here.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import VersionRecord
from app.modules.estimates.domain.estimates import VERSION_SUBJECT_TYPE, VersionStatus
from app.platform import trace
from app.platform.actor import Actor
from app.platform.trace.catalogue import (
    EstimatesEstimateVersionApproved,
    EstimatesEstimateVersionRejected,
    EstimatesEstimateVersionReviewEnded,
    EstimatesEstimateVersionReviewStarted,
)
from app.platform.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class ReviewableVersion:
    """An Estimate Version as the review rules see it."""

    id: UUID
    opportunity_id: UUID
    version: int
    status: VersionStatus
    row_version: int
    created_by: UUID | None
    submitted_at: datetime | None
    superseded_by_version: int | None = None
    """For a superseded version, the number of the first later version submitted (Story 9.4)
    when it was itself submitted, else the Opportunity's current (else latest) version."""


async def _view(uow: UnitOfWork, record: VersionRecord) -> ReviewableVersion:
    status = VersionStatus(record.status)
    replaced_by: int | None = None
    if status == VersionStatus.SUPERSEDED and record.submitted_at is not None:
        # Story 9.4: a submitted version is superseded by the next one submitted, whatever
        # drafts came after.
        replaced_by = await repo.first_submitted_after(uow, record.opportunity_id, record.version)
    if status == VersionStatus.SUPERSEDED and replaced_by is None:
        current = await repo.current_version(uow, record.opportunity_id)
        replaced_by = (
            current.version
            if current is not None
            else await repo.latest_version_number(uow, record.opportunity_id)
        )
    return ReviewableVersion(
        id=record.id,
        opportunity_id=record.opportunity_id,
        version=record.version,
        status=status,
        row_version=record.row_version,
        created_by=record.created_by,
        submitted_at=record.submitted_at,
        superseded_by_version=replaced_by,
    )


async def reviewable_version(uow: UnitOfWork, version_id: UUID) -> ReviewableVersion | None:
    """The Estimate Version, or None when there is none with this id."""
    record = await repo.get_version(uow, version_id)
    return None if record is None else await _view(uow, record)


async def current_reviewable_version(
    uow: UnitOfWork, opportunity_id: UUID
) -> ReviewableVersion | None:
    """The Opportunity's current Estimate Version (its draft, else its latest submitted or
    in-review one), or None before the first."""
    record = await repo.current_version(uow, opportunity_id)
    return None if record is None else await _view(uow, record)


async def lock_opportunity(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Take the Opportunity's Estimate lock until commit (the one submit and drafting take),
    so a Review Request and a version change never interleave."""
    await repo.lock_opportunity(uow, opportunity_id)


async def _trace(uow: UnitOfWork, actor: Actor, record: VersionRecord, *, started: bool) -> None:
    payload = (
        EstimatesEstimateVersionReviewStarted if started else EstimatesEstimateVersionReviewEnded
    )(version_id=str(record.id), version=record.version)
    await trace.append(
        uow,
        actor=actor,
        payload=payload,
        subject_type=VERSION_SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=record.opportunity_id,
        subject_version=record.row_version,
    )


async def mark_in_review(uow: UnitOfWork, version_id: UUID, *, actor: Actor) -> ReviewableVersion:
    """Move a `submitted` version to `in_review`; an `in_review` one is returned as it is.
    Raises `LookupError` for an unknown version and `ValueError` for any other status (the
    caller has checked it)."""
    record = await repo.get_version(uow, version_id)
    if record is None:
        raise LookupError(f"No Estimate Version {version_id}")
    if record.status == VersionStatus.IN_REVIEW:
        return await _view(uow, record)
    if record.status != VersionStatus.SUBMITTED:
        raise ValueError(f"Estimate Version {version_id} is {record.status}")
    moved = await repo.move_status(
        uow,
        version_id,
        from_status=VersionStatus.SUBMITTED.value,
        to_status=VersionStatus.IN_REVIEW.value,
    )
    assert moved is not None  # the caller holds the Opportunity's lock
    await _trace(uow, actor, moved, started=True)
    return await _view(uow, moved)


async def mark_submitted_from_review(
    uow: UnitOfWork, version_id: UUID, *, actor: Actor
) -> ReviewableVersion | None:
    """Move an `in_review` version back to `submitted` (its last pending Review Request was
    cancelled); None, and no change, when it isn't `in_review`."""
    moved = await repo.move_status(
        uow,
        version_id,
        from_status=VersionStatus.IN_REVIEW.value,
        to_status=VersionStatus.SUBMITTED.value,
    )
    if moved is None:
        return None
    await _trace(uow, actor, moved, started=False)
    return await _view(uow, moved)


async def _move_from_review(
    uow: UnitOfWork, version_id: UUID, to_status: VersionStatus, *, actor: Actor
) -> ReviewableVersion | None:
    moved = await repo.move_status(
        uow, version_id, from_status=VersionStatus.IN_REVIEW.value, to_status=to_status.value
    )
    if moved is None:
        return None
    approved = to_status == VersionStatus.APPROVED
    payload = (EstimatesEstimateVersionApproved if approved else EstimatesEstimateVersionRejected)(
        version_id=str(moved.id), version=moved.version
    )
    await trace.append(
        uow,
        actor=actor,
        payload=payload,
        subject_type=VERSION_SUBJECT_TYPE,
        subject_id=moved.id,
        opportunity_id=moved.opportunity_id,
        subject_version=moved.row_version,
    )
    return await _view(uow, moved)


async def mark_approved(
    uow: UnitOfWork, version_id: UUID, *, actor: Actor
) -> ReviewableVersion | None:
    """Story 9.3: move an `in_review` version to `approved` (the caller checked that every
    non-cancelled Review Request counting towards it is approved); None, and no change, when
    it isn't `in_review`."""
    return await _move_from_review(uow, version_id, VersionStatus.APPROVED, actor=actor)


async def mark_rejected(
    uow: UnitOfWork, version_id: UUID, *, actor: Actor
) -> ReviewableVersion | None:
    """Story 9.3: move an `in_review` version to `rejected` (a reviewer rejected a request
    counting towards it); None, and no change, when it isn't `in_review`."""
    return await _move_from_review(uow, version_id, VersionStatus.REJECTED, actor=actor)
