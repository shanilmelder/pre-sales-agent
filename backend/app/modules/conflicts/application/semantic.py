"""LLM-assisted Conflict detection for free-text Findings (Story 6.2): the
`conflicts.semantic_detection` job and `conflicts.accept_semantic_conflicts`.

**Queueing.** `workflows.finish_run` calls `queue_semantic_detection` in its Unit of Work,
right after the rules ran (`detect_for_run`), with the run and the rules' detection pass. A
job (background priority) is queued only when at least two agents have a current Assessment
with at least one Finding, and only while `conflict_agent` runs tasks in the Agent Registry.
When none is queued, each open semantic Conflict citing an Assessment that is no longer
current is resolved as gone there and then (same reason, trace event and notify).

**The handler** (three phases, like the Red Team):

1. Short Unit of Work: unless a newer detection pass or run exists for the Opportunity (then
   nothing is done), reads the current specialist Findings, labels them `F<n>` (and their
   Requirements `R<n>`), and reads the Agent's current config.
2. No Unit of Work open: `conflict_agent` proposes candidate Conflicts through the
   ModelGateway.
3. `accept_semantic_conflicts`, one Unit of Work: when the pass is still the Opportunity's
   latest, validates every candidate (`domain/semantic.py`) against the Assessments current
   now and the open or escalated rule Conflicts, stores each valid one through `raise_conflict`
   (`detected_by = semantic`, actor `conflict_agent@<semver>`) with one position per cited
   Finding, then resolves as gone every `open` semantic Conflict of the Opportunity it did
   not raise ("No longer present in Engineering Assessment v3", else "Not raised again by
   the Conflict Agent."). Escalated ones stand.

When the reply had candidates and every one was dropped as malformed (none for a legitimate
reason: a rule duplicate, a mandatory constraint, an Assessment no longer current), nothing is
written and `ModelOutputInvalidError` is raised, so the queue runs the job once more
(`max_attempts` 2). A reply left empty by legitimate drops counts as zero found.
A stale result (a newer pass or run) writes nothing and is not retried.

Logs and trace carry ids, kinds and counts only, never Finding, stance or summary text.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.agents.conflict_agent.agent import ConflictAgent, ConflictTask, FindingBlock
from app.agents.conflict_agent.schema import ConflictOutput
from app.agents.contract import AgentConfig, AgentResult
from app.modules.conflicts.adapters import repository as repo
from app.modules.conflicts.application import findings as assessments
from app.modules.conflicts.application.conflicts import _trace_resolved, raise_conflict
from app.modules.conflicts.domain.conflicts import (
    ConflictStatus,
    DetectedBy,
    PositionSource,
)
from app.modules.conflicts.domain.rules import ConflictCandidate, PositionCandidate
from app.modules.conflicts.domain.semantic import (
    NOT_RAISED_AGAIN,
    SEMANTIC_PREFIX,
    FindingSnapshot,
    LabelledFinding,
    SemanticCandidate,
    SemanticValidation,
    StanceCandidate,
    ValidSemantic,
    agents_with_findings,
    gone_reason,
    label_findings,
    rule_key,
    validate_semantic,
)
from app.modules.intake.application import public as intake
from app.modules.registry.application import public as registry
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelGatewayPort, ModelOutputInvalidError
from app.platform.uow import UnitOfWork, unit_of_work

SEMANTIC_DETECTION = "conflicts.semantic_detection"
CONFLICT_AGENT = "conflict_agent"
"""The Agent that compares the Findings; its config comes from the Agent Registry."""
_GONE = Actor(type="system", id="conflicts.semantic_detection")
_log = get_logger(__name__)


class SemanticDetection(JobPayload):
    opportunity_id: UUID
    run_id: UUID
    detection_pass: int


def semantic_settings() -> Settings:
    """Settings for the handler (the chat profile). Tests replace this."""
    return get_settings()


# --- queueing -------------------------------------------------------------------------------


async def queue_semantic_detection(
    uow: UnitOfWork, *, opportunity_id: UUID, run_id: UUID, detection_pass: int
) -> bool:
    """Queue the semantic detection of the run's detection pass in the caller's Unit of
    Work, when at least two agents have a current Assessment with a Finding and
    `conflict_agent` runs tasks. True when queued. When not queued, the open semantic
    Conflicts citing an Assessment no longer current are resolved as gone instead."""
    ids = {"opportunity_id": str(opportunity_id), "run_id": str(run_id)}
    found = await assessments.current_findings(uow, opportunity_id)
    reason = None
    if agents_with_findings(found) < 2:
        reason = "too_few_agents"
    elif not (await registry.current_config(uow, CONFLICT_AGENT)).runs_tasks:
        reason = "agent_disabled"
    if reason is not None:
        resolved = await _resolve_superseded(uow, opportunity_id, run_id)
        _log.info(
            "conflicts.semantic_not_queued",
            extra={**ids, "reason": reason, "resolved_count": resolved},
        )
        return False
    await enqueue(
        uow,
        SemanticDetection(
            opportunity_id=opportunity_id, run_id=run_id, detection_pass=detection_pass
        ),
        opportunity_id=opportunity_id,
    )
    _log.info("conflicts.semantic_queued", extra={**ids, "detection_pass": detection_pass})
    return True


async def _resolve_superseded(uow: UnitOfWork, opportunity_id: UUID, run_id: UUID) -> int:
    """Without an accept: lock the Opportunity's Conflicts and resolve as gone each open
    semantic Conflict citing an Assessment that is no longer current (trace, notify)."""
    await repo.lock_opportunity(uow, opportunity_id)
    current = {
        s.agent: (s.assessment_id, s.version)
        for s in await assessments.current_assessments(uow, opportunity_id)
    }
    resolved = await _resolve_gone(uow, opportunity_id, run_id, (), current, superseded=True)
    if resolved:
        await repo.notify_conflicts_changed(uow, opportunity_id)
    return resolved


async def _gone_without_accept(ctx: JobContext, payload: SemanticDetection) -> int:
    """The job ends without an accept: unless its pass is stale, resolve the superseded
    semantic Conflicts in a fresh Unit of Work."""
    async with unit_of_work(ctx.engine) as uow:
        await repo.lock_opportunity(uow, payload.opportunity_id)
        latest = await repo.latest_detection(uow, payload.opportunity_id)
        if latest != (payload.run_id, payload.detection_pass):
            return 0
        return await _resolve_superseded(uow, payload.opportunity_id, payload.run_id)


# --- accepting ------------------------------------------------------------------------------


def proposal(result: AgentResult) -> ConflictOutput:
    """The agent's proposed Conflicts, re-validated (AD-4). Raises `ModelOutputInvalidError`
    when the extension is missing or malformed."""
    raw = result.extensions.get(CONFLICT_AGENT)
    try:
        return ConflictOutput.model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError("The conflict_agent extension is not valid.") from None


def candidates(output: ConflictOutput) -> list[SemanticCandidate]:
    return [
        SemanticCandidate(
            type=c.type,
            severity=c.severity,
            finding_labels=tuple(c.finding_labels),
            summary=c.summary,
            stances=tuple(StanceCandidate(s.finding_label, s.stance) for s in c.stances),
            mandatory_constraint=c.mandatory_constraint,
        )
        for c in output.conflicts
    ]


def conflict_candidate(valid: ValidSemantic) -> ConflictCandidate:
    """The Conflict to raise: one position per cited Finding, its stance as the summary, the
    Finding's first cited Requirement."""
    positions: list[PositionCandidate] = []
    for p in valid.positions:
        finding = p.finding.finding
        first = p.finding.first_requirement
        positions.append(
            PositionCandidate(
                source=PositionSource.ASSESSMENT,
                summary=p.stance,
                agent=finding.agent,
                assessment_id=finding.assessment_id,
                assessment_version=finding.assessment_version,
                requirement_id=None if first is None else first[0],
                requirement_version=None if first is None else first[1],
                finding_id=finding.finding_id,
            )
        )
    return ConflictCandidate(
        rule=SEMANTIC_PREFIX,
        type=valid.type,
        severity=valid.severity,
        fingerprint=valid.fingerprint,
        summary=valid.summary,
        positions=tuple(positions),
    )


