"""Lineage: from an Estimate line or an Assumption back to the Findings, Evidence and human
decisions behind it (Story 9.9; FR-41, FR-42).

Read only and derived: nothing is stored and nothing is traced. Anyone who can read the
Opportunity (sales representatives included) reads it; everyone else gets the Opportunity's
404, and a line or Assumption of another Opportunity is 404 too. Other modules are read only
through their `public.py` (`assessments`, `gaps` and `reviews` lazily, inside the functions:
they import estimates' public API), and the trace through this module's repository.

**A line** (`get_line_lineage`). Lines store no Finding ids, so the chain is line ->
`estimates_line_requirements` -> the version's `source_run_id` Assessments -> the Findings and
effort entries that cite those Requirements:

- `requirements`: each covered Requirement at its cited version, with its Evidence chip;
  superseded when edited since or no longer active.
- `findings`: the specialist Findings and effort entries of the run's Assessments that cite
  them (a rerun Assessment is superseded), then the run's Critic and the version's Red Team
  Findings that cite them or the line.
- `decisions`: Conflict resolutions whose trace `line_id` is this line (or a carried
  predecessor), then the overrides and resolutions of those Critic and Red Team Findings.
- `assumptions`: the version's Contingencies linked to the line.
- `edits`: every `estimates.estimate_line.edited` event of the line and its carried
  predecessors (the line with the same section and title on an earlier version, the rule
  `carry_edits` uses), oldest first; all but the latest are superseded.
- `reviews`: Challenges targeting the version or a listed Finding or Assessment, and Review
  Decisions on the version or a listed Assessment.

**An Assumption** (`get_assumption_lineage`): origin (Gap, or Unknown by `is_unknown`) ->
Clarification Question -> answer with its Source passage -> conversion (`gaps.gap.converted`)
-> acceptance. A step that never happened is left out; a sales representative sees a
question only once it was approved or sent (`gaps.gap_lineage`).
"""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import LineRecord, TraceRecord, VersionRecord
from app.modules.estimates.application.models import (
    AssumptionLineage,
    LineageActor,
    LineageAssumption,
    LineageDecision,
    LineageEdit,
    LineageEvidence,
    LineageFinding,
    LineagePassage,
    LineageRequirement,
    LineageReview,
    LineageStep,
    LineLineage,
)
from app.modules.estimates.domain.assumptions import AssumptionKind, carried_line, origin_superseded
from app.modules.estimates.domain.estimates import Section, VersionSource
from app.modules.gaps.application import public as gaps
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Principal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform.errors import NotFoundError
from app.platform.storage import BlobStore
from app.platform.uow import UnitOfWork

LINE_NOT_FOUND = "No Estimate line with this id."
ASSUMPTION_NOT_FOUND = "No Assumption with this id."
UNKNOWN_USER = "Unknown user"
SYSTEM_NAME = "System"
SUPERSEDED_LABEL = "Superseded"
REQUIREMENT_KIND = "requirement"
SOURCE_KIND = "source_document"
CONFLICT_RESOLVED = "conflicts.conflict.resolved"
DECISION_RECORDED = "reviews.review_decision.recorded"
GAP_RAISED = "gaps.gap.raised"
GAP_CONVERTED = "gaps.gap.converted"
GAP_SUBJECT = "gaps.gap"
EXCERPT_MAX = 280
CONVERSION_LABELS = {
    "condition": "Converted to a Condition",
    "contingency": "Converted to a Contingency",
    "risk": "Converted to a Risk",
}


# --- actors ---------------------------------------------------------------------------------


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


async def trace_actors(uow: UnitOfWork, records: Iterable[TraceRecord]) -> dict[str, LineageActor]:
    """Each trace record's actor in words, keyed by `<type>:<id>`."""
    found = list(records)
    users = {
        user_id
        for r in found
        if r.actor_type == "user" and (user_id := _uuid(r.actor_id)) is not None
    }
    names = await identity.user_names(uow, users)
    actors: dict[str, LineageActor] = {}
    for r in found:
        actors[f"{r.actor_type}:{r.actor_id}"] = actor_of(r.actor_type, r.actor_id, names)
    return actors


