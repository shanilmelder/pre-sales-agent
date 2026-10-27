"""assessments' public API. Other modules (and `app.orchestration`) import assessments only
from here."""

from uuid import UUID

from app.modules.assessments.application import review
from app.modules.assessments.application import tools as tools  # registers the ToolGateway handler
from app.modules.assessments.application.assessment import (
    AssessedGap,
    AssessedRequirement,
    AssessmentInputs,
    accept_assessment,
    build_inputs,
    current_assessment_snapshots,
    current_finding_snapshots,
    current_sizings,
    finding_titles,
    load_inputs,
    run_assessment_snapshots,
    run_finding_snapshots,
)
from app.modules.assessments.application.assessments import (
    AssessmentCitations,
    FindingCitations,
    agent_assessments,
    assessment_at,
    current_citations,
    outdated_assessments,
)
from app.modules.assessments.application.critic import (
    CriticEffort,
    CriticFinding,
    CriticInputs,
    CriticRequirement,
    RunAssessment,
    accept_critic_review,
    agent_role,
    critic_inputs,
    critic_task,
    evaluate_critic,
    load_critic_inputs,
    run_assessment_reads,
)
from app.modules.assessments.application.critic_reviews import get_critic
from app.modules.assessments.application.findings import (
    blocking_finding_counts,
    get_blocking_findings,
    mark_resolved,
    override_finding,
    supply_evidence,
)
from app.modules.assessments.application.models import (
    AgentAssessment,
    AssessmentEffort,
    AssessmentFinding,
    AssessmentView,
    BlockingFinding,
    CitedFinding,
    CriticReviewView,
    CriticView,
    EvidenceRefIn,
    FindingEvidence,
    FindingEvidenceSubmission,
    FindingLine,
    FindingOverride,
    FindingPerson,
    FindingReason,
    FindingRequirement,
    FindingResolution,
    FindingState,
    OutdatedAssessment,
    OutdatedAssessments,
    PolicyRef,
    RedTeamFinding,
    RedTeamReviewView,
    RedTeamRun,
    RedTeamView,
    SeverityCounts,
)
from app.modules.assessments.application.reviews import get_red_team, start_review
from app.modules.assessments.domain.assessments import AGENTS, AssessmentAgent
from app.modules.assessments.domain.critic import CRITIC_AGENT
from app.modules.assessments.domain.reviews import RunErrorCode
from app.platform.uow import UnitOfWork


async def enqueue_review(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a Red Team Review of the Opportunity in the caller's Unit of Work (Story 6.5:
    after every stored Estimate Version). Coalesces with a run that is queued and not yet
    started; returns the run's id."""
    return await review.enqueue_review(uow, opportunity_id)


__all__ = [
    "AGENTS",
    "CRITIC_AGENT",
    "AgentAssessment",
    "AssessedGap",
    "AssessedRequirement",
    "AssessmentAgent",
    "AssessmentCitations",
    "AssessmentEffort",
    "AssessmentFinding",
    "AssessmentInputs",
    "AssessmentView",
    "BlockingFinding",
    "CitedFinding",
    "CriticEffort",
    "CriticFinding",
    "CriticInputs",
    "CriticRequirement",
    "CriticReviewView",
    "CriticView",
    "EvidenceRefIn",
    "FindingCitations",
    "FindingEvidence",
    "FindingEvidenceSubmission",
    "FindingLine",
    "FindingOverride",
    "FindingPerson",
    "FindingReason",
    "FindingRequirement",
    "FindingResolution",
    "FindingState",
    "OutdatedAssessment",
    "OutdatedAssessments",
    "PolicyRef",
    "RedTeamFinding",
    "RedTeamReviewView",
    "RedTeamRun",
    "RedTeamView",
    "RunAssessment",
    "RunErrorCode",
    "SeverityCounts",
    "accept_assessment",
    "accept_critic_review",
    "agent_assessments",
    "agent_role",
    "assessment_at",
    "blocking_finding_counts",
    "build_inputs",
    "critic_inputs",
    "critic_task",
    "current_assessment_snapshots",
    "current_citations",
    "current_finding_snapshots",
    "current_sizings",
    "enqueue_review",
    "evaluate_critic",
    "finding_titles",
    "get_blocking_findings",
    "get_critic",
    "get_red_team",
    "load_critic_inputs",
    "load_inputs",
    "mark_resolved",
    "outdated_assessments",
    "override_finding",
    "run_assessment_reads",
    "run_assessment_snapshots",
    "run_finding_snapshots",
    "start_review",
    "supply_evidence",
]