async def accept_semantic_conflicts(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    run_id: UUID,
    detection_pass: int,
    result: AgentResult,
    findings: Sequence[LabelledFinding],
    actor: Actor,
) -> SemanticValidation | None:
    """`conflicts.accept_semantic_conflicts`: validate the agent's candidates and store the
    valid ones as semantic Conflicts of the run's detection pass, then resolve the
    Opportunity's open semantic Conflicts it no longer raises (see the module docstring).
    None (and nothing written) when a newer detection pass or run exists."""
    ids = {
        "opportunity_id": str(opportunity_id),
        "run_id": str(run_id),
        "detection_pass": detection_pass,
    }
    await repo.lock_opportunity(uow, opportunity_id)
    if await repo.latest_detection(uow, opportunity_id) != (run_id, detection_pass):
        _log.info("conflicts.semantic_stale", extra=ids)
        return None
    proposed = candidates(proposal(result))
    current = {
        s.agent: (s.assessment_id, s.version)
        for s in await assessments.current_assessments(uow, opportunity_id)
    }
    rule_fingerprints = set(
        await repo.fingerprints_of_pass(
            uow, run_id, detection_pass, detected_by=DetectedBy.RULE.value
        )
    )
    rule_fingerprints.update(
        c.fingerprint
        for c in await repo.open_conflicts(
            uow,
            opportunity_id,
            statuses=(ConflictStatus.OPEN.value, ConflictStatus.ESCALATED.value),
            detected_by=DetectedBy.RULE.value,
        )
    )
    rule_keys = {key for fp in rule_fingerprints if (key := rule_key(fp)) is not None}
    validation = validate_semantic(
        proposed, {f.label: f for f in findings}, current=current, rule_keys=rule_keys
    )
    if validation.retry:
        _log.info(
            "conflicts.semantic_all_invalid",
            extra={**ids, "dropped_count": validation.dropped, **_reasons(validation)},
        )
        raise ModelOutputInvalidError("Every proposed semantic Conflict was malformed.")

    raised: list[UUID] = []
    created = 0
    for valid in validation.conflicts:
        outcome = await raise_conflict(
            uow,
            opportunity_id=opportunity_id,
            run_id=run_id,
            detection_pass=detection_pass,
            candidate=conflict_candidate(valid),
            detected_by=DetectedBy.SEMANTIC,
            actor=actor,
        )
        raised.append(outcome.id)
        created += outcome.created

    resolved = await _resolve_gone(uow, opportunity_id, run_id, raised, current)
    if created or resolved:
        await repo.notify_conflicts_changed(uow, opportunity_id)
    _log.info(
        "conflicts.semantic_accepted",
        extra={
            **ids,
            "candidate_count": len(proposed),
            "raised_count": len(raised),
            "created_count": created,
            "resolved_count": resolved,
            "dropped_count": validation.dropped,
            **_reasons(validation),
        },
    )
    return validation