def actor_of(actor_type: str, actor_id: str, names: dict[UUID, str]) -> LineageActor:
    """A trace actor in words: a person's name, an agent's role or "System"."""
    if actor_type == "agent":
        name, version = opportunities.agent_name(actor_id)
        return LineageActor(type="agent", id=actor_id, name=name, version=version)
    if actor_type == "user":
        user_id = _uuid(actor_id)
        name = UNKNOWN_USER if user_id is None else names.get(user_id, UNKNOWN_USER)
        return LineageActor(type="user", id=actor_id, name=name)
    return LineageActor(type="system", id=actor_id, name=SYSTEM_NAME)


def _person(user_id: UUID | str, name: str) -> LineageActor:
    return LineageActor(type="user", id=str(user_id), name=name)


def _text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) else None


# --- loading --------------------------------------------------------------------------------


async def _line(
    uow: UnitOfWork, opportunity_id: UUID, line_id: UUID
) -> tuple[LineRecord, VersionRecord]:
    line = await repo.get_line(uow, line_id)
    version = (
        None
        if line is None or line.version_id is None
        else await repo.get_version(uow, line.version_id)
    )
    if line is None or version is None or version.opportunity_id != opportunity_id:
        raise NotFoundError(LINE_NOT_FOUND)
    return line, version


async def _predecessors(
    uow: UnitOfWork, line: LineRecord, version: VersionRecord
) -> dict[UUID, int]:
    """The line and the line it was carried from on each earlier version (the one line with
    the same section and title, trimmed and case-insensitive), with their version numbers."""
    chain = {line.id: version.version}
    earlier = [
        v
        for v in await repo.versions_of(uow, version.opportunity_id)
        if v.version < version.version
    ]
    found = await repo.lines_of_versions(uow, [v.id for v in earlier])
    for v in earlier:
        candidates = [(c.id, c.section, c.title) for c in found.get(v.id, [])]
        match = carried_line(line.section, line.title, candidates)
        if match is not None:
            chain[match] = v.version
    return chain


# --- the line's sections --------------------------------------------------------------------


def _requirement_chip(
    requirement_id: str, version: int, label: str, active: dict[UUID, int], excerpt: str = ""
) -> LineageEvidence:
    current = active.get(UUID(requirement_id))
    return LineageEvidence(
        kind="requirement",
        id=requirement_id,
        version=version,
        label=label,
        superseded=current is None or current > version,
        excerpt=excerpt,
    )


async def _requirements(
    uow: UnitOfWork, opportunity_id: UUID, line: LineRecord
) -> tuple[list[LineageRequirement], dict[UUID, int]]:
    links = await repo.links_for(uow, [line.id])
    snapshots = await intake.active_requirement_snapshots(uow, opportunity_id)
    active = {s.id: s.version for s in snapshots}
    numbers = {s.id: s.number for s in snapshots}
    refs = [(link.requirement_id, link.requirement_version) for link in links]
    texts = await intake.requirement_version_texts(uow, opportunity_id, refs)
    labels = await intake.evidence_labels(
        uow, opportunity_id, [(REQUIREMENT_KIND, rid, version) for rid, version in refs]
    )
    found: list[LineageRequirement] = []
    for link in sorted(
        links,
        key=lambda k: (numbers.get(k.requirement_id, len(numbers) + 1), str(k.requirement_id)),
    ):
        rid, version = link.requirement_id, link.requirement_version
        label = labels.get((REQUIREMENT_KIND, rid, version), SUPERSEDED_LABEL)
        text = texts.get((rid, version))
        body = "" if text is None else text.text
        chip = _requirement_chip(str(rid), version, label, active, body[:EXCERPT_MAX])
        found.append(
            LineageRequirement(
                id=str(rid),
                version=version,
                label=label,
                text=body,
                active_version=active.get(rid),
                superseded=chip.superseded,
                evidence=[chip],
            )
        )
    return found, active


