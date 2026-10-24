"""Critic Review (Story 6.4): what the `critic_review` task reads, and
`assessments.accept_critic_review`.

Every assessment run plans one `critic_agent` task that runs once all specialist tasks have
ended (`workflows`, Story 6.4). Its node (`app.orchestration`) reads the inputs through
`load_critic_inputs` in its short Unit of Work, calls the Agent with none open and submits
the reply to `accept_critic_review` in the Unit of Work that locked the task as still
`running`. This module never writes run or task status.

**Inputs.** The Assessments accepted in this run (the newest per agent), their Findings
labelled `F1…Fn` (agent order, then Finding order) with the agent, Assessment version, kind,
severity, title, detail and cited `R<n>`, each Assessment's effort rows, the active
Requirements `R1…Rn`, and `uncovered`: the active Requirements no Finding and no effort row
of those Assessments cites. With no Assessment accepted in the run there is nothing to
review: no model call and no Review (the task succeeds).

**Accepting** (one Unit of Work): the reply is re-validated (AD-4; an unparseable reply
raises `ModelOutputInvalidError`, so the task is retried like the specialists'); every
proposed Finding is checked (`domain/critic.py`; Requirement labels resolve only to
Requirements still active at the version read); each uncovered Requirement no valid
`coverage` Finding cites gets a code-written one; the contradictions go to
`conflicts.raise_critic_conflicts` (Conflicts with `detected_by = critic`, never Findings);
the Opportunity's `current` Critic Review is superseded and the new one stored (numbered one
past the latest, with its run), its Findings linked to the Requirements and to the specialist
Findings they cite at their Assessment version; and `assessments.critic_review.completed` is
traced.

`run_assessment_reads` backs the `assessments.run.read` ToolGateway tool (`tools.py`).

Logs and trace carry ids and counts only, never Requirement, Finding or argument text.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.agents.contract import AgentConfig, AgentResult
from app.agents.critic_agent.agent import (
    CriticAgent,
    CriticTask,
    EffortBlock,
    FindingBlock,
    RequirementBlock,
)
from app.agents.critic_agent.schema import CriticOutput
from app.modules.assessments.adapters import repository as repo
from app.modules.assessments.application.assessment import (
    run_assessment_snapshots,
    run_finding_snapshots,
)
from app.modules.assessments.domain.assessments import AGENT_LABELS, AGENTS, AssessmentAgent
from app.modules.assessments.domain.critic import (
    CRITIC_AGENT,
    CriticFindingCandidate,
    CriticValidation,
    uncovered,
)
from app.modules.assessments.domain.critic import (
    validate_critic_findings as validate,
)
from app.modules.assessments.domain.reviews import (
    REVIEW_SUBJECT_TYPE,
    ReviewKind,
    Severity,
    severity_counts,
)
from app.modules.conflicts.application import public as conflicts
from app.modules.intake.application import public as intake
from app.modules.registry.application import public as registry
from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.model_gateway.port import ModelGatewayPort, ModelOutputInvalidError
from app.platform.trace.catalogue import AssessmentsCriticReviewCompleted
from app.platform.uow import UnitOfWork

_KIND = ReviewKind.CRITIC.value
_log = get_logger(__name__)


def agent_role(agent: str) -> str:
    """The agent's role in words ("Engineering Agent"); an unknown id in words."""
    try:
        return AGENT_LABELS[AssessmentAgent(agent)]
    except ValueError:
        return " ".join(w.capitalize() for w in agent.split("_") if w)


@dataclass(frozen=True, slots=True)
class CriticRequirement:
    """An active Requirement the task read, with its prompt label `R<n>`."""

    label: str
    requirement_id: UUID
    version: int
    classification: str
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class CriticFinding:
    """A specialist Finding of the run, with its prompt label `F<n>` and its cited
    Requirements' labels (active ones only, in Requirement order)."""

    label: str
    snapshot: conflicts.FindingSnapshot = field(repr=False)
    requirement_labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CriticEffort:
    """One Assessment's effort rows: (`R<n>`, hours to 0.1) for its active Requirements."""

    agent: str
    assessment_version: int
    rows: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CriticInputs:
    """What the task read (module docstring). `uncovered`: labels, in Requirement order."""

    requirements: Sequence[CriticRequirement] = field(repr=False, default=())
    findings: Sequence[CriticFinding] = field(repr=False, default=())
    effort: Sequence[CriticEffort] = field(repr=False, default=())
    uncovered: tuple[str, ...] = ()
    assessment_count: int = 0


@dataclass(frozen=True, slots=True)
class RunAssessment:
    """An Assessment accepted in the run, with its Findings (the `assessments.run.read`
    tool's record)."""

    assessment: conflicts.AssessmentSnapshot
    findings: tuple[conflicts.FindingSnapshot, ...] = field(repr=False, default=())


