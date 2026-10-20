"""Conflict commands and queries (Stories 6.1 and 6.3).

- `raise_conflict`: the single write every detector uses. Idempotent per run, detection
  pass and fingerprint: a second call for the same ones changes nothing and traces nothing.
  It looks at the Opportunity's latest Conflict with the same fingerprint from an earlier
  run or an earlier pass of this run:
  - `open`: the new Conflict links it (`previous_conflict_id`) and closes it as carried
    forward (it is no longer listed);
  - `escalated` (Story 6.3): nothing new is raised while every Assessment position reads as
    it did then; once one reads differently, a new Conflict with the fresh positions is
    raised already escalated to the same reviewer (same reason, by and at), links it, and
    closes it as carried forward;
  - resolved by a person (Story 6.3, the decision stands): nothing new is raised while every
    Assessment position reads as it did then (Estimate positions are not compared); once
    one reads differently, a new `open` Conflict links the resolved one, which stays listed;
  - resolved by the system, or none: a new, unlinked `open` Conflict.
- `detect_for_run`: at the end of an assessment run (in its Unit of Work), run the rules over
  each agent's current Assessment and the current Estimate draft as a new detection pass of
  the run (1 + the highest pass recorded for it: a task retry finishes the run again; the
  pass is recorded even when it raises nothing, Story 6.2), raise what they find, and
  resolve every `open` or `escalated` rule Conflict they no longer raise, with a reason
  naming the source that changed ("No longer present in PM Assessment v2"). Semantic
  Conflicts (Story 6.2, `semantic.py`) are left alone.
- Every write that changes what the Conflicts tab shows also sends `conflicts.changed` on
  the Opportunity's event stream (Story 6.2; delivered on commit, ids only).
- `list_open`: the Opportunity's open and escalated Conflicts (no authorization; for other
  modules).
- `open_by_requirement`: its open and escalated `effort` and `scope` Conflicts by Requirement
  (no authorization; Story 8.3, the Estimate's Open Conflict markers).
- `get_conflicts`: the Conflicts tab (anyone who can read the Opportunity), with what the
  viewer may do on each Conflict and whom they may escalate to.

Detection's trace payloads and logs carry ids, kinds and counts only, never Requirement or
Finding text. A person's decision is in `decisions.py`.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.conflicts.adapters import repository as repo
from app.modules.conflicts.adapters.repository import ConflictRecord, NewPosition, PositionRecord
from app.modules.conflicts.application import findings as assessment_findings
from app.modules.conflicts.application.models import (
    ConflictFinding,
    ConflictPosition,
    ConflictRequirement,
    ConflictsView,
    ConflictView,
    OpenConflict,
    Person,
    PreviousDecision,
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
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import ConflictsConflictDetected, ConflictsConflictResolved
from app.platform.uow import UnitOfWork

INACTIVE_LABEL = "Superseded"
UNKNOWN_PERSON = "Someone"
_SYSTEM = Actor(type="system", id="conflicts.detect_conflicts")
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RequirementConflict:
    """An open or escalated Conflict about a Requirement: its id and type."""

    id: UUID
    type: ConflictType


@dataclass(frozen=True, slots=True)
class RaisedConflict:
    id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class Detection:
    """What a rule detection did: its detection pass of the run and the Conflicts it
    raised."""

    detection_pass: int
    raised: list[UUID]


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
    latest = await repo.latest_with_fingerprint(
        uow, opportunity_id, candidate.fingerprint, besides=(run_id, detection_pass)
    )
    previous: ConflictRecord | None = None
    if latest is not None:
        if latest.status == ConflictStatus.ESCALATED:
            if await _reads_the_same(uow, latest, candidate):
                return RaisedConflict(latest.id, created=False)  # the escalation stands
            previous = latest  # re-raised with the fresh positions, still escalated
        elif latest.decided:
            if await _reads_the_same(uow, latest, candidate):
                return RaisedConflict(latest.id, created=False)  # the decision stands
            previous = latest
        elif latest.status == ConflictStatus.OPEN:
            previous = latest
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
        escalation=previous
        if previous is not None and previous.status == ConflictStatus.ESCALATED
        else None,
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
                finding_id=p.finding_id,
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
    if (
        previous is not None
        and previous.status in (ConflictStatus.OPEN, ConflictStatus.ESCALATED)
        and await repo.resolve(uow, previous.id, reason=CARRIED_FORWARD)
    ):
        await _trace_resolved(uow, previous, run_id, "carried_forward", actor)
    return RaisedConflict(conflict_id, created=True)


def _assessment_reads(summaries: Sequence[tuple[str, str | None, str]]) -> list[tuple[str, str]]:
    """The Assessment positions as sorted (agent, summary) pairs."""
    return sorted(
        (agent or "", summary)
        for source, agent, summary in summaries
        if source == PositionSource.ASSESSMENT
    )


async def _reads_the_same(
    uow: UnitOfWork, decided: ConflictRecord, candidate: ConflictCandidate
) -> bool:
    """Whether every Assessment position of the candidate reads as it did when a person
    resolved `decided` (the Estimate's positions are not compared)."""
    stored = await repo.positions_of(uow, [decided.id])
    return _assessment_reads([(p.source, p.agent, p.summary) for p in stored]) == _assessment_reads(
        [(p.source.value, p.agent, p.summary) for p in candidate.positions]
    )


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
) -> Detection:
    """Run the rules for the finished run and record the outcome (see the module docstring).
    Returns the detection pass (recorded, Story 6.2) and the ids of the Conflicts the rules
    raised in it."""
    await repo.lock_opportunity(uow, opportunity_id)
    detection_pass = await repo.latest_pass(uow, run_id) + 1
    await repo.record_detection(
        uow, opportunity_id=opportunity_id, run_id=run_id, detection_pass=detection_pass
    )
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
        for c in await repo.open_conflicts(
            uow,
            opportunity_id,
            statuses=tuple(sorted(s.value for s in BLOCKING)),
            detected_by=DetectedBy.RULE.value,
        )
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
    if created or resolved:
        await repo.notify_conflicts_changed(uow, opportunity_id)  # Story 6.2: live tab
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
    return Detection(detection_pass=detection_pass, raised=raised)


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