async def _findings(
    uow: UnitOfWork,
    version: VersionRecord,
    line: LineRecord,
    requirement_ids: set[UUID],
    active: dict[UUID, int],
) -> tuple[list[LineageFinding], list[Any]]:
    """The run's specialist Findings and effort entries citing the line's Requirements, then
    the Critic and Red Team Findings citing them or the line (also returned as they are, for
    their decisions)."""
    from app.modules.assessments.application import public as assessments

    wanted = {str(r) for r in requirement_ids}
    found: list[LineageFinding] = []
    if version.source_run_id is not None:
        snapshots = await assessments.run_assessment_snapshots(
            uow, version.opportunity_id, version.source_run_id
        )
        for snapshot in snapshots:
            view = await assessments.assessment_at(uow, snapshot.assessment_id, snapshot.version)
            if view is None:  # pragma: no cover - Assessments are never deleted
                continue
            superseded = view.status != "current"
            label = assessments.agent_role(view.agent.value)
            for f in view.findings:
                if not any(r.id in wanted for r in f.requirements):
                    continue
                found.append(
                    LineageFinding(
                        entry="finding",
                        id=f.id,
                        agent=view.agent.value,
                        agent_label=label,
                        assessment_id=view.id,
                        version=view.version,
                        title=f.title,
                        detail=f.detail,
                        severity=f.severity.value,
                        hours=None,
                        status=None,
                        created_at=view.created_at,
                        superseded=superseded,
                        evidence=[
                            _requirement_chip(r.id, r.version, r.label, active, r.excerpt)
                            for r in f.requirements
                        ],
                    )
                )
            for e in view.effort:
                if e.requirement.id not in wanted:
                    continue
                r = e.requirement
                found.append(
                    LineageFinding(
                        entry="effort",
                        id=f"{view.id}:{r.id}",
                        agent=view.agent.value,
                        agent_label=label,
                        assessment_id=view.id,
                        version=view.version,
                        title=f"{r.label} sized at {e.hours:g} h",
                        detail=e.basis,
                        severity=None,
                        hours=e.hours,
                        status=None,
                        created_at=view.created_at,
                        superseded=superseded,
                        evidence=[_requirement_chip(r.id, r.version, r.label, active, r.excerpt)],
                    )
                )
    reviewed = await assessments.linked_review_findings(
        uow,
        version.opportunity_id,
        requirement_ids=requirement_ids,
        line_ids=[line.id],
        run_id=version.source_run_id,
        estimate_version_id=version.id,
    )
    for linked in reviewed:
        found.append(
            LineageFinding(
                entry=linked.review_kind,
                id=linked.id,
                agent=linked.review_kind,
                agent_label="Critic" if linked.review_kind == "critic" else "Red Team",
                assessment_id=linked.review_id,
                version=linked.review_version,
                title=linked.title,
                detail="",
                severity=linked.severity.value,
                hours=None,
                status=linked.status.value,
                created_at=linked.review_created_at,
                superseded=linked.review_superseded,
                evidence=[
                    _requirement_chip(r.id, r.version, r.label, active, r.excerpt)
                    for r in linked.requirements
                ],
            )
        )
    return found, reviewed


