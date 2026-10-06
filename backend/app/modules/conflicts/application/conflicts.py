"""Conflict commands and queries (Story 6.1).

- `raise_conflict`: the single write every detector uses. Idempotent per run, detection
  pass and fingerprint: a second call for the same ones changes nothing and traces nothing.
  A new Conflict links the Opportunity's latest `open` Conflict with the same fingerprint
  from an earlier run or an earlier pass of this run (`previous_conflict_id`) and closes
  that one as carried forward (it is no longer listed).
- `detect_for_run`: at the end of an assessment run (in its Unit of Work), run the rules over
  each agent's current Assessment and the current Estimate draft as a new detection pass of
  the run (1 + the highest pass stored for it: a task retry finishes the run again), raise
  what they find, and resolve every `open` rule Conflict they no longer raise, with a reason
  naming the source that changed ("No longer present in PM Assessment v2").
- `list_open`: the Opportunity's open and escalated Conflicts (no authorization; for other
  modules).
- `get_conflicts`: the Conflicts tab (anyone who can read the Opportunity).

Trace payloads and logs carry ids, kinds and counts only, never Requirement or Finding text.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.conflicts.adapters import repository as repo
from app.modules.conflicts.adapters.repository import ConflictRecord, NewPosition, PositionRecord
from app.modules.conflicts.application.models import (
    ConflictPosition,
    ConflictRequirement,
    ConflictsView,
    ConflictView,
    OpenConflict,
)
from app.modules.conflicts.domain import rules
from app.modules.conflicts.domain.conflicts import (
    BLOCKING,
    CONFLICT_SUBJECT_TYPE,
    UNRESOLVED,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    DetectedBy,
    PositionSource,
    excerpt,
    severity_rank,
)
from app.modules.conflicts.domain.resolution import (
    CARRIED_FORWARD,
    StoredPosition,
    no_longer_present_reason,
)
from app.modules.conflicts.domain.rules import (
    ActiveRequirement,
    AssessmentSnapshot,
    ConflictCandidate,
    EstimateSnapshot,
    RuleInputs,
)
from app.modules.identity.application.public import Principal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import ConflictsConflictDetected, ConflictsConflictResolved
from app.platform.uow import UnitOfWork

INACTIVE_LABEL = "Superseded"
_SYSTEM = Actor(type="system", id="conflicts.detect_conflicts")
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RaisedConflict:
    id: UUID
    created: bool


async def raise_conflict(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    run_id: UUID,
    detection_pass: int,
    candidate: ConflictCandidate,
    detected_by: DetectedBy = DetectedBy.RULE,
    actor: Actor = _SYSTEM,
) -> RaisedConflict:
    """Store the candidate as an `open` Conflict of the run's detection pass (with its
    positions) and trace it; or, when that pass already has one with this fingerprint, return
    that one untouched."""
    existing = await repo.get_by_fingerprint(uow, run_id, detection_pass, candidate.fingerprint)
    if existing is not None:
        return RaisedConflict(existing.id, created=False)
    previous = next(
        (
            c
            for c in reversed(await repo.open_conflicts(uow, opportunity_id))
            if c.fingerprint == candidate.fingerprint
            and (c.run_id, c.detection_pass) != (run_id, detection_pass)
        ),
        None,
    )
    conflict_id = new_id()
    created = await repo.insert_conflict(
        uow,
        conflict_id=conflict_id,
        opportunity_id=opportunity_id,
        run_id=run_id,
        detection_pass=detection_pass,
        type=candidate.type.value,
        severity=candidate.severity.value,
        detected_by=detected_by.value,
        fingerprint=candidate.fingerprint,
        summary=candidate.summary,
        previous_conflict_id=None if previous is None else previous.id,
        positions=[
            NewPosition(
                source=p.source.value,
                assessment_id=p.assessment_id,
                assessment_version=p.assessment_version,
                estimate_version_id=p.estimate_version_id,
                estimate_version=p.estimate_version,
                agent=p.agent,
                value=p.value,
                requirement_id=p.requirement_id,
                requirement_version=p.requirement_version,
                summary=p.summary,
            )
            for p in candidate.positions
        ],
    )
    if not created:  # pragma: no cover - detection is serialised per Opportunity
        found = await repo.get_by_fingerprint(uow, run_id, detection_pass, candidate.fingerprint)
        assert found is not None
        return RaisedConflict(found.id, created=False)
    await trace.append(
        uow,
        actor=actor,
        payload=ConflictsConflictDetected(
            run_id=str(run_id),
            type=candidate.type.value,
            severity=candidate.severity.value,
            detected_by=detected_by.value,
            position_count=len(candidate.positions),
        ),
        subject_type=CONFLICT_SUBJECT_TYPE,
        subject_id=conflict_id,
        opportunity_id=opportunity_id,
    )
    if previous is not None and await repo.resolve(uow, previous.id, reason=CARRIED_FORWARD):
        await _trace_resolved(uow, previous, run_id, "carried_forward", actor)
    return RaisedConflict(conflict_id, created=True)


async def _trace_resolved(
    uow: UnitOfWork,
    conflict: ConflictRecord,
    run_id: UUID,
    kind: str,
    actor: Actor,
) -> None:
    await trace.append(
        uow,
        actor=actor,
        payload=ConflictsConflictResolved(
            run_id=str(run_id),
            reason_kind="carried_forward" if kind == "carried_forward" else "no_longer_present",
        ),
        subject_type=CONFLICT_SUBJECT_TYPE,
        subject_id=conflict.id,
        opportunity_id=conflict.opportunity_id,
    )


def _stored(position: PositionRecord) -> StoredPosition:
    return StoredPosition(
        source=PositionSource(position.source),
        agent=position.agent,
        assessment_version=position.assessment_version,
        estimate_version=position.estimate_version,
        requirement_id=position.requirement_id,
        summary=position.summary,
    )


async def detect_for_run(
    uow: UnitOfWork,
    opportunity_id: UUID,
    run_id: UUID,
    snapshots: Sequence[AssessmentSnapshot],
    estimate: EstimateSnapshot | None,
) -> list[UUID]:
    """Run the rules for the finished run and record the outcome (see the module docstring).
    Returns the ids of the Conflicts the rules raised in this pass."""
    await repo.lock_opportunity(uow, opportunity_id)
    detection_pass = await repo.latest_pass(uow, run_id) + 1
    active = await intake.active_requirement_snapshots(uow, opportunity_id)
    inputs = RuleInputs(
        assessments=list(snapshots),
        estimate=estimate,
        requirements=[ActiveRequirement(id=s.id, version=s.version) for s in active],
    )
    raised: list[UUID] = []
    created = 0
    for candidate in rules.detect(inputs):
        outcome = await raise_conflict(
            uow,
            opportunity_id=opportunity_id,
            run_id=run_id,
            detection_pass=detection_pass,
            candidate=candidate,
        )
        raised.append(outcome.id)
        created += outcome.created

    gone = [
        c
        for c in await repo.open_conflicts(uow, opportunity_id, detected_by=DetectedBy.RULE.value)
        if c.id not in raised
    ]
    positions: dict[UUID, list[PositionRecord]] = defaultdict(list)
    for position in await repo.positions_of(uow, [c.id for c in gone]):
        positions[position.conflict_id].append(position)
    resolved = 0
    for conflict in gone:
        reason = no_longer_present_reason(
            conflict.fingerprint, [_stored(p) for p in positions[conflict.id]], inputs
        )
        if await repo.resolve(uow, conflict.id, reason=reason):
            await _trace_resolved(uow, conflict, run_id, "no_longer_present", _SYSTEM)
            resolved += 1
    _log.info(
        "conflicts.detected",
        extra={
            "opportunity_id": str(opportunity_id),
            "run_id": str(run_id),
            "detection_pass": detection_pass,
            "raised_count": len(raised),
            "created_count": created,
            "resolved_count": resolved,
        },
    )
    return raised


async def list_open(uow: UnitOfWork, opportunity_id: UUID) -> list[OpenConflict]:
    """The Opportunity's open and escalated Conflicts, oldest first."""
    records = await repo.open_conflicts(
        uow, opportunity_id, statuses=tuple(sorted(s.value for s in BLOCKING))
    )
    return [
        OpenConflict(
            id=str(c.id),
            type=ConflictType(c.type),
            severity=ConflictSeverity(c.severity),
            status=ConflictStatus(c.status),
            summary=c.summary,
        )
        for c in records
    ]