REQUIREMENT_TYPES = frozenset({ConflictType.EFFORT, ConflictType.SCOPE})
"""The Conflict types marked on the Estimate lines covering their Requirement (Story 8.3)."""


async def open_by_requirement(
    uow: UnitOfWork, opportunity_id: UUID
) -> dict[UUID, list[RequirementConflict]]:
    """The Opportunity's open and escalated `effort` and `scope` Conflicts by the Requirement
    their positions cite (Story 8.3: the Estimate's Open Conflict markers), oldest first. No
    authorization; for other modules."""
    records = [
        c
        for c in await repo.open_conflicts(
            uow, opportunity_id, statuses=tuple(sorted(s.value for s in BLOCKING))
        )
        if c.type in REQUIREMENT_TYPES
    ]
    by_id = {c.id: c for c in records}
    found: dict[UUID, list[RequirementConflict]] = defaultdict(list)
    for p in await repo.positions_of(uow, list(by_id)):
        if p.requirement_id is None:
            continue
        conflict = by_id[p.conflict_id]
        marker = RequirementConflict(id=conflict.id, type=ConflictType(conflict.type))
        if marker not in found[p.requirement_id]:
            found[p.requirement_id].append(marker)
    order = {c.id: n for n, c in enumerate(records)}
    return {rid: sorted(items, key=lambda m: order[m.id]) for rid, items in found.items()}


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


def _listed(everything: Sequence[ConflictRecord]) -> list[ConflictRecord]:
    """Leave out the Conflicts carried forward (a newer Conflict links them), except one a
    person resolved (Story 6.3: it stays listed)."""
    linked = {c.previous_conflict_id for c in everything if c.previous_conflict_id is not None}
    return [c for c in everything if c.id not in linked or c.decided]


def _previous_decision(
    conflict: ConflictRecord, by_id: dict[UUID, ConflictRecord]
) -> ConflictRecord | None:
    """The Conflict a person resolved that this one was raised again after, following the
    links through Conflicts carried forward since."""
    seen: set[UUID] = set()
    previous_id = conflict.previous_conflict_id
    while previous_id is not None and previous_id not in seen:
        seen.add(previous_id)
        previous = by_id.get(previous_id)
        if previous is None:
            return None
        if previous.decided:
            return previous
        previous_id = previous.previous_conflict_id
    return None