async def _decisions(
    uow: UnitOfWork, opportunity_id: UUID, chain: dict[UUID, int], reviewed: list[Any]
) -> list[LineageDecision]:
    resolved = await repo.payload_events(
        uow,
        opportunity_id,
        event_type=CONFLICT_RESOLVED,
        key="line_id",
        values=[str(line_id) for line_id in chain],
    )
    actors = await trace_actors(uow, resolved)
    found: list[LineageDecision] = []
    for event in resolved:
        line_id = _uuid(event.payload.get("line_id"))
        hours = event.payload.get("applied_hours")
        found.append(
            LineageDecision(
                kind="conflict_resolved",
                subject_id=str(event.subject_id),
                title="Conflict resolved"
                if not isinstance(hours, int | float)
                else f"Conflict resolved: {hours:g} h",
                reason=_text(event.payload, "reason"),
                actor=actors[f"{event.actor_type}:{event.actor_id}"],
                at=event.occurred_at,
                version=None if line_id is None else chain.get(line_id),
                superseded=False,
            )
        )
    for f in reviewed:
        if f.override is not None:
            found.append(
                LineageDecision(
                    kind="finding_overridden",
                    subject_id=f.id,
                    title=f"Finding overridden: {f.title}",
                    reason=f.override.reason,
                    actor=_person(f.override.by.id, f.override.by.name),
                    at=f.override.at,
                    version=f.review_version,
                    superseded=f.review_superseded,
                )
            )
        if f.resolution is not None:
            found.append(
                LineageDecision(
                    kind="finding_resolved",
                    subject_id=f.id,
                    title=f"Finding resolved: {f.title}",
                    reason=f.resolution.reason,
                    actor=_person(f.resolution.by.id, f.resolution.by.name),
                    at=f.resolution.at,
                    version=f.review_version,
                    superseded=f.review_superseded,
                )
            )
    return sorted(found, key=lambda d: d.at)


async def _assumptions(
    uow: UnitOfWork, version: VersionRecord, line: LineRecord
) -> list[LineageAssumption]:
    linked = [
        a
        for a in await repo.assumptions_of(uow, version.id)
        if a.line_id == line.id and a.kind == AssumptionKind.CONTINGENCY
    ]
    names = await identity.user_names(
        uow, {a.accepted_by for a in linked if a.accepted_by is not None}
    )
    return [
        LineageAssumption(
            id=str(a.id),
            position=a.position,
            wording=a.wording,
            amount_hours=None if a.amount_hours is None else float(a.amount_hours),
            accepted_by_name=None
            if a.accepted_by is None
            else names.get(a.accepted_by, UNKNOWN_USER),
            accepted_at=a.accepted_at,
            version=version.version,
            superseded=False,
        )
        for a in linked
    ]


async def _edits(
    uow: UnitOfWork, opportunity_id: UUID, chain: dict[UUID, int]
) -> list[LineageEdit]:
    events = await repo.line_edit_events(uow, opportunity_id, list(chain))
    actors = await trace_actors(uow, events)
    found: list[LineageEdit] = []
    for n, event in enumerate(events):
        before = event.payload.get("before_hours")
        after = event.payload.get("after_hours")
        found.append(
            LineageEdit(
                line_id=str(event.subject_id),
                version=_int(event.payload, "version") or chain.get(event.subject_id, 1),
                before_hours=float(before) if isinstance(before, int | float) else 0.0,
                after_hours=float(after) if isinstance(after, int | float) else 0.0,
                reason=_text(event.payload, "reason") or "",
                actor=actors[f"{event.actor_type}:{event.actor_id}"],
                at=event.occurred_at,
                superseded=n < len(events) - 1,
            )
        )
    return found