def _order(conflict: ConflictRecord, requirement_rank: int) -> tuple[int, int, float, int, str]:
    """Open before resolved, critical to low, newest first; Conflicts of one detection (same
    time) in Requirement order, Opportunity-level ones first (`requirement_rank` 0); then id."""
    section = 0 if ConflictStatus(conflict.status) in UNRESOLVED else 1
    return (
        section,
        severity_rank(conflict.severity),
        -conflict.created_at.timestamp(),
        requirement_rank,
        str(conflict.id),
    )


async def get_conflicts(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> ConflictsView:
    await opportunities.readable_resource(uow, actor, opportunity_id)
    records = await repo.listed_conflicts(uow, opportunity_id)
    positions = await repo.positions_of(uow, [c.id for c in records])
    refs = {
        (p.requirement_id, p.requirement_version)
        for p in positions
        if p.requirement_id is not None and p.requirement_version is not None
    }
    active = {
        s.id: s.number for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    texts = await intake.requirement_version_texts(uow, opportunity_id, list(refs))
    about: dict[UUID, UUID] = {}
    for p in positions:
        if p.requirement_id is not None:
            about.setdefault(p.conflict_id, p.requirement_id)

    def requirement_rank(conflict: ConflictRecord) -> int:
        requirement_id = about.get(conflict.id)
        if requirement_id is None:
            return 0
        return active.get(requirement_id, len(active) + 1)

    records = sorted(records, key=lambda c: _order(c, requirement_rank(c)))

    def chip(requirement_id: UUID | None, version: int | None) -> ConflictRequirement | None:
        if requirement_id is None or version is None:
            return None
        number = active.get(requirement_id)
        found = texts.get((requirement_id, version))
        return ConflictRequirement(
            id=str(requirement_id),
            version=version,
            label=f"R{number}" if number is not None else INACTIVE_LABEL,
            excerpt="" if found is None else excerpt(found.text),
        )

    by_conflict: dict[UUID, list[ConflictPosition]] = defaultdict(list)
    for p in positions:
        by_conflict[p.conflict_id].append(
            ConflictPosition(
                position=p.position,
                source=PositionSource(p.source),
                agent=p.agent,
                assessment_id=None if p.assessment_id is None else str(p.assessment_id),
                assessment_version=p.assessment_version,
                estimate_version_id=None
                if p.estimate_version_id is None
                else str(p.estimate_version_id),
                estimate_version=p.estimate_version,
                summary=p.summary,
                value=None if p.value is None else float(p.value),
                requirement=chip(p.requirement_id, p.requirement_version),
            )
        )
    views: list[ConflictView] = []
    for c in records:
        own = by_conflict.get(c.id, [])
        views.append(
            ConflictView(
                id=str(c.id),
                type=ConflictType(c.type),
                severity=ConflictSeverity(c.severity),
                status=ConflictStatus(c.status),
                detected_by=DetectedBy(c.detected_by),
                summary=c.summary,
                run_id=str(c.run_id),
                previous_conflict_id=None
                if c.previous_conflict_id is None
                else str(c.previous_conflict_id),
                resolution_reason=c.resolution_reason,
                resolved_at=c.resolved_at,
                created_at=c.created_at,
                requirement=next((p.requirement for p in own if p.requirement), None),
                positions=own,
            )
        )
    open_count = sum(1 for c in records if ConflictStatus(c.status) in BLOCKING)
    return ConflictsView(conflicts=views, open_count=open_count)