def may_resolve(actor: Principal, resource: Resource, conflict: ConflictRecord) -> bool:
    """`conflicts.conflict.resolve` on the Opportunity, or the reviewer an escalated
    Conflict was escalated to; only while it is `open` or `escalated`."""
    status = ConflictStatus(conflict.status)
    if status not in BLOCKING:
        return False
    if status == ConflictStatus.ESCALATED and actor.user_id is not None:
        if actor.user_id == conflict.escalated_to:
            return True
    return identity.can(actor, Action.CONFLICT_RESOLVE, resource)


def may_escalate(actor: Principal, resource: Resource, conflict: ConflictRecord) -> bool:
    """`conflicts.conflict.escalate` on the Opportunity, while the Conflict is `open`."""
    return conflict.status == ConflictStatus.OPEN and identity.can(
        actor, Action.CONFLICT_ESCALATE, resource
    )


def reviewer_ids(resource: Resource, viewer: UUID | None) -> set[UUID]:
    """Whom a Conflict may be escalated to: the Opportunity's owner and collaborators, other
    than the viewer."""
    people = set(resource.member_ids)
    if resource.owner_id is not None:
        people.add(resource.owner_id)
    if viewer is not None:
        people.discard(viewer)
    return people


async def get_conflicts(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> ConflictsView:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    return await conflicts_view(uow, actor, resource, opportunity_id)


async def conflicts_view(
    uow: UnitOfWork, actor: Principal, resource: Resource, opportunity_id: UUID
) -> ConflictsView:
    """The Conflicts tab for a viewer who may read the Opportunity (`resource`)."""
    everything = await repo.all_conflicts(uow, opportunity_id)
    by_id = {c.id: c for c in everything}
    records = _listed(everything)
    # Only an unresolved Conflict says it was resolved earlier (a decided one is its own).
    previous_decisions = {
        c.id: _previous_decision(c, by_id) if ConflictStatus(c.status) in UNRESOLVED else None
        for c in records
    }
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
    titles = await assessment_findings.finding_titles(
        uow, sorted({p.finding_id for p in positions if p.finding_id is not None}, key=str)
    )
    reviewers = reviewer_ids(resource, actor.user_id)
    people: set[UUID] = set(reviewers)
    for c in records:
        people.update(u for u in (c.resolved_by, c.escalated_to, c.escalated_by) if u is not None)
        decided = previous_decisions[c.id]
        if decided is not None and decided.resolved_by is not None:
            people.add(decided.resolved_by)
    names = await identity.user_names(uow, people)
    not_applied = await repo.not_applied_kinds(
        uow, [c.id for c in records if c.decided and c.type == ConflictType.EFFORT]
    )
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

    def name(user_id: UUID | None) -> str | None:
        if user_id is None:
            return None
        return names.get(user_id, UNKNOWN_PERSON)

    def finding(finding_id: UUID | None) -> ConflictFinding | None:
        found = None if finding_id is None else titles.get(finding_id)
        if found is None:
            return None
        return ConflictFinding(id=str(found.id), title=found.title, kind=found.kind)

    def person(user_id: UUID | None) -> Person | None:
        if user_id is None:
            return None
        return Person(id=str(user_id), name=names.get(user_id, UNKNOWN_PERSON))

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
                finding=finding(p.finding_id),
            )
        )
    views: list[ConflictView] = []
    for c in records:
        own = by_conflict.get(c.id, [])
        decided = previous_decisions[c.id]
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
                row_version=c.row_version,
                resolved_by_name=name(c.resolved_by),
                chosen_position=c.chosen_position,
                entered_position=c.entered_position,
                applied_hours=None if c.applied_hours is None else float(c.applied_hours),
                not_applied=not_applied.get(c.id),
                previous_decision=None
                if decided is None or decided.resolved_at is None
                else PreviousDecision(
                    name=name(decided.resolved_by) or UNKNOWN_PERSON,
                    resolved_at=decided.resolved_at,
                ),
                escalated_to=person(c.escalated_to),
                escalated_by=person(c.escalated_by),
                escalation_reason=c.escalation_reason,
                escalated_at=c.escalated_at,
                can_resolve=may_resolve(actor, resource, c),
                can_escalate=may_escalate(actor, resource, c) and bool(reviewers),
            )
        )
    open_count = sum(1 for c in records if ConflictStatus(c.status) in BLOCKING)
    return ConflictsView(
        conflicts=views,
        open_count=open_count,
        reviewers=sorted(
            (Person(id=str(u), name=names.get(u, UNKNOWN_PERSON)) for u in reviewers),
            key=lambda p: (p.name.casefold(), p.id),
        ),
    )
