"""Submitting an Estimate Version (Story 8.6; FR-14, FR-34).

`submit_version` (`estimates.estimate_version.submit`: the owner and collaborators except
sales representatives; other readers 403, everyone else the Opportunity's 404), with
`If-Match` the version's `row_version` (428 without, 412 when stale):

1. Takes the Opportunity's draft lock, then its Assumption lock (the order Accept takes
   them), so no accept, conversion or re-draft runs alongside.
2. 404 unless the version is one of the Opportunity's; 409 `estimate_version_not_draft`
   unless it is the `draft`; then the `If-Match` check.
3. Re-runs `get_submission_blockers` in this Unit of Work: anything in `to_submit` is 409
   `estimate_version_blocked` with the blockers in the problem body, and nothing changes.
4. Otherwise the version becomes `submitted`; the Opportunity's earlier `submitted` versions
   become `superseded`, each traced `estimates.estimate_version.superseded`; then
   `estimates.estimate_version.submitted` (ids and counts only).
5. Story 9.4: for each superseded version, `reviews.public.supersede_open_requests` in this
   Unit of Work: its pending and challenged Review Requests become `superseded` (and a request
   linked to one goes to the new version when the author's reply named it as the
   alternative, which moves the new version to `in_review`).

Lines and Assumptions of a submitted version stay immutable through the existing not-draft
errors (`line_edits`, `assumptions`).
"""

from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.application.blockers import get_submission_blockers
from app.modules.estimates.application.line_edits import not_draft_detail
from app.modules.estimates.application.models import SubmittedVersion
from app.modules.estimates.domain.estimates import VERSION_SUBJECT_TYPE, VersionStatus
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    EstimateVersionBlockedError,
    EstimateVersionNotDraftError,
    NotFoundError,
    RowVersionMismatchError,
)
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    EstimatesEstimateVersionSubmitted,
    EstimatesEstimateVersionSuperseded,
)
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Estimate Version with this id."
STALE_DETAIL = "The Estimate changed since you opened it. Reload and try again."
_log = get_logger(__name__)


def blocked_detail(count: int) -> str:
    """The 409's sentence, e.g. "Resolve 3 blockers before you can submit."."""
    noun = "blocker" if count == 1 else "blockers"
    return f"Resolve {count} {noun} before you can submit."


async def submit_version(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    version_id: UUID,
    if_match: str | None,
) -> SubmittedVersion:
    """Submit the Opportunity's draft Estimate Version (module docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ESTIMATE_VERSION_SUBMIT, resource)
    await repo.lock_opportunity(uow, opportunity_id)
    await repo.lock_assumptions(uow, opportunity_id)
    version = await repo.get_version(uow, version_id, for_update=True)
    if version is None or version.opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    if version.status != VersionStatus.DRAFT:
        raise EstimateVersionNotDraftError(not_draft_detail(version.status))
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or version.row_version != expected:
        raise RowVersionMismatchError(STALE_DETAIL)

    blockers = await get_submission_blockers(uow, version_id)
    if blockers.to_submit:
        _log.info(
            "estimates.version_submit_blocked",
            extra={
                "opportunity_id": str(opportunity_id),
                "version_id": str(version_id),
                "blocker_count": len(blockers.to_submit),
            },
        )
        raise EstimateVersionBlockedError(
            blocked_detail(len(blockers.to_submit)), blockers=blockers.model_dump(mode="json")
        )

    submitted = await repo.submit_version(uow, version_id, expected_row_version=expected)
    if submitted is None:  # pragma: no cover - the draft lock serialises version changes
        raise RowVersionMismatchError(STALE_DETAIL)
    superseded = await repo.supersede_submitted(uow, opportunity_id, keep=version_id)
    for old in superseded:
        await trace.append(
            uow,
            actor=actor.actor,
            payload=EstimatesEstimateVersionSuperseded(
                version_id=str(old.id),
                version=old.version,
                superseded_by_version_id=str(submitted.id),
                superseded_by_version=submitted.version,
            ),
            subject_type=VERSION_SUBJECT_TYPE,
            subject_id=old.id,
            opportunity_id=opportunity_id,
            subject_version=old.row_version,
        )
    # Imported here: reviews imports estimates' public API, which imports this module.
    from app.modules.reviews.application import public as reviews

    for old in superseded:
        await reviews.supersede_open_requests(uow, old.id, submitted.id, actor=actor.actor)
    line_count = len(await repo.lines_of(uow, version_id))
    assumption_count = len(await repo.assumptions_of(uow, version_id))
    await trace.append(
        uow,
        actor=actor.actor,
        payload=EstimatesEstimateVersionSubmitted(
            version_id=str(submitted.id),
            version=submitted.version,
            line_count=line_count,
            assumption_count=assumption_count,
            superseded_count=len(superseded),
        ),
        subject_type=VERSION_SUBJECT_TYPE,
        subject_id=submitted.id,
        opportunity_id=opportunity_id,
        subject_version=submitted.row_version,
    )
    _log.info(
        "estimates.version_submitted",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": str(version_id),
            "version": submitted.version,
            "actor_id": actor.actor.id,
            "superseded_count": len(superseded),
        },
    )
    # A linked request (Story 9.4) may have moved it on to `in_review`.
    submitted = await repo.get_version(uow, version_id) or submitted
    return SubmittedVersion(
        id=str(submitted.id),
        version=submitted.version,
        status=VersionStatus(submitted.status),
        row_version=submitted.row_version,
        superseded_count=len(superseded),
    )