def _reasons(validation: SemanticValidation) -> dict[str, int]:
    return {f"dropped_{reason}": count for reason, count in validation.reasons.items()}


async def _resolve_gone(
    uow: UnitOfWork,
    opportunity_id: UUID,
    run_id: UUID,
    raised: Sequence[UUID],
    current: dict[str, tuple[UUID, int]],
    *,
    superseded: bool = False,
    detected_by: DetectedBy = DetectedBy.SEMANTIC,
    not_raised: str = NOT_RAISED_AGAIN,
    actor: Actor = _GONE,
) -> int:
    """Resolve, as the system, every `open` semantic Conflict of the Opportunity that this
    pass did not raise (with `superseded`, only those citing an Assessment that is no longer
    current). Escalated ones stand. Returns how many changed."""
    gone = [
        c
        for c in await repo.open_conflicts(
            uow,
            opportunity_id,
            statuses=(ConflictStatus.OPEN.value,),
            detected_by=detected_by.value,
        )
        if c.id not in raised
    ]
    positions: dict[UUID, list[tuple[str, int]]] = {}
    outdated: set[UUID] = set()
    for p in await repo.positions_of(uow, [c.id for c in gone]):
        if p.agent is not None and p.assessment_version is not None:
            positions.setdefault(p.conflict_id, []).append((p.agent, p.assessment_version))
            if current.get(p.agent) != (p.assessment_id, p.assessment_version):
                outdated.add(p.conflict_id)
    if superseded:
        gone = [c for c in gone if c.id in outdated]
    versions = {agent: version for agent, (_, version) in current.items()}
    resolved = 0
    for conflict in gone:
        reason = gone_reason(positions.get(conflict.id, []), versions, not_raised)
        if await repo.resolve(uow, conflict.id, reason=reason):
            await _trace_resolved(uow, conflict, run_id, "no_longer_present", actor)
            resolved += 1
    return resolved


# --- the handler ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Started:
    version: registry.ConfigVersion
    findings: list[LabelledFinding] = field(repr=False)


def _short_agent(agent: str) -> str:
    return agent.removesuffix("_agent")


def _task(opportunity_id: UUID, run_id: UUID, findings: Sequence[LabelledFinding]) -> ConflictTask:
    return ConflictTask(
        opportunity_id=opportunity_id,
        run_id=run_id,
        findings=[
            FindingBlock(
                label=f.label,
                agent=_short_agent(f.finding.agent),
                assessment_version=f.finding.assessment_version,
                kind=f.finding.kind,
                severity=f.finding.severity,
                title=f.finding.title,
                detail=f.finding.detail,
                requirements=f.requirement_labels,
            )
            for f in findings
        ],
    )


