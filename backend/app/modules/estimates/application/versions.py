"""A person's **New version** (Story 9.4; FR-37).

`create_version` (`estimates.estimate_version.create`: the owner and collaborators except
sales representatives; other readers 403, everyone else the Opportunity's 404), in one Unit of
Work:

1. Takes the Opportunity's draft lock, then its Assumption lock (the order submit takes them),
   and reads the base version: 404 unless it is one of the Opportunity's; 409
   `estimate_version_not_decided` unless it is `rejected` or `approved`, or `submitted` or
   `in_review` with a pending Review Request whose latest decision asks for an alternative
   (`reviews.public.alternative_requested`, read lazily); 409
   `estimate_draft_exists` while the Opportunity has a draft. A reason over 1,000 characters
   is 422.
2. Stores a new `draft` version (numbered one past the latest) through `store_version`, with a
   copy of the base's lines (section, title, hours, role mix, basis and the Requirements each
   covers) and the base's Assumptions, Risks and line edits carried, exactly as a re-draft
   carries them; traced `estimates.estimate_version.created` with the base and the reason, and
   followed by the version's Assumption proposals and the Red Team Review.

The base keeps its status (and its reviewers' decisions): only submitting the new draft
supersedes it. Logs and trace carry ids, numbers and counts only (and the person's reason in
the trace).
"""

from decimal import Decimal
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.application.draft import store_version
from app.modules.estimates.application.models import CreatedVersion
from app.modules.estimates.domain.estimates import (
    DECIDED,
    REVIEWABLE,
    EstimateRole,
    Section,
    ValidLine,
    VersionSource,
    VersionStatus,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform.errors import (
    EstimateDraftExistsError,
    EstimateVersionNotDecidedError,
    NotFoundError,
    UnprocessableError,
)
from app.platform.locks import opportunity_lock
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

NOT_FOUND_DETAIL = "No Estimate Version with this id."
REASON_MAX = 1000
REASON_RULE = f"The reason can be at most {REASON_MAX:,} characters."
_log = get_logger(__name__)


async def may_start_from(uow: UnitOfWork, version_id: UUID, status: VersionStatus) -> bool:
    """Whether a New version may start from a version in `status` (module docstring, step 1);
    the caller checks that no draft exists."""
    if status in DECIDED:
        return True
    if status not in REVIEWABLE:
        return False
    # Imported here: reviews imports estimates' public API, which imports this module.
    from app.modules.reviews.application import public as reviews

    return await reviews.alternative_requested(uow, version_id)


def not_decided_detail(version: int) -> str:
    return (
        f"v{version} is not rejected or approved, and no reviewer asked for an alternative, "
        "so a new version can't start from it."
    )


def draft_exists_detail(version: int) -> str:
    return f"Draft v{version} already exists. Work on it, or submit it first."


def _clean_reason(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if len(text) > REASON_MAX:
        raise UnprocessableError(REASON_RULE)
    return text or None


async def _copied_lines(uow: UnitOfWork, version_id: UUID) -> list[ValidLine[tuple[UUID, int]]]:
    lines = await repo.lines_of(uow, version_id)
    covers: dict[UUID, list[tuple[UUID, int]]] = {}
    for link in await repo.links_for(uow, [line.id for line in lines]):
        covers.setdefault(link.line_id, []).append((link.requirement_id, link.requirement_version))
    return [
        ValidLine(
            section=Section(line.section),
            title=line.title,
            covers=tuple(dict.fromkeys(covers.get(line.id, []))),
            effort_hours=Decimal(line.effort_hours),
            role_mix={EstimateRole(role): int(share) for role, share in line.role_mix.items()},
            basis=line.basis,
        )
        for line in lines
    ]


async def create_version(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    base_version_id: UUID,
    reason: str | None,
) -> CreatedVersion:
    """Start a new draft Estimate Version from a rejected or approved one (module
    docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ESTIMATE_VERSION_CREATE, resource)
    text = _clean_reason(reason)
    await opportunity_lock(uow, opportunity_id)
    base = await repo.get_version(uow, base_version_id, for_update=True)
    if base is None or base.opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    if not await may_start_from(uow, base.id, VersionStatus(base.status)):
        raise EstimateVersionNotDecidedError(not_decided_detail(base.version))
    draft = await repo.draft_version(uow, opportunity_id)
    if draft is not None:
        raise EstimateDraftExistsError(draft_exists_detail(draft.version))

    lines = await _copied_lines(uow, base.id)
    snapshots = await intake.active_requirement_snapshots(uow, opportunity_id)
    stored = await store_version(
        uow,
        opportunity_id,
        lines,
        active=[(s.id, s.version) for s in snapshots],
        dropped=0,
        requirement_count=len(snapshots),
        actor=actor.actor,
        source=VersionSource(base.source),
        created_by=actor.user_id,
        base=base,
        reason=text,
    )
    created = await repo.get_version(uow, stored.version_id)
    assert created is not None  # just stored
    _log.info(
        "estimates.version_created_from_base",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": str(created.id),
            "base_version_id": str(base.id),
            "line_count": len(lines),
            "actor_id": actor.actor.id,
        },
    )
    return CreatedVersion(
        id=str(created.id),
        version=created.version,
        status=VersionStatus(created.status),
        row_version=created.row_version,
        base_version_id=str(base.id),
        base_version=base.version,
    )
