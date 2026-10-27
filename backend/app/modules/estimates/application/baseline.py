"""Setting the Baseline (Story 9.7; AD-26, FR-39, FR-62).

`set_baseline` (`estimates.baseline.set`: the owner and collaborators except sales
representatives; people only, so an agent or the system is 403 whatever its grants
(`HUMAN_ONLY_ACTIONS`); other readers 403, everyone else the Opportunity's 404), with
`If-Match` the version's `row_version` (428 without, 412 when stale), in one Unit of Work:

1. `identity.authorize`, then the Opportunity's shared lock (`platform.locks.opportunity_lock`),
   which review decisions, Finding overrides, Gap conversion and submit take too, so nothing
   the checks read changes alongside.
2. Loads the version (404 unless it is one of the Opportunity's), then the `If-Match` check.
3. With a Baseline already set, a version numbered at or below it, or one that isn't
   `approved`, is 409 `baseline_not_newer`.
4. Otherwise a version that isn't `approved`, or whose `to_baseline` blockers
   (`get_submission_blockers`, the same list the gate shows) aren't empty, is 409
   `baseline_blocked` with each blocker (by kind) in `blockers`.
5. Inserts the Baseline row (`previous_version_id`: the Baseline it replaces) and traces
   `estimates.baseline.set` with the version, the previous Baseline's version and the
   approvals behind it (`reviews.public.version_approvals`, read lazily).

Nothing is written on any error. A Baseline is never undone or removed: only a newer approved
version replaces it, and the replaced version stays `approved` (it only loses the marker).
"""

from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import BaselineRecord
from app.modules.estimates.application.blockers import get_submission_blockers
from app.modules.estimates.application.models import (
    BaselineApproval,
    BaselineRef,
    BaselineSet,
    VersionGate,
)
from app.modules.estimates.domain.estimates import VERSION_SUBJECT_TYPE, VersionStatus
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    BaselineBlockedError,
    BaselineNotNewerError,
    ForbiddenError,
    NotFoundError,
    RowVersionMismatchError,
)
from app.platform.ids import new_id
from app.platform.locks import opportunity_lock
from app.platform.logging import get_logger
from app.platform.trace.catalogue import BaselineApprover, EstimatesBaselineSet
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Estimate Version with this id."
STALE_DETAIL = "The Estimate changed since you opened it. Reload and try again."
NOT_NEWER_DETAIL = "Only a newer approved Estimate Version can replace the Baseline"
NOT_APPROVED_DETAIL = "Every requested review must approve v{version} first."
UNKNOWN_USER = "Unknown user"
_log = get_logger(__name__)


def blocked_detail(version: int, count: int, approved: bool) -> str:
    """The 409 `baseline_blocked` sentence."""
    if count == 0 and not approved:
        return NOT_APPROVED_DETAIL.format(version=version)
    noun = "blocker" if count == 1 else "blockers"
    return f"Resolve {count} {noun} before you can set the Baseline."


async def baseline_ref(uow: UnitOfWork, record: BaselineRecord | None) -> BaselineRef | None:
    """The Baseline as the Estimate shows it, or None."""
    if record is None:
        return None
    version = await repo.get_version(uow, record.estimate_version_id)
    assert version is not None  # a Baseline row keys an existing version
    names = await identity.user_names(uow, {record.set_by})
    return BaselineRef(
        version_id=str(version.id),
        version=version.version,
        set_at=record.set_at,
        set_by_name=names.get(record.set_by, UNKNOWN_USER),
    )


async def current_baseline_ref(uow: UnitOfWork, opportunity_id: UUID) -> BaselineRef | None:
    """The Opportunity's current Baseline, or None before the first. No authorization."""
    return await baseline_ref(uow, await repo.current_baseline(uow, opportunity_id))


