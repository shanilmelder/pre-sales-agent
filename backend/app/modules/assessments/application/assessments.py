"""The specialist Assessments read model (Epic 5 slice 5A).

`agent_assessments`: per agent its current Assessment (or null) with the Findings ranked
critical to low (then by position), each with its Requirement chips (label and excerpt), and
the effort rows in Requirement order with the total hours. Superseded Assessments are
hidden. No authorization: `workflows` composes it with the latest run into the Assessments
tab's view (Story 5.2), behind the Opportunity's read check.

`outdated_assessments` (Story 2.7): the current Assessments that used a Requirement version
that has changed since, for the Requirements tab's notice (anyone who can read the
Opportunity).
"""

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from app.modules.assessments.adapters import assessment_repository as repo
from app.modules.assessments.adapters.assessment_repository import (
    AssessmentRecord,
    EffortRecord,
    FindingRecord,
)
from app.modules.assessments.application.models import (
    AgentAssessment,
    AssessmentEffort,
    AssessmentFinding,
    AssessmentView,
    FindingRequirement,
    OutdatedAssessment,
    OutdatedAssessments,
    SeverityCounts,
)
from app.modules.assessments.domain.assessments import (
    AGENT_LABELS,
    AGENTS,
    AssessmentAgent,
    AssessmentStatus,
    Confidence,
    FindingKind,
    Recommendation,
    total_hours,
)
from app.modules.assessments.domain.reviews import (
    Severity,
    excerpt,
    severity_counts,
    severity_rank,
)
from app.modules.identity.application.public import Principal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform.uow import UnitOfWork

INACTIVE_LABEL = "Superseded"