async def run_assessment_reads(
    uow: UnitOfWork, opportunity_id: UUID, run_id: UUID
) -> list[RunAssessment]:
    """The Assessments accepted in the run (the newest per agent, in agent order) with their
    Findings and versions. No authorization."""
    snapshots = await run_assessment_snapshots(uow, opportunity_id, run_id)
    found = await run_finding_snapshots(uow, opportunity_id, run_id)
    return [
        RunAssessment(
            assessment=a,
            findings=tuple(f for f in found if f.assessment_id == a.assessment_id),
        )
        for a in snapshots
    ]


def _agent_rank(agent: str) -> int:
    try:
        return AGENTS.index(AssessmentAgent(agent))
    except ValueError:
        return len(AGENTS)


async def load_critic_inputs(uow: UnitOfWork, opportunity_id: UUID, run_id: UUID) -> CriticInputs:
    """The Critic task's inputs (module docstring). Queries; no authorization."""
    return critic_inputs(
        await intake.active_requirement_snapshots(uow, opportunity_id),
        await run_assessment_reads(uow, opportunity_id, run_id),
    )


def critic_inputs(
    active: Sequence[intake.RequirementSnapshot], reads: Sequence[RunAssessment]
) -> CriticInputs:
    """The inputs from the active Requirements and the run's Assessments, labelled, with the
    uncovered Requirements computed. Pure (the eval builds its fixtures with it)."""
    numbers = {s.id: s.number for s in active}
    requirements = [
        CriticRequirement(
            label=f"R{s.number}",
            requirement_id=s.id,
            version=s.version,
            classification=s.classification,
            text=s.text,
        )
        for s in active
    ]

    def order(requirement_id: UUID) -> tuple[int, str]:
        return (numbers.get(requirement_id, len(numbers) + 1), str(requirement_id))

    ordered = sorted(
        (f for r in reads for f in r.findings),
        key=lambda f: (_agent_rank(f.agent), f.agent, f.position),
    )
    findings = [
        CriticFinding(
            label=f"F{n}",
            snapshot=f,
            requirement_labels=tuple(
                f"R{numbers[rid]}"
                for rid, _ in sorted(f.requirements, key=lambda r: order(r[0]))
                if rid in numbers
            ),
        )
        for n, f in enumerate(ordered, start=1)
    ]
    effort = [
        CriticEffort(
            agent=r.assessment.agent,
            assessment_version=r.assessment.version,
            rows=tuple(
                (f"R{numbers[e.requirement_id]}", f"{e.hours:.1f}")
                for e in sorted(r.assessment.effort, key=lambda e: order(e.requirement_id))
                if e.requirement_id in numbers
            ),
        )
        for r in reads
    ]
    cited = {rid for f in ordered for rid, _ in f.requirements} | {
        e.requirement_id for r in reads for e in r.assessment.effort
    }
    return CriticInputs(
        requirements=requirements,
        findings=findings,
        effort=effort,
        uncovered=tuple(uncovered([(r.label, r.requirement_id) for r in requirements], cited)),
        assessment_count=len(reads),
    )


def critic_task(inputs: CriticInputs, *, opportunity_id: UUID, run_id: UUID) -> CriticTask:
    """The agent's task: the inputs as prompt blocks."""
    return CriticTask(
        opportunity_id=opportunity_id,
        run_id=run_id,
        requirements=[
            RequirementBlock(r.label, r.classification, r.text) for r in inputs.requirements
        ],
        findings=[
            FindingBlock(
                label=f.label,
                role=agent_role(f.snapshot.agent),
                assessment_version=f.snapshot.assessment_version,
                kind=f.snapshot.kind,
                severity=f.snapshot.severity,
                title=f.snapshot.title,
                detail=f.snapshot.detail,
                requirements=f.requirement_labels,
            )
            for f in inputs.findings
        ],
        effort=[
            EffortBlock(
                role=agent_role(e.agent), assessment_version=e.assessment_version, rows=e.rows
            )
            for e in inputs.effort
        ],
        uncovered=inputs.uncovered,
    )


EVAL_SEMVER = "0.1.0"
"""The seeded config version the eval runs (prompt 1)."""


async def evaluate_critic(
    gateway: ModelGatewayPort, inputs: CriticInputs, *, profile: str
) -> CriticValidation[conflicts.FindingSnapshot, tuple[UUID, int]]:
    """`make eval-critic` (Story 6.4): run `critic_agent` (prompt 1) on these inputs through
    `gateway` and validate its Findings with the task's pure validation, without a database
    (no call rows). The backstopped Findings are marked (`backstop`): the eval scores the
    agent's own. Raises the gateway's errors and `ModelOutputInvalidError` for a malformed
    extension."""
    config = AgentConfig(
        agent_id=CRITIC_AGENT,
        semver=EVAL_SEMVER,
        prompt_version=1,
        profile=profile,
        config_version_id=registry.seed_config_version_id(CRITIC_AGENT),
    )
    agent = CriticAgent(gateway, config=config)
    result = await agent.run(critic_task(inputs, opportunity_id=new_id(), run_id=new_id()))
    return evaluate(proposal(result), inputs)


