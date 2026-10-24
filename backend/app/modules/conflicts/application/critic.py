"""Contradictions the Critic found (Story 6.4): `conflicts.raise_critic_conflicts`.

`assessments.accept_critic_review` hands over, in its Unit of Work, the contradictions
`critic_agent` reported between the run's specialist Findings, with the Findings it showed
the agent by label (`F<n>`). They are validated with the semantic rules of Story 6.2
(`validate_semantic`: a known type and severity, at least two known Findings from at least
two agents, each cited Assessment still current at its cited version, no mandatory-constraint
claim, a summary and one stance per Finding of at most 240 characters, duplicate fingerprints
dropped) and each valid one is raised through `raise_conflict` with `detected_by = critic`,
the caller's actor (`critic_agent@<semver>`) and one position per cited Finding.

The fingerprint is `critic:<type>:<sorted Finding ids>`, so the Critic's Conflicts never
carry forward or resolve the Conflict Agent's (`semantic:`) or the rules'. They are stored
in a detection pass of their own (one past the run's latest), without recording it as a
detection pass (`conflicts_detections`), so the semantic job's staleness check is unchanged.
Then every `open` Critic Conflict of the Opportunity this pass did not raise is resolved as
gone, by the semantic detection's path ("No longer present in Engineering Assessment v3",
else "Not raised again by the Critic."); escalated ones stand. Never stored as Findings. Logs
carry ids, kinds and counts only.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from app.modules.conflicts.adapters import repository as repo
from app.modules.conflicts.application import findings as assessments
from app.modules.conflicts.application.conflicts import raise_conflict
from app.modules.conflicts.application.semantic import _resolve_gone, conflict_candidate
from app.modules.conflicts.domain.conflicts import ConflictType, DetectedBy
from app.modules.conflicts.domain.semantic import (
    FindingSnapshot,
    LabelledFinding,
    SemanticCandidate,
    validate_semantic,
)
from app.platform.actor import Actor
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

CRITIC_PREFIX = "critic"
NOT_RAISED_BY_CRITIC = "Not raised again by the Critic."
_log = get_logger(__name__)


def critic_fingerprint(type_: ConflictType | str, finding_ids: Sequence[UUID]) -> str:
    return f"{CRITIC_PREFIX}:{type_}:" + "+".join(sorted(str(i) for i in finding_ids))


@dataclass(frozen=True, slots=True)
class CriticConflicts:
    """What `raise_critic_conflicts` did: Conflicts raised (new or already standing),
    newly created, contradictions dropped, and earlier Critic Conflicts resolved as gone."""

    raised: int
    created: int
    dropped: int
    resolved: int = 0


async def raise_critic_conflicts(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    run_id: UUID,
    candidates: Sequence[SemanticCandidate],
    findings: Mapping[str, FindingSnapshot],
    actor: Actor,
) -> CriticConflicts:
    """Validate the Critic's contradictions and raise the valid ones as Conflicts of the run
    (module docstring). `findings`: the Findings the agent saw, by their `F<n>` label."""
    ids = {"opportunity_id": str(opportunity_id), "run_id": str(run_id)}
    await repo.lock_opportunity(uow, opportunity_id)
    labels = {label: LabelledFinding(label, f) for label, f in findings.items()}
    current = {
        s.agent: (s.assessment_id, s.version)
        for s in await assessments.current_assessments(uow, opportunity_id)
    }
    validation = validate_semantic(candidates, labels, current=current)
    detection_pass = await repo.latest_pass(uow, run_id) + 1
    raised = created = 0
    raised_ids: list[UUID] = []
    for valid in validation.conflicts:
        base = conflict_candidate(valid)
        candidate = replace(
            base,
            rule=CRITIC_PREFIX,
            fingerprint=critic_fingerprint(valid.type, valid.finding_ids),
        )
        outcome = await raise_conflict(
            uow,
            opportunity_id=opportunity_id,
            run_id=run_id,
            detection_pass=detection_pass,
            candidate=candidate,
            detected_by=DetectedBy.CRITIC,
            actor=actor,
        )
        raised += 1
        raised_ids.append(outcome.id)
        created += outcome.created
    resolved = await _resolve_gone(
        uow,
        opportunity_id,
        run_id,
        raised_ids,
        current,
        detected_by=DetectedBy.CRITIC,
        not_raised=NOT_RAISED_BY_CRITIC,
        actor=actor,
    )
    if created or resolved:
        await repo.notify_conflicts_changed(uow, opportunity_id)
    _log.info(
        "conflicts.critic_raised",
        extra={
            **ids,
            "candidate_count": len(candidates),
            "raised_count": raised,
            "created_count": created,
            "resolved_count": resolved,
            "dropped_count": validation.dropped,
            **{f"dropped_{reason}": count for reason, count in validation.reasons.items()},
        },
    )
    return CriticConflicts(
        raised=raised, created=created, dropped=validation.dropped, resolved=resolved
    )
