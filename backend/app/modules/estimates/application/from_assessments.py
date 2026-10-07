"""The Estimate built from the specialist Assessments (Story 8.3).

`build_from_assessments` runs inside `assessments.finish_run`'s Unit of Work when a run
finishes with at least one task `succeeded` (and again when it finishes again after a task
retry), just before the Conflict detection, which therefore compares against this version.
No model call: the lines come from `domain.from_assessments.build_lines` over each agent's
current Assessment, one per active Requirement an agent sized. The version is stored with
`store_version`, exactly as an accepted model draft is (superseding the current draft,
carrying accepted Assumptions and line edits, trace, Assumption proposals and the Red Team
Review), with `source` `assessments`, `source_run_id` the run and the system as actor.

When no agent sized any active Requirement, nothing is stored and the current version stays.

Logs and trace carry ids and counts only, never Requirement or line text.
"""

from collections.abc import Sequence
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.application.draft import store_version
from app.modules.estimates.domain.estimates import VersionSource
from app.modules.estimates.domain.from_assessments import (
    ActiveRequirement,
    AgentSizing,
    build_lines,
)
from app.modules.intake.application import public as intake
from app.platform.actor import Actor
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

BUILD_FROM_ASSESSMENTS = "estimates.build_from_assessments"
_SYSTEM = Actor(type="system", id=BUILD_FROM_ASSESSMENTS)
_log = get_logger(__name__)


async def build_from_assessments(
    uow: UnitOfWork,
    opportunity_id: UUID,
    run_id: UUID,
    sizings: Sequence[AgentSizing],
) -> UUID | None:
    """Store a new `draft` Estimate Version from the agents' current Assessments (`sizings`)
    for the finished run; its id, or None when no agent sized any active Requirement."""
    ids = {"opportunity_id": str(opportunity_id), "run_id": str(run_id)}
    await repo.lock_opportunity(uow, opportunity_id)
    snapshots = await intake.active_requirement_snapshots(uow, opportunity_id)
    built = build_lines(
        [
            ActiveRequirement(
                id=s.id,
                version=s.version,
                number=s.number,
                classification=s.classification,
                text=s.text,
            )
            for s in snapshots
        ],
        sizings,
    )
    if not built.lines:
        _log.info(
            "estimates.assessments_version_skipped",
            extra={**ids, "requirement_count": len(snapshots), "agent_count": len(sizings)},
        )
        return None
    stored = await store_version(
        uow,
        opportunity_id,
        built.lines,
        active=[(s.id, s.version) for s in snapshots],
        dropped=0,
        requirement_count=len(snapshots),
        actor=_SYSTEM,
        uncovered_count=built.uncovered,
        source=VersionSource.ASSESSMENTS,
        source_run_id=run_id,
    )
    _log.info(
        "estimates.assessments_version_created",
        extra={**ids, "version_id": str(stored.version_id), **stored.created.model_dump()},
    )
    return stored.version_id