# --- accepting ------------------------------------------------------------------------------


def proposal(result: AgentResult) -> CriticOutput:
    """The agent's proposal, re-validated (AD-4). Raises `ModelOutputInvalidError` when the
    extension is missing or malformed."""
    raw = result.extensions.get(CRITIC_AGENT)
    try:
        return CriticOutput.model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError("The critic_agent extension is not valid.") from None


def candidates(output: CriticOutput) -> list[CriticFindingCandidate]:
    return [
        CriticFindingCandidate(
            category=f.category,
            severity=f.severity,
            title=f.title,
            argument=f.argument,
            findings=tuple(f.findings),
            requirements=tuple(f.requirements),
        )
        for f in output.findings
    ]


def contradictions(output: CriticOutput) -> list[conflicts.SemanticCandidate]:
    return [
        conflicts.SemanticCandidate(
            type=c.type,
            severity=c.severity,
            finding_labels=tuple(p.finding for p in c.positions),
            summary=c.summary,
            stances=tuple(conflicts.StanceCandidate(p.finding, p.stance) for p in c.positions),
            mandatory_constraint=c.mandatory_constraint,
        )
        for c in output.contradictions
    ]


def evaluate(
    output: CriticOutput, inputs: CriticInputs
) -> CriticValidation[conflicts.FindingSnapshot, tuple[UUID, int]]:
    """The proposed Findings validated against what the task read (no database: every
    Requirement read counts as still active), with the coverage backstop. The eval
    (`evaluate_critic`) scores this and filters out the backstop Findings (`backstop`)."""
    return validate(
        candidates(output),
        {f.label: f.snapshot for f in inputs.findings},
        {r.label: (r.requirement_id, r.version) for r in inputs.requirements},
        inputs.uncovered,
    )


async def accept_critic_review(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    run_id: UUID,
    result: AgentResult,
    inputs: CriticInputs,
    actor: Actor,
) -> CriticValidation[conflicts.FindingSnapshot, tuple[UUID, int]]:
    """`assessments.accept_critic_review`: validate the Critic's reply and store it as the
    Opportunity's new `current` Critic Review (module docstring). The caller (the task's
    node) has locked the task as still `running` in this Unit of Work and marks it done
    after. Raises `ModelOutputInvalidError` (and writes nothing) for an unparseable reply."""
    await repo.lock_reviews(uow, opportunity_id, _KIND)
    ids = {"run_id": str(run_id), "opportunity_id": str(opportunity_id)}
    output = proposal(result)
    current = {
        (s.id, s.version) for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    requirement_labels = {
        r.label: (r.requirement_id, r.version)
        for r in inputs.requirements
        if (r.requirement_id, r.version) in current
    }
    finding_labels = {f.label: f.snapshot for f in inputs.findings}
    validation = validate(candidates(output), finding_labels, requirement_labels, inputs.uncovered)
    raised = await conflicts.raise_critic_conflicts(
        uow,
        opportunity_id=opportunity_id,
        run_id=run_id,
        candidates=contradictions(output),
        findings=finding_labels,
        actor=actor,
    )

    superseded = await repo.supersede_reviews(uow, opportunity_id, _KIND)
    number = await repo.latest_review_number(uow, opportunity_id, _KIND) + 1
    review_id = new_id()
    await repo.insert_review(
        uow,
        review_id=review_id,
        opportunity_id=opportunity_id,
        kind=_KIND,
        version=number,
        estimate_version_id=None,
        run_id=run_id,
        dropped_count=validation.dropped,
        findings=[
            repo.NewFinding(
                finding_id=new_id(),
                position=position,
                category=f.category.value,
                severity=f.severity.value,
                title=f.title,
                argument=f.argument,
                requirements=list(f.requirements),
                lines=[],
                targets=[(t.finding_id, t.assessment_id, t.assessment_version) for t in f.findings],
            )
            for position, f in enumerate(validation.findings, start=1)
        ],
    )
    counts = severity_counts(f.severity for f in validation.findings)
    completed = AssessmentsCriticReviewCompleted(
        version=number,
        finding_count=len(validation.findings),
        critical_count=counts[Severity.CRITICAL],
        high_count=counts[Severity.HIGH],
        medium_count=counts[Severity.MEDIUM],
        low_count=counts[Severity.LOW],
        dropped_count=validation.dropped,
        backstopped_count=validation.backstopped,
        conflict_count=raised.raised,
        superseded_count=superseded,
    )
    await trace.append(
        uow,
        actor=actor,
        payload=completed,
        subject_type=REVIEW_SUBJECT_TYPE,
        subject_id=review_id,
        subject_version=number,
        opportunity_id=opportunity_id,
        workflow_run_id=run_id,
    )
    _log.info(
        "assessments.critic_accepted",
        extra={
            **ids,
            "review_id": str(review_id),
            "contradiction_dropped_count": raised.dropped,
            **completed.model_dump(),
        },
    )
    return validation