async def _chips(
    uow: UnitOfWork, opportunity_id: UUID, refs: set[tuple[UUID, int]]
) -> tuple[dict[tuple[UUID, int], FindingRequirement], dict[UUID, int]]:
    """Requirement chips for `(id, version)` refs, and each active Requirement's number."""
    active = {
        s.id: s.number for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    texts = await intake.requirement_version_texts(uow, opportunity_id, list(refs))
    chips: dict[tuple[UUID, int], FindingRequirement] = {}
    for requirement_id, version in refs:
        number = active.get(requirement_id)
        found = texts.get((requirement_id, version))
        chips[(requirement_id, version)] = FindingRequirement(
            id=str(requirement_id),
            version=version,
            label=f"R{number}" if number is not None else INACTIVE_LABEL,
            excerpt="" if found is None else excerpt(found.text),
        )
    return chips, active


async def _views(
    uow: UnitOfWork, opportunity_id: UUID, records: Sequence[AssessmentRecord]
) -> dict[str, AssessmentView]:
    """Each Assessment with its ranked Findings, their chips, its effort and the counts."""
    ids = [r.id for r in records]
    findings = await repo.findings_of(uow, ids)
    links = await repo.requirement_links_for(uow, [f.id for f in findings])
    effort = await repo.effort_of(uow, ids)
    refs = {(link.requirement_id, link.requirement_version) for link in links} | {
        (e.requirement_id, e.requirement_version) for e in effort
    }
    chips, active = await _chips(uow, opportunity_id, refs)

    def order(requirement_id: UUID) -> tuple[int, str]:
        return (active.get(requirement_id, len(active) + 1), str(requirement_id))

    cited: dict[UUID, list[FindingRequirement]] = defaultdict(list)
    for link in sorted(links, key=lambda link: order(link.requirement_id)):
        cited[link.finding_id].append(chips[(link.requirement_id, link.requirement_version)])
    by_assessment: dict[UUID, list[FindingRecord]] = defaultdict(list)
    for f in findings:
        by_assessment[f.assessment_id].append(f)
    effort_by: dict[UUID, list[EffortRecord]] = defaultdict(list)
    for e in sorted(effort, key=lambda e: order(e.requirement_id)):
        effort_by[e.assessment_id].append(e)

    views: dict[str, AssessmentView] = {}
    for record in records:
        own = by_assessment.get(record.id, [])
        rows = effort_by.get(record.id, [])
        counts = severity_counts(Severity(f.severity) for f in own)
        views[record.agent] = AssessmentView(
            id=str(record.id),
            agent=AssessmentAgent(record.agent),
            version=record.version,
            status=AssessmentStatus(record.status),
            run_id=str(record.run_id),
            config_version_id=str(record.config_version_id),
            recommendation=Recommendation(record.recommendation),
            confidence=Confidence(record.confidence),
            confidence_basis=record.confidence_basis,
            dropped_count=record.dropped_count,
            created_at=record.created_at,
            counts=SeverityCounts(
                critical=counts[Severity.CRITICAL],
                high=counts[Severity.HIGH],
                medium=counts[Severity.MEDIUM],
                low=counts[Severity.LOW],
            ),
            findings=[
                AssessmentFinding(
                    id=str(f.id),
                    position=f.position,
                    kind=FindingKind(f.kind),
                    severity=Severity(f.severity),
                    title=f.title,
                    detail=f.detail,
                    requirements=cited.get(f.id, []),
                    injection_suspected=f.injection_suspected,
                )
                for f in sorted(own, key=lambda f: (severity_rank(f.severity), f.position))
            ],
            effort=[
                AssessmentEffort(
                    requirement=chips[(e.requirement_id, e.requirement_version)],
                    hours=float(e.hours),
                    basis=e.basis,
                )
                for e in rows
            ],
            total_hours=float(total_hours(Decimal(e.hours) for e in rows)),
        )
    return views


async def agent_assessments(uow: UnitOfWork, opportunity_id: UUID) -> list[AgentAssessment]:
    """One slot per agent (Engineering, PM, Security) with its current Assessment or null."""
    views = await _views(uow, opportunity_id, await repo.current_assessments(uow, opportunity_id))
    return [AgentAssessment(agent=agent, assessment=views.get(agent.value)) for agent in AGENTS]


async def outdated_assessments(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> OutdatedAssessments:
    """The Opportunity's current Assessments with at least one Requirement pin (a Finding's or
    an effort row's) older than that Requirement's current version, or whose Requirement is
    no longer active (Story 2.7). Anyone who can read the Opportunity."""
    await opportunities.readable_resource(uow, actor, opportunity_id)
    records = await repo.current_assessments(uow, opportunity_id)
    if not records:
        return OutdatedAssessments(items=[])
    active = {
        s.id: (s.version, s.number)
        for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    ids = [r.id for r in records]
    findings = await repo.findings_of(uow, ids)
    owner = {f.id: f.assessment_id for f in findings}
    pins: dict[UUID, set[tuple[UUID, int]]] = defaultdict(set)
    for link in await repo.requirement_links_for(uow, list(owner)):
        pins[owner[link.finding_id]].add((link.requirement_id, link.requirement_version))
    for e in await repo.effort_of(uow, ids):
        pins[e.assessment_id].add((e.requirement_id, e.requirement_version))

    items: list[OutdatedAssessment] = []
    for record in sorted(records, key=lambda r: AGENTS.index(AssessmentAgent(r.agent))):
        numbers: set[int] = set()
        inactive = False
        for requirement_id, version in pins.get(record.id, set()):
            current = active.get(requirement_id)
            if current is None:
                inactive = True
            elif version < current[0]:
                numbers.add(current[1])
        if not numbers and not inactive:
            continue
        labels = [f"R{n}" for n in sorted(numbers)]
        if inactive:
            labels.append(INACTIVE_LABEL)
        agent = AssessmentAgent(record.agent)
        items.append(
            OutdatedAssessment(
                id=str(record.id), agent=agent, label=AGENT_LABELS[agent], requirement_labels=labels
            )
        )
    return OutdatedAssessments(items=items)