async def _reviews(
    uow: UnitOfWork,
    version: VersionRecord,
    findings: list[LineageFinding],
) -> list[LineageReview]:
    from app.modules.reviews.application import public as reviews

    superseded_targets = {f.id for f in findings if f.superseded} | {
        f.assessment_id for f in findings if f.superseded
    }
    assessment_ids = {f.assessment_id for f in findings if f.entry in ("finding", "effort")}
    target_ids = (
        {str(version.id)} | assessment_ids | {f.id for f in findings if f.entry != "effort"}
    )
    challenges = await reviews.challenges_for(
        uow,
        version.opportunity_id,
        target_ids=[u for t in target_ids if (u := _uuid(t)) is not None],
    )
    found: list[LineageReview] = [
        LineageReview(
            kind="challenge",
            id=str(c.id),
            label=f"Challenge {reviews.CHALLENGE_STATUS_LABELS[c.status].lower()}",
            target_kind=c.target_kind.value,
            target_id=str(c.target_id),
            reason=c.reason,
            decline_reason=c.decline_reason,
            actor=_person(c.challenger_id, c.challenger_name),
            at=c.created_at,
            version=c.target_version,
            superseded=str(c.target_id) in superseded_targets,
        )
        for c in challenges
    ]
    decided = await repo.payload_events(
        uow,
        version.opportunity_id,
        event_type=DECISION_RECORDED,
        key="target_id",
        values=sorted({str(version.id)} | assessment_ids),
    )
    actors = await trace_actors(uow, decided)
    for event in decided:
        raw = _text(event.payload, "decision") or ""
        try:
            label = reviews.DECISION_LABELS[reviews.Decision(raw)]
        except ValueError:
            label = raw
        target_id = _text(event.payload, "target_id") or ""
        found.append(
            LineageReview(
                kind="review_decision",
                id=_text(event.payload, "decision_id") or str(event.id),
                label=label,
                target_kind=_text(event.payload, "target_kind") or "",
                target_id=target_id,
                reason=_text(event.payload, "reason"),
                actor=actors[f"{event.actor_type}:{event.actor_id}"],
                at=event.occurred_at,
                version=_int(event.payload, "target_version"),
                superseded=target_id in superseded_targets,
            )
        )
    return sorted(found, key=lambda r: r.at)


async def get_line_lineage(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, line_id: UUID
) -> LineLineage:
    """`estimates.get_line_lineage`: what is behind the line (module docstring)."""
    await opportunities.readable_resource(uow, actor, opportunity_id)
    line, version = await _line(uow, opportunity_id, line_id)
    requirements, active = await _requirements(uow, opportunity_id, line)
    requirement_ids = {UUID(r.id) for r in requirements}
    findings, reviewed = await _findings(uow, version, line, requirement_ids, active)
    chain = await _predecessors(uow, line, version)
    return LineLineage(
        line_id=str(line.id),
        title=line.title,
        section=Section(line.section),
        version_id=str(version.id),
        version=version.version,
        source=VersionSource(version.source),
        requirements=requirements,
        findings=findings,
        decisions=await _decisions(uow, opportunity_id, chain, reviewed),
        assumptions=await _assumptions(uow, version, line),
        edits=await _edits(uow, opportunity_id, chain),
        reviews=await _reviews(uow, version, findings),
    )


# --- an Assumption --------------------------------------------------------------------------


def _passage(passage: Any) -> LineagePassage:
    return LineagePassage(
        passage_id=passage.passage_id,
        source_id=passage.source_id,
        source_version=passage.source_version,
        filename=passage.filename,
        label=passage.label,
        excerpt=passage.excerpt,
    )


async def _finding_origin(
    uow: UnitOfWork, origin: dict[str, Any], finding_id: UUID
) -> LineageStep | None:
    """A Finding origin (`{kind: "finding", id, assessment_version?}`): its title."""
    from app.modules.assessments.application import public as assessments

    titles = await assessments.finding_titles(uow, [finding_id])
    found = titles.get(finding_id)
    if found is None:
        return None
    version = origin.get("assessment_version")
    return LineageStep(
        kind="finding",
        id=str(finding_id),
        title=found.title,
        detail=None,
        actor=None,
        at=None,
        version=version if isinstance(version, int) else None,
        superseded=False,
    )