EVAL_SEMVER = "0.1.0"
"""The seeded config version the eval runs (prompt 1)."""


async def evaluate_semantic(
    gateway: ModelGatewayPort,
    findings: Sequence[FindingSnapshot],
    *,
    profile: str,
    requirement_numbers: Mapping[UUID, int] | None = None,
) -> SemanticValidation:
    """`make eval-conflicts` (Story 6.2): run `conflict_agent` (prompt 1) on these Findings
    through `gateway` and validate its reply with the job's pure validation, without a
    database (no Assessment currency check, no rule Conflicts to dedupe against). Raises the
    gateway's errors and `ModelOutputInvalidError` for a malformed extension."""
    labelled = label_findings(findings, requirement_numbers or {})
    config = AgentConfig(
        agent_id=CONFLICT_AGENT,
        semver=EVAL_SEMVER,
        prompt_version=1,
        profile=profile,
        config_version_id=registry.seed_config_version_id(CONFLICT_AGENT),
    )
    agent = ConflictAgent(gateway, config=config)
    result = await agent.run(_task(new_id(), new_id(), labelled))
    return validate_semantic(candidates(proposal(result)), {f.label: f for f in labelled})


async def _start(ctx: JobContext, payload: SemanticDetection) -> _Started | str | None:
    """Read and label the current Findings; None when the pass is stale; the reason
    (`agent_disabled`, `too_few_agents`) when the Agent no longer runs tasks or fewer than
    two agents have Findings now."""
    ids = {"run_id": str(payload.run_id), "opportunity_id": str(payload.opportunity_id)}
    async with unit_of_work(ctx.engine) as uow:
        latest = await repo.latest_detection(uow, payload.opportunity_id)
        if latest != (payload.run_id, payload.detection_pass):
            _log.info("conflicts.semantic_stale", extra=ids)
            return None
        agent = await registry.current_config(uow, CONFLICT_AGENT)
        if not agent.runs_tasks:
            _log.info("conflicts.semantic_agent_disabled", extra=ids)
            return "agent_disabled"
        found = await assessments.current_findings(uow, payload.opportunity_id)
        if agents_with_findings(found) < 2:
            _log.info("conflicts.semantic_too_few_agents", extra=ids)
            return "too_few_agents"
        numbers = {
            s.id: s.number
            for s in await intake.active_requirement_snapshots(uow, payload.opportunity_id)
        }
        return _Started(version=agent.current, findings=label_findings(found, numbers))


async def semantic_detection(ctx: JobContext, payload: SemanticDetection) -> None:
    """The handler (see the module docstring)."""
    ids = {
        "run_id": str(payload.run_id),
        "opportunity_id": str(payload.opportunity_id),
        "job_id": str(ctx.job_id),
    }
    try:
        started = await _start(ctx, payload)
        if started is None:
            return
        if isinstance(started, str):
            await _gone_without_accept(ctx, payload)
            return
        config = registry.agent_config(started.version, semantic_settings())
        agent = ConflictAgent(provider.current(), config=config)
        result = await agent.run(_task(payload.opportunity_id, payload.run_id, started.findings))
        async with unit_of_work(ctx.engine) as uow:
            await accept_semantic_conflicts(
                uow,
                opportunity_id=payload.opportunity_id,
                run_id=payload.run_id,
                detection_pass=payload.detection_pass,
                result=result,
                findings=started.findings,
                actor=Actor(type="agent", id=config.actor_id),
            )
    except Exception as exc:
        _log.warning(
            "conflicts.semantic_failed",
            extra={
                **ids,
                "exc_type": type(exc).__name__,
                "attempt": ctx.attempt,
                "final": ctx.attempt >= ctx.max_attempts,
            },
        )
        if ctx.attempt >= ctx.max_attempts:
            try:
                await _gone_without_accept(ctx, payload)
            except Exception as gone_exc:  # never masks the original error
                _log.warning(
                    "conflicts.semantic_gone_failed",
                    extra={**ids, "exc_type": type(gone_exc).__name__},
                )
        raise


SEMANTIC_DETECTION_JOB = register(
    JobType(
        name=SEMANTIC_DETECTION,
        payload=SemanticDetection,
        handler=semantic_detection,
        priority="background",
        # Above the worst case: (1 + PSA_MODEL_MAX_RETRIES) attempts of PSA_MODEL_TIMEOUT_S
        # (3 x 120 s) for the call, plus the wait for a model slot.
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=15.0,
        backoff_cap_s=120.0,
    )
)
