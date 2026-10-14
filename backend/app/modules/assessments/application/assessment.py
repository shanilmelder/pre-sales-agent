"""Specialist Assessments (Epic 5 slice 5A): the inputs an assessment task reads, and
`assessments.accept_assessment`.

Since Story 5.2 the runs and tasks belong to `workflows`, which executes each task as a node
of the run's LangGraph graph (`app.orchestration`): the node loads the inputs through
`load_inputs`, calls the Agent outside any Unit of Work and, in one Unit of Work, locks its
still-`running` task (a late reply after a cancel is discarded there), submits the result to
`accept_assessment` and marks the task done through `workflows`. This module never writes
run or task status.

`current_sizings` and `current_assessment_snapshots` give `workflows` each agent's current
Assessment when a run finishes (the Estimate is built from them, Story 8.3, and the Conflict
rules run over them, Story 6.1).

Logs and trace carry ids, codes and counts only, never Requirement, Gap or Finding text.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.agents.contract import AgentResult
from app.agents.engineering_agent.schema import EngineeringOutput
from app.agents.pm_agent.schema import PmOutput
from app.agents.security_agent.schema import SecurityOutput
from app.agents.specialist.schema import SpecialistOutput
from app.modules.assessments.adapters import assessment_repository as repo
from app.modules.assessments.domain.assessments import (
    AGENTS,
    ASSESSMENT_SUBJECT_TYPE,
    AssessmentAgent,
    AssessmentCandidate,
    AssessmentFindingCandidate,
    AssessmentValidation,
    EffortCandidate,
    validate_assessment,
)
from app.modules.assessments.domain.reviews import Severity, severity_counts
from app.modules.conflicts.application import public as conflicts
from app.modules.estimates.application import public as estimates
from app.modules.gaps.application import public as gaps
from app.modules.intake.application import public as intake
from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.model_gateway.port import ModelOutputInvalidError
from app.platform.trace.catalogue import AssessmentsAssessmentCompleted
from app.platform.uow import UnitOfWork

_log = get_logger(__name__)

_OUTPUTS: dict[AssessmentAgent, type[SpecialistOutput]] = {
    AssessmentAgent.ENGINEERING: EngineeringOutput,
    AssessmentAgent.PM: PmOutput,
    AssessmentAgent.SECURITY: SecurityOutput,
}


# --- accepting ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssessedRequirement:
    """A Requirement the run read, with its prompt label `R<n>`."""

    label: str
    requirement_id: UUID
    version: int
    classification: str
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AssessedGap:
    """An open Gap the run read, with its prompt label `G<n>`."""

    label: str
    category: str
    impact: str
    title: str = field(repr=False)
    why_it_matters: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class AssessmentInputs:
    """What a task read: the Requirements, the open Gaps and their number."""

    requirements: Sequence[AssessedRequirement]
    gap_count: int = 0
    gaps: Sequence[AssessedGap] = field(default=(), repr=False)


async def load_inputs(uow: UnitOfWork, opportunity_id: UUID) -> AssessmentInputs:
    """The Opportunity's active Requirements at their current versions, labelled `R<n>`, and
    its open Gaps, labelled `G<n>` (queries; no authorization)."""
    snapshots = await intake.active_requirement_snapshots(uow, opportunity_id)
    open_gaps = await gaps.open_gap_summaries(uow, opportunity_id)
    return AssessmentInputs(
        requirements=[
            AssessedRequirement(
                label=f"R{s.number}",
                requirement_id=s.id,
                version=s.version,
                classification=s.classification,
                text=s.text,
            )
            for s in snapshots
        ],
        gap_count=len(open_gaps),
        gaps=[
            AssessedGap(
                label=f"G{n}",
                category=g.category,
                impact=g.impact,
                title=g.title,
                why_it_matters=g.why_it_matters,
            )
            for n, g in enumerate(open_gaps, start=1)
        ],
    )


def proposal(agent: AssessmentAgent, result: AgentResult) -> SpecialistOutput:
    """The agent's proposed Assessment, re-validated (AD-4). Raises `ModelOutputInvalidError`
    when the extension is missing or malformed."""
    raw = result.extensions.get(agent.value)
    try:
        return _OUTPUTS[agent].model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError(f"The {agent.value} extension is not valid.") from None


def candidate(output: SpecialistOutput) -> AssessmentCandidate:
    return AssessmentCandidate(
        recommendation=output.recommendation,
        confidence=output.confidence,
        confidence_basis=output.confidence_basis,
        findings=[
            AssessmentFindingCandidate(
                kind=f.kind,
                severity=f.severity,
                title=f.title,
                detail=f.detail,
                requirements=tuple(f.requirements),
            )
            for f in output.findings
        ],
        effort=[
            EffortCandidate(requirement=e.requirement, hours=e.hours, basis=e.basis)
            for e in output.effort
        ],
    )


async def accept_assessment(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    run_id: UUID,
    agent: AssessmentAgent,
    config_version_id: UUID,
    result: AgentResult,
    inputs: AssessmentInputs,
    actor: Actor,
) -> AssessmentValidation[tuple[UUID, int]]:
    """`assessments.accept_assessment`: validate the agent's reply and store it as the
    agent's new `current` Assessment of the Opportunity, superseding its earlier one, and
    trace it. `run_id` and `config_version_id`: the Workflow Run and the registry config
    version the task pinned (stored with it). The caller (the task's node) has locked the
    task as still `running` in this Unit of Work and marks it done after.

    Raises `ModelOutputInvalidError` (and writes nothing) when the recommendation or
    confidence is missing or invalid, or when no Finding is valid, so the task runs again.
    Invalid Findings and effort rows are dropped and counted."""
    await repo.lock_agent(uow, opportunity_id, agent.value)
    ids = {"run_id": str(run_id), "opportunity_id": str(opportunity_id)}

    proposed = candidate(proposal(agent, result))
    current = {
        (s.id, s.version) for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    labels = {
        r.label: (r.requirement_id, r.version)
        for r in inputs.requirements
        if (r.requirement_id, r.version) in current
    }
    validation = validate_assessment(proposed, labels)
    if validation is None:
        _log.info("assessments.assessment_reply_invalid", extra={**ids, "agent": agent.value})
        raise ModelOutputInvalidError(f"The {agent.value} recommendation or confidence is invalid.")
    if not validation.findings:
        _log.info(
            "assessments.assessment_all_invalid",
            extra={**ids, "agent": agent.value, "dropped_count": validation.dropped},
        )
        raise ModelOutputInvalidError(f"No proposed {agent.value} Finding was valid.")

    superseded = await repo.supersede_assessments(uow, opportunity_id, agent.value)
    number = await repo.latest_assessment_number(uow, opportunity_id, agent.value) + 1
    assessment_id = new_id()
    await repo.insert_assessment(
        uow,
        assessment_id=assessment_id,
        opportunity_id=opportunity_id,
        agent=agent.value,
        version=number,
        run_id=run_id,
        config_version_id=config_version_id,
        recommendation=validation.recommendation.value,
        confidence=validation.confidence.value,
        confidence_basis=validation.confidence_basis,
        dropped_count=validation.dropped,
        findings=[
            repo.NewFinding(
                position=position,
                kind=f.kind.value,
                severity=f.severity.value,
                title=f.title,
                detail=f.detail,
                requirements=list(f.requirements),
            )
            for position, f in enumerate(validation.findings, start=1)
        ],
        effort=[
            repo.NewEffort(
                requirement_id=e.requirement[0],
                requirement_version=e.requirement[1],
                hours=e.hours,
                basis=e.basis,
            )
            for e in validation.effort
        ],
    )
    counts = severity_counts(f.severity for f in validation.findings)
    completed = AssessmentsAssessmentCompleted(
        run_id=str(run_id),
        agent=agent.value,
        version=number,
        recommendation=validation.recommendation.value,
        confidence=validation.confidence.value,
        finding_count=len(validation.findings),
        critical_count=counts[Severity.CRITICAL],
        high_count=counts[Severity.HIGH],
        medium_count=counts[Severity.MEDIUM],
        low_count=counts[Severity.LOW],
        effort_count=len(validation.effort),
        dropped_count=validation.dropped,
        requirement_count=len(inputs.requirements),
        gap_count=inputs.gap_count,
        superseded_count=superseded,
    )
    await trace.append(
        uow,
        actor=actor,
        payload=completed,
        subject_type=ASSESSMENT_SUBJECT_TYPE,
        subject_id=assessment_id,
        subject_version=number,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "assessments.assessment_accepted",
        extra={**ids, "assessment_id": str(assessment_id), **completed.model_dump()},
    )
    return validation


async def current_assessment_snapshots(
    uow: UnitOfWork, opportunity_id: UUID
) -> list[conflicts.AssessmentSnapshot]:
    """Each agent's current Assessment of the Opportunity: id, version, recommendation and
    effort rows (Requirement id and version, hours), in agent order. No authorization."""
    records = sorted(
        await repo.current_assessments(uow, opportunity_id),
        key=lambda r: AGENTS.index(AssessmentAgent(r.agent)),
    )
    effort: dict[UUID, list[conflicts.EffortSnapshot]] = {}
    for row in await repo.effort_of(uow, [r.id for r in records]):
        effort.setdefault(row.assessment_id, []).append(
            conflicts.EffortSnapshot(
                requirement_id=row.requirement_id,
                requirement_version=row.requirement_version,
                hours=row.hours,
            )
        )
    return [
        conflicts.AssessmentSnapshot(
            assessment_id=r.id,
            agent=r.agent,
            version=r.version,
            recommendation=r.recommendation,
            effort=tuple(sorted(effort.get(r.id, []), key=lambda e: str(e.requirement_id))),
        )
        for r in records
    ]


async def current_sizings(uow: UnitOfWork, opportunity_id: UUID) -> list[estimates.AgentSizing]:
    """Each agent's current Assessment of the Opportunity with its effort rows and their
    basis, in agent order (Story 8.3: the Estimate from the Assessments). No authorization."""
    records = sorted(
        await repo.current_assessments(uow, opportunity_id),
        key=lambda r: AGENTS.index(AssessmentAgent(r.agent)),
    )
    rows: dict[UUID, list[estimates.SizingRow]] = {}
    for row in await repo.effort_of(uow, [r.id for r in records]):
        rows.setdefault(row.assessment_id, []).append(
            estimates.SizingRow(
                requirement_id=row.requirement_id,
                requirement_version=row.requirement_version,
                hours=row.hours,
                basis=row.basis,
            )
        )
    return [
        estimates.AgentSizing(
            agent=r.agent,
            assessment_id=r.id,
            assessment_version=r.version,
            rows=tuple(sorted(rows.get(r.id, []), key=lambda e: str(e.requirement_id))),
        )
        for r in records
    ]