async def _gap_steps(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    gap_id: UUID,
    made_at_row_version: object,
    store: BlobStore | None,
) -> list[LineageStep]:
    gap = await gaps.gap_lineage(uow, actor, opportunity_id, gap_id, store=store)
    if gap is None:
        return []
    events = await repo.subject_events(
        uow,
        opportunity_id,
        subject_type=GAP_SUBJECT,
        subject_ids=[gap_id],
        event_types=(GAP_RAISED, GAP_CONVERTED),
    )
    actors = await trace_actors(uow, events)
    raised = next((e for e in events if e.event_type == GAP_RAISED), None)
    steps = [
        LineageStep(
            kind="unknown" if gaps.is_unknown(gap.why_it_matters) else "gap",
            id=gap.id,
            title=gap.title,
            detail=gap.why_it_matters,
            actor=None if raised is None else actors[f"{raised.actor_type}:{raised.actor_id}"],
            at=gap.created_at,
            version=made_at_row_version if isinstance(made_at_row_version, int) else None,
            superseded=origin_superseded(gap.status, gap.row_version, made_at_row_version),
        )
    ]
    question = gap.question
    if question is not None:
        approved = question.approved_by
        steps.append(
            LineageStep(
                kind="question",
                id=question.id,
                title=question.text,
                detail=question.status.value,
                actor=None if approved is None else _person(approved.id, approved.name),
                at=question.approved_at or question.status_changed_at,
                version=question.row_version,
                superseded=False,
            )
        )
    answer = gap.answer
    if answer is not None:
        passage = answer.passage
        steps.append(
            LineageStep(
                kind="answer",
                id=passage.passage_id if passage is not None else f"{gap.id}:answer",
                title="Answer recorded" if passage is None else passage.label,
                detail=f"Answered on {answer.answered_on.isoformat()}",
                actor=_person(answer.answered_by.id, answer.answered_by.name),
                at=None,
                version=None if passage is None else passage.source_version,
                superseded=False,
                evidence=[]
                if passage is None
                else [
                    LineageEvidence(
                        kind=SOURCE_KIND,
                        id=passage.source_id,
                        version=passage.source_version,
                        label=passage.label,
                        superseded=False,
                        passage_id=passage.passage_id,
                        excerpt=passage.excerpt,
                    )
                ],
                passage=None if passage is None else _passage(passage),
            )
        )
    converted = [e for e in events if e.event_type == GAP_CONVERTED]
    if converted:
        event = converted[-1]
        kind = _text(event.payload, "assumption_kind") or ""
        steps.append(
            LineageStep(
                kind="conversion",
                id=str(event.id),
                title=CONVERSION_LABELS.get(kind, "Converted"),
                detail=None,
                actor=actors[f"{event.actor_type}:{event.actor_id}"],
                at=event.occurred_at,
                version=_int(event.payload, "row_version"),
                superseded=False,
            )
        )
    return steps


async def get_assumption_lineage(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    assumption_id: UUID,
    *,
    store: BlobStore | None = None,
) -> AssumptionLineage:
    """`estimates.get_assumption_lineage`: the Assumption's chain (module docstring)."""
    await opportunities.readable_resource(uow, actor, opportunity_id)
    assumption = await repo.get_assumption(uow, assumption_id)
    version = None if assumption is None else await repo.get_version(uow, assumption.version_id)
    if assumption is None or version is None or version.opportunity_id != opportunity_id:
        raise NotFoundError(ASSUMPTION_NOT_FOUND)
    origin = assumption.origin_ref
    origin_id = _uuid(origin.get("id"))
    steps: list[LineageStep] = []
    if origin_id is not None and origin.get("kind") == "finding":
        step = await _finding_origin(uow, origin, origin_id)
        steps.extend([] if step is None else [step])
    elif origin_id is not None:
        steps.extend(
            await _gap_steps(
                uow, actor, opportunity_id, origin_id, origin.get("row_version"), store
            )
        )
    if assumption.accepted_by is not None and assumption.accepted_at is not None:
        names = await identity.user_names(uow, {assumption.accepted_by})
        steps.append(
            LineageStep(
                kind="acceptance",
                id=str(assumption.id),
                title="Accepted",
                detail=None,
                actor=_person(
                    assumption.accepted_by, names.get(assumption.accepted_by, UNKNOWN_USER)
                ),
                at=assumption.accepted_at,
                version=version.version,
                superseded=False,
            )
        )
    return AssumptionLineage(
        assumption_id=str(assumption.id),
        version_id=str(version.id),
        version=version.version,
        kind=AssumptionKind(assumption.kind),
        wording=assumption.wording,
        steps=steps,
    )
