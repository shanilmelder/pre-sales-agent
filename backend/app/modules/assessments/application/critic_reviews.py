"""The Critic query (Story 6.4): `get_critic`, the Opportunity's current Critic Review in the
Red Team's view shape. Findings are ranked critical to low (then by position), each with its
Requirement chips (label and excerpt) and its cited-Finding chips (agent role, Assessment
version and title), with the counts per severity, and (Story 6.6) each Finding's status and
what the caller may do with it, plus the Review's blocking count. Superseded Reviews are
hidden. Anyone who can read the Opportunity.
"""

from collections import defaultdict
from uuid import UUID

from app.modules.assessments.adapters import assessment_repository as assessment_repo
from app.modules.assessments.adapters import repository as repo
from app.modules.assessments.adapters.repository import FindingRecord, ReviewRecord
from app.modules.assessments.application.critic import agent_role
from app.modules.assessments.application.findings import blocking_count, finding_states
from app.modules.assessments.application.models import (
    CitedFinding,
    CriticFinding,
    CriticReviewView,
    CriticView,
    SeverityCounts,
)
from app.modules.assessments.application.reviews import requirement_chips
from app.modules.assessments.domain.assessments import AGENTS, AssessmentAgent
from app.modules.assessments.domain.critic import CriticCategory
from app.modules.assessments.domain.reviews import (
    ReviewKind,
    ReviewStatus,
    Severity,
    severity_counts,
    severity_rank,
)
from app.modules.identity.application.public import Principal, Resource
from app.modules.opportunities.application import public as opportunities
from app.platform.uow import UnitOfWork

_KIND = ReviewKind.CRITIC.value


async def _cited(uow: UnitOfWork, finding_ids: list[UUID]) -> dict[UUID, list[CitedFinding]]:
    links = await repo.target_links_for(uow, finding_ids)
    found = {
        f.id: f
        for f in await assessment_repo.findings_by_id(
            uow, list({link.assessment_finding_id for link in links})
        )
    }
    agents = {
        a.id: a.agent
        for a in await assessment_repo.assessments_by_id(
            uow, list({link.assessment_id for link in links})
        )
    }
    cited: dict[UUID, list[tuple[tuple[int, int, int], CitedFinding]]] = defaultdict(list)
    for link in links:
        finding = found.get(link.assessment_finding_id)
        agent = agents.get(link.assessment_id)
        if finding is None or agent is None:  # pragma: no cover - never deleted
            continue
        known = AssessmentAgent(agent)
        cited[link.finding_id].append(
            (
                (AGENTS.index(known), link.assessment_version, finding.position),
                CitedFinding(
                    id=str(finding.id),
                    agent=known,
                    role=agent_role(agent),
                    assessment_id=str(link.assessment_id),
                    assessment_version=link.assessment_version,
                    title=finding.title,
                ),
            )
        )
    return {
        finding_id: [c for _, c in sorted(items, key=lambda pair: pair[0])]
        for finding_id, items in cited.items()
    }


async def critic_review_view(
    uow: UnitOfWork,
    record: ReviewRecord,
    actor: Principal,
    resource: Resource,
    findings: list[FindingRecord],
) -> CriticReviewView:
    """The Critic Review with its ranked Findings, their chips, statuses (Story 6.6) and the
    counts per severity."""
    states = await finding_states(uow, actor, resource, record.opportunity_id, record, findings)
    ids = [f.id for f in findings]
    requirements = await requirement_chips(uow, record.opportunity_id, findings)
    cited = await _cited(uow, ids)
    counts = severity_counts(Severity(f.severity) for f in findings)
    return CriticReviewView(
        id=str(record.id),
        version=record.version,
        status=ReviewStatus(record.status),
        run_id=None if record.run_id is None else str(record.run_id),
        dropped_count=record.dropped_count,
        created_at=record.created_at,
        counts=SeverityCounts(
            critical=counts[Severity.CRITICAL],
            high=counts[Severity.HIGH],
            medium=counts[Severity.MEDIUM],
            low=counts[Severity.LOW],
        ),
        findings=[
            CriticFinding(
                **dict(states[f.id]),
                position=f.position,
                category=CriticCategory(f.category),
                severity=Severity(f.severity),
                title=f.title,
                argument=f.argument,
                requirements=requirements.get(f.id, []),
                findings=cited.get(f.id, []),
            )
            for f in sorted(findings, key=lambda f: (severity_rank(f.severity), f.position))
        ],
    )


async def get_critic(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> CriticView:
    """The Opportunity's current Critic Review (null before the first)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    record = await repo.current_review(uow, opportunity_id, _KIND)
    if record is None:
        return CriticView(review=None, blocking_count=0)
    findings = await repo.findings_of(uow, record.id)
    return CriticView(
        review=await critic_review_view(uow, record, actor, resource, findings),
        blocking_count=blocking_count(findings),
    )