async def set_baseline(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    version_id: UUID,
    if_match: str | None,
) -> BaselineSet:
    """`estimates.set_baseline`: set the approved version as the Baseline (module
    docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ESTIMATE_BASELINE_SET, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - HUMAN_ONLY_ACTIONS denies every non-person
        raise ForbiddenError("Only people can set the Baseline.")
    await opportunity_lock(uow, opportunity_id)
    version = await repo.get_version(uow, version_id, for_update=True)
    if version is None or version.opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or version.row_version != expected:
        raise RowVersionMismatchError(STALE_DETAIL)

    ids = {"opportunity_id": str(opportunity_id), "version_id": str(version_id)}
    approved = version.status == VersionStatus.APPROVED
    current = await repo.current_baseline(uow, opportunity_id)
    previous = None if current is None else await repo.get_version(uow, current.estimate_version_id)
    if previous is not None and (version.version <= previous.version or not approved):
        _log.info("estimates.baseline_not_newer", extra=ids)
        raise BaselineNotNewerError(NOT_NEWER_DETAIL)
    blockers = (await get_submission_blockers(uow, version_id)).to_baseline
    if not approved or blockers:
        _log.info("estimates.baseline_blocked", extra={**ids, "blocker_count": len(blockers)})
        raise BaselineBlockedError(
            blocked_detail(version.version, len(blockers), approved),
            blockers=[b.model_dump(mode="json") for b in blockers],
        )

    # Imported here: reviews imports estimates' public API, which imports this module.
    from app.modules.reviews.application import public as reviews

    approvals = await reviews.version_approvals(uow, version_id)
    stored = await repo.insert_baseline(
        uow,
        baseline_id=new_id(),
        opportunity_id=opportunity_id,
        estimate_version_id=version_id,
        previous_version_id=None if previous is None else previous.id,
        set_by=user_id,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=EstimatesBaselineSet(
            baseline_id=str(stored.id),
            version_id=str(version.id),
            version=version.version,
            previous_version_id=None if previous is None else str(previous.id),
            previous_version=None if previous is None else previous.version,
            approvers=[
                BaselineApprover(
                    user_id=str(a.decided_by or a.reviewer_id),
                    review_type=a.review_type.value,
                    decision_id=str(a.decision_id),
                )
                for a in approvals
                if a.decision_id is not None
            ],
        ),
        subject_type=VERSION_SUBJECT_TYPE,
        subject_id=version.id,
        opportunity_id=opportunity_id,
        subject_version=version.row_version,
    )
    _log.info(
        "estimates.baseline_set",
        extra={
            **ids,
            "version": version.version,
            "previous_version": None if previous is None else previous.version,
            "approver_count": len(approvals),
            "actor_id": actor.actor.id,
        },
    )
    ref = await baseline_ref(uow, stored)
    assert ref is not None
    return BaselineSet(
        version_id=ref.version_id,
        version=ref.version,
        set_at=ref.set_at,
        set_by_name=ref.set_by_name,
        previous_version_id=None if previous is None else str(previous.id),
        previous_version=None if previous is None else previous.version,
    )


async def version_gate(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, version_id: UUID
) -> VersionGate | None:
    """Story 9.7: the version's Set Baseline state (for the review panel), or None when it
    isn't one of the Opportunity's. The caller has checked that the actor may read the
    Opportunity."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    version = await repo.get_version(uow, version_id)
    if version is None or version.opportunity_id != opportunity_id:
        return None
    current = await repo.current_baseline(uow, opportunity_id)
    baseline = None if current is None else await repo.get_version(uow, current.estimate_version_id)
    return VersionGate(
        version_id=str(version.id),
        version=version.version,
        status=VersionStatus(version.status),
        row_version=version.row_version,
        is_baseline=current is not None and current.estimate_version_id == version.id,
        to_baseline=(await get_submission_blockers(uow, version_id)).to_baseline,
        can_set_baseline=identity.can(actor, Action.ESTIMATE_BASELINE_SET, resource),
        baseline_version=None if baseline is None else baseline.version,
    )


async def version_approvers(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, version_id: UUID
) -> list[BaselineApproval]:
    """Story 9.7: the Review Requests behind the version (non-cancelled, oldest first), each
    with who decided and when, for the Set Baseline dialog. Anyone who can read the
    Opportunity."""
    await opportunities.readable_resource(uow, actor, opportunity_id)
    version = await repo.get_version(uow, version_id)
    if version is None or version.opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    # Imported here for the reason given in `set_baseline`.
    from app.modules.reviews.application import public as reviews

    return [
        BaselineApproval(
            name=a.decided_by_name or a.reviewer_name,
            review_type=a.review_type.value,
            status=a.status.value,
            decided_at=a.decided_at,
            decision_id=None if a.decision_id is None else str(a.decision_id),
        )
        for a in await reviews.version_approvals(uow, version_id)
    ]
