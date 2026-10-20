"""What `conflicts` reads from `assessments` (Story 6.2): the current Assessments' Findings
for the Conflict Agent, each agent's current Assessment version, and a Finding's title and
kind for a position card.

`assessments` imports `conflicts` (its snapshots are `conflicts` DTOs), so the import here is
made at call time, when both modules are loaded; this is the only place `conflicts`' own
layers reach `assessments` (an `ignore_imports` entry of the import-linter contract)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.conflicts.domain.rules import AssessmentSnapshot
from app.modules.conflicts.domain.semantic import FindingSnapshot, FindingTitle
from app.platform.uow import UnitOfWork


async def current_findings(uow: UnitOfWork, opportunity_id: UUID) -> list[FindingSnapshot]:
    from app.modules.assessments.application import public as assessments

    return await assessments.current_finding_snapshots(uow, opportunity_id)


async def current_assessments(uow: UnitOfWork, opportunity_id: UUID) -> list[AssessmentSnapshot]:
    from app.modules.assessments.application import public as assessments

    return await assessments.current_assessment_snapshots(uow, opportunity_id)


async def finding_titles(uow: UnitOfWork, finding_ids: Sequence[UUID]) -> dict[UUID, FindingTitle]:
    if not finding_ids:
        return {}
    from app.modules.assessments.application import public as assessments

    return await assessments.finding_titles(uow, finding_ids)
