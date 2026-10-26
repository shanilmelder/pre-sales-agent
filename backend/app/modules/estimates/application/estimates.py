"""The Estimate query and the draft start command (Stories 8.1 and 8.4).

- `get_estimate`: the Opportunity's current Estimate Version (its `draft`, else its latest
  `submitted` one: Story 8.6, with its submission blockers and `can_submit`), with its source (a
  model draft, or the specialist Assessments of run n: Story 8.3), sections, lines, covered
  Requirements, each line's open `effort` and `scope` Conflicts (Story 8.3), its Assumptions
  Register (Conditions and Contingencies with their origin Gaps, linked lines, who accepted
  them and the version a carried one came from; the open Gaps left without one) and every
  server-calculated total, Contingency included; its latest draft run, and whether an
  assessment run is in progress (anyone who can read the Opportunity). Superseded versions
  are hidden.
- `edit_line`: a person's edit of a draft line's hours and role mix (Story 8.2; see
  `line_edits`), answered with the whole Estimate so every total refreshes.
- Story 8.5: `edit_assumption` (see `assumption_edits`), `create_risk` and `edit_risk` (see
  `risks`); the Register's rows carry their number, whether their origin Gap was superseded
  and whether it is an Unknown, and the version its Risks.
- `start_draft`: queue a new draft, e.g. to retry a failed one (`estimates.draft.start`: the
  owner and collaborators except sales representatives; other readers 403, everyone else
  the Opportunity's 404). 409 `estimate_draft_in_progress` while one is queued or running;
  one past `stale_after()` is marked failed (`model_timeout`) first, so it never blocks.
"""

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.modules.conflicts.application import public as conflicts
from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import (
    AssumptionRecord,
    DraftRecord,
    LineRecord,
    RiskRecord,
    VersionRecord,
)
from app.modules.estimates.application import assumption_edits, line_edits, risks
from app.modules.estimates.application import assumptions as assumption_commands
from app.modules.estimates.application import blockers as submission
from app.modules.estimates.application.draft import fail_stale, queue_draft, stale_after
from app.modules.estimates.application.models import (
    AcceptAllResult,
    Assumption,
    AssumptionChanges,
    AssumptionCounts,
    AssumptionGroups,
    AssumptionLine,
    CurrentEstimate,
    EstimateDraft,
    EstimateLine,
    EstimateLineChanges,
    EstimateSection,
    EstimateVersion,
    EstimateView,
    LineConflict,
    LineRequirement,
    OriginGap,
    Risk,
    RiskChanges,
    RiskCreate,
    RoleHours,
    RoleMix,
    SubmissionBlockersView,
    SubmissionVersion,
    Totals,
    UnconvertedGap,
)
from app.modules.estimates.application.versions import may_start_from
from app.modules.estimates.domain import arithmetic
from app.modules.estimates.domain.assumptions import (
    AssumptionKind,
    ProposalStatus,
    origin_superseded,
)
from app.modules.estimates.domain.estimates import (
    ESTIMATING_AGENT,
    IN_PROGRESS,
    REVIEWABLE,
    ROLES,
    DraftErrorCode,
    DraftStatus,
    EstimateRole,
    Section,
    VersionSource,
    VersionStatus,
)
from app.modules.estimates.domain.risks import RiskLevel, risk_order
from app.modules.gaps.application import public as gaps
from app.modules.gaps.application.public import GapCategory, GapSummary, Impact
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.modules.opportunities.application.public import UserRef
from app.modules.registry.application import public as registry
from app.platform.errors import EstimateDraftInProgressError
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

IN_PROGRESS_DETAIL = "An Estimate is already being drafted for this Opportunity."
EXCERPT_MAX = 140
INACTIVE_LABEL = "Superseded"
UNKNOWN_USER = "Unknown user"
FINISHED_PROPOSALS = frozenset({ProposalStatus.SUCCEEDED, ProposalStatus.FAILED})
_log = get_logger(__name__)


def excerpt(text: str, limit: int = EXCERPT_MAX) -> str:
    """At most `limit` code points of `text` on one line, cut at whitespace where possible,
    ending in `…` when cut."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def _draft(record: DraftRecord | None) -> EstimateDraft | None:
    """The read model of the latest draft. One still queued or running past `stale_after()`
    is lost: it reads as failed with `model_timeout`, so it can be retried (`start_draft`
    records that)."""
    if record is None:
        return None
    lost = (
        DraftStatus(record.status) in IN_PROGRESS
        and datetime.now(UTC) - record.created_at > stale_after()
    )
    if lost:
        return EstimateDraft(status=DraftStatus.FAILED, error_code=DraftErrorCode.MODEL_TIMEOUT)
    return EstimateDraft(
        status=DraftStatus(record.status),
        error_code=None if record.error_code is None else DraftErrorCode(record.error_code),
    )


def _hours(value: Decimal) -> float:
    return float(value)


def _role_hours(hours: Mapping[EstimateRole, Decimal]) -> RoleHours:
    return RoleHours(
        engineer=_hours(hours[EstimateRole.ENGINEER]),
        project_manager=_hours(hours[EstimateRole.PROJECT_MANAGER]),
        qa=_hours(hours[EstimateRole.QA]),
    )


def _totals(totals: arithmetic.Totals) -> Totals:
    return Totals(
        effort_hours=_hours(totals.effort),
        contingency_hours=_hours(totals.contingency),
        total_hours=_hours(totals.total),
        role_hours=_role_hours(totals.role_hours),
    )


def _mix(raw: Mapping[str, object]) -> dict[EstimateRole, int]:
    mix: dict[EstimateRole, int] = {}
    for role in ROLES:
        share = raw.get(role.value, 0)
        mix[role] = share if isinstance(share, int) else 0
    return mix


async def _requirements(
    uow: UnitOfWork, opportunity_id: UUID, lines: list[LineRecord]
) -> dict[UUID, list[LineRequirement]]:
    links = await repo.links_for(uow, [line.id for line in lines])
    active = {
        s.id: s.number for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    texts = await intake.requirement_version_texts(
        uow,
        opportunity_id,
        list({(link.requirement_id, link.requirement_version) for link in links}),
    )
    related: dict[UUID, list[tuple[int, LineRequirement]]] = defaultdict(list)
    for link in links:
        number = active.get(link.requirement_id)
        found = texts.get((link.requirement_id, link.requirement_version))
        related[link.line_id].append(
            (
                number if number is not None else len(active) + 1,
                LineRequirement(
                    id=str(link.requirement_id),
                    version=link.requirement_version,
                    label=f"R{number}" if number is not None else INACTIVE_LABEL,
                    excerpt="" if found is None else excerpt(found.text),
                ),
            )
        )
    return {
        line_id: [r for _, r in sorted(items, key=lambda pair: (pair[0], pair[1].id))]
        for line_id, items in related.items()
    }


def _gap_id(record: AssumptionRecord | RiskRecord) -> UUID:
    return UUID(str(record.origin_ref["id"]))


def _superseded(summary: GapSummary | None, record: AssumptionRecord | RiskRecord) -> bool:
    """Story 8.5: whether the origin Gap moved on since the record was made from it."""
    if summary is None:  # pragma: no cover - Gaps are never deleted
        return True
    return origin_superseded(
        summary.status, summary.row_version, record.origin_ref.get("row_version")
    )


def _origin(summary: GapSummary | None, gap_id: UUID) -> OriginGap:
    if summary is None:  # pragma: no cover - Gaps are never deleted
        return OriginGap(
            id=str(gap_id),
            title="",
            category=GapCategory.OTHER,
            impact=Impact.LOW,
            why_it_matters="",
            status="superseded",
        )
    status: Literal["open", "converted", "superseded"] = (
        "open"
        if summary.status == "open"
        else "converted"
        if summary.status == "converted"
        else "superseded"
    )
    return OriginGap(
        id=str(summary.id),
        title=summary.title,
        category=GapCategory(summary.category),
        impact=Impact(summary.impact),
        why_it_matters=summary.why_it_matters,
        status=status,
    )


async def _conflicts(
    uow: UnitOfWork, opportunity_id: UUID, covered: Mapping[UUID, list[LineRequirement]]
) -> dict[UUID, list[LineConflict]]:
    """Story 8.3: each line's open `effort` and `scope` Conflicts about a Requirement it
    covers, read now."""
    by_requirement = await conflicts.open_by_requirement(uow, opportunity_id)
    if not by_requirement:
        return {}
    markers: dict[UUID, list[LineConflict]] = {}
    for line_id, requirements in covered.items():
        seen: dict[UUID, LineConflict] = {}
        for requirement in requirements:
            for found in by_requirement.get(UUID(requirement.id), []):
                seen.setdefault(found.id, LineConflict(id=str(found.id), type=found.type))
        if seen:
            markers[line_id] = list(seen.values())
    return markers


async def _run_number(uow: UnitOfWork, record: VersionRecord) -> int | None:
    """Story 8.3: the number of the assessment run a version from the Assessments was built
    for (a Workflow Run, Story 5.2). Imported here, not at the top: workflows imports
    `estimates.application.public`, which imports this module, so a top-level import would
    be circular."""
    if record.source_run_id is None:
        return None
    from app.modules.workflows.application import public as workflows

    return await workflows.run_number(uow, record.opportunity_id, record.source_run_id)


async def _assessment_running(uow: UnitOfWork, opportunity_id: UUID) -> bool:
    """Story 8.3: whether an assessment run is queued or running (imported here for the
    same reason as in `_run_number`)."""
    from app.modules.workflows.application import public as workflows

    return await workflows.run_in_progress(uow, opportunity_id)


async def _register(
    uow: UnitOfWork,
    record: VersionRecord,
    lines: list[LineRecord],
    assumptions: list[AssumptionRecord],
) -> tuple[AssumptionGroups, AssumptionCounts, list[UnconvertedGap]]:
    """The version's Assumptions Register: its Assumptions by kind, their counts, and the
    open Gaps without one (once proposals have finished)."""
    origins = await gaps.gap_summaries(
        uow, record.opportunity_id, list({_gap_id(a) for a in assumptions})
    )
    names = await identity.user_names(
        uow, {a.accepted_by for a in assumptions if a.accepted_by is not None}
    )
    sources = await repo.carried_from_versions(
        uow, [a.carried_from for a in assumptions if a.carried_from is not None]
    )
    titles = {line.id: line.title for line in lines}
    conditions: list[Assumption] = []
    contingencies: list[Assumption] = []
    for a in assumptions:
        gap_id = _gap_id(a)
        summary = origins.get(gap_id)
        view = Assumption(
            id=str(a.id),
            position=a.position,
            kind=AssumptionKind(a.kind),
            wording=a.wording,
            amount_hours=None if a.amount_hours is None else _hours(a.amount_hours),
            line=None
            if a.line_id is None
            else AssumptionLine(id=str(a.line_id), title=titles.get(a.line_id, "")),
            origin_kind="gap",
            origin=_origin(summary, gap_id),
            origin_superseded=_superseded(summary, a),
            origin_is_unknown=summary is not None and gaps.is_unknown(summary.why_it_matters),
            accepted_by=None
            if a.accepted_by is None
            else UserRef(id=str(a.accepted_by), name=names.get(a.accepted_by, UNKNOWN_USER)),
            accepted_at=a.accepted_at,
            row_version=a.row_version,
            carried_from_version=None if a.carried_from is None else sources.get(a.carried_from),
        )
        (conditions if view.kind is AssumptionKind.CONDITION else contingencies).append(view)
    accepted = sum(1 for a in assumptions if a.accepted_at is not None)
    unconverted: list[UnconvertedGap] = []
    status = None if record.proposal_status is None else ProposalStatus(record.proposal_status)
    if status in FINISHED_PROPOSALS:
        covered = set(origins)
        unconverted = [
            UnconvertedGap(
                id=str(g.id),
                title=g.title,
                category=GapCategory(g.category),
                impact=Impact(g.impact),
            )
            for g in await gaps.open_gap_summaries(uow, record.opportunity_id)
            if g.id not in covered
        ]
    groups = AssumptionGroups(
        conditions=conditions,
        contingencies=contingencies,
        contingency_hours=_hours(
            arithmetic.line_contingency(
                a.amount_hours for a in assumptions if a.amount_hours is not None
            )
        ),
    )
    counts = AssumptionCounts(
        total=len(assumptions), accepted=accepted, not_accepted=len(assumptions) - accepted
    )
    return groups, counts, unconverted


async def _risks(uow: UnitOfWork, record: VersionRecord) -> list[Risk]:
    """Story 8.5: the version's Risks, impact high first, then likelihood high first."""
    found = sorted(
        await repo.risks_of(uow, record.id),
        key=lambda r: risk_order(r.impact, r.likelihood, r.position),
    )
    if not found:
        return []
    origins = await gaps.gap_summaries(
        uow, record.opportunity_id, list({_gap_id(r) for r in found})
    )
    sources = await repo.risk_carried_from_versions(
        uow, [r.carried_from for r in found if r.carried_from is not None]
    )
    views: list[Risk] = []
    for r in found:
        gap_id = _gap_id(r)
        summary = origins.get(gap_id)
        views.append(
            Risk(
                id=str(r.id),
                position=r.position,
                description=r.description,
                likelihood=RiskLevel(r.likelihood),
                impact=RiskLevel(r.impact),
                origin_kind="gap",
                origin=_origin(summary, gap_id),
                origin_superseded=_superseded(summary, r),
                row_version=r.row_version,
                carried_from_version=None
                if r.carried_from is None
                else sources.get(r.carried_from),
            )
        )
    return views


def _calculate(
    lines: list[LineRecord], assumptions: list[AssumptionRecord]
) -> tuple[list[arithmetic.LineInput], arithmetic.EstimateTotals]:
    """The lines' arithmetic inputs and every total, each Contingency amount (accepted or
    not) counted on its line, or as unallocated when it is linked to none."""
    linked: dict[UUID, list[Decimal]] = defaultdict(list)
    unallocated: list[Decimal] = []
    for a in assumptions:
        if a.amount_hours is None:
            continue
        if a.line_id is None:
            unallocated.append(a.amount_hours)
        else:
            linked[a.line_id].append(a.amount_hours)
    inputs = [
        arithmetic.LineInput(
            section=Section(line.section),
            effort=line.effort_hours,
            mix=_mix(line.role_mix),
            contingencies=tuple(linked.get(line.id, ())),
        )
        for line in lines
    ]
    return inputs, arithmetic.estimate_totals(inputs, unallocated)


async def version_view(uow: UnitOfWork, record: VersionRecord) -> EstimateVersion:
    """The version with its sections, lines, covered Requirements, its Assumptions Register
    and every total."""
    lines = await repo.lines_of(uow, record.id)
    covered = await _requirements(uow, record.opportunity_id, lines)
    assumptions = await repo.assumptions_of(uow, record.id)
    inputs, calculated = _calculate(lines, assumptions)
    groups, counts, unconverted = await _register(uow, record, lines, assumptions)
    editors = await identity.user_names(
        uow, {line.edited_by for line in lines if line.edited_by is not None}
    )
    markers = await _conflicts(uow, record.opportunity_id, covered)
    by_section: dict[Section, list[EstimateLine]] = defaultdict(list)
    for line, given, totals in zip(lines, inputs, calculated.lines, strict=True):
        by_section[given.section].append(
            EstimateLine(
                id=str(line.id),
                position=line.position,
                section=given.section,
                title=line.title,
                basis=line.basis,
                role_mix=RoleMix(
                    engineer=given.mix[EstimateRole.ENGINEER],
                    project_manager=given.mix[EstimateRole.PROJECT_MANAGER],
                    qa=given.mix[EstimateRole.QA],
                ),
                effort_hours=_hours(totals.effort),
                contingency_hours=_hours(totals.contingency),
                total_hours=_hours(totals.total),
                role_hours=_role_hours(totals.role_hours),
                requirements=covered.get(line.id, []),
                row_version=line.row_version,
                edited=line.edited_at is not None,
                edited_by_name=None
                if line.edited_by is None
                else editors.get(line.edited_by, UNKNOWN_USER),
                edited_at=line.edited_at,
                edit_reason=line.edit_reason,
                edit_carried_from_version=line.edit_carried_from_version,
                conflicts=markers.get(line.id, []),
            )
        )
    return EstimateVersion(
        id=str(record.id),
        version=record.version,
        status=VersionStatus(record.status),
        template_version=record.template_version,
        roles=list(ROLES),
        uncovered_count=record.uncovered_count,
        dropped_count=record.dropped_count,
        row_version=record.row_version,
        created_at=record.created_at,
        sections=[
            EstimateSection(
                section=section,
                lines=by_section[section],
                subtotal=_totals(subtotal),
            )
            for section, subtotal in calculated.sections.items()
        ],
        totals=_totals(calculated.overall),
        proposal_status=None
        if record.proposal_status is None
        else ProposalStatus(record.proposal_status),
        assumptions=groups,
        counts=counts,
        unconverted_gaps=unconverted,
        unallocated_contingency_hours=_hours(calculated.unallocated),
        risks=await _risks(uow, record),
        uncarried_edit_count=record.uncarried_edit_count,
        # The superseded draft is always the version just before (Story 8.1 numbering).
        uncarried_edits_from_version=record.version - 1 if record.uncarried_edit_count else None,
        source=VersionSource(record.source),
        source_run=await _run_number(uow, record),
        submitted_at=record.submitted_at,
    )


async def current_estimates(
    uow: UnitOfWork, opportunity_ids: list[UUID]
) -> dict[UUID, CurrentEstimate]:
    """Each of these Opportunities' current `draft` Estimate Version number and its total
    hours, Contingency included (the same as `get_estimate`'s `totals.total_hours`), for
    the Opportunity list. No authorization (the caller lists only Opportunities the actor
    may read). Three queries whatever the count; ones with no draft are left out."""
    versions = await repo.current_versions(uow, opportunity_ids)
    if not versions:
        return {}
    version_ids = [v.id for v in versions.values()]
    lines = await repo.lines_of_versions(uow, version_ids)
    assumptions = await repo.assumptions_of_versions(uow, version_ids)
    found: dict[UUID, CurrentEstimate] = {}
    for opportunity_id, version in versions.items():
        _, calculated = _calculate(lines.get(version.id, []), assumptions.get(version.id, []))
        found[opportunity_id] = CurrentEstimate(
            version=version.version,
            status=VersionStatus(version.status),
            total_hours=_hours(calculated.overall.total),
        )
    return found


def _may_submit(actor: Principal, resource: Resource, record: VersionRecord | None) -> bool:
    return (
        record is not None
        and record.status == VersionStatus.DRAFT
        and identity.can(actor, Action.ESTIMATE_VERSION_SUBMIT, resource)
    )


async def get_estimate(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> EstimateView:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    record, blockers = await submission.current_blockers(uow, opportunity_id)
    return EstimateView(
        version=None if record is None else await version_view(uow, record),
        draft=_draft(await repo.latest_draft(uow, opportunity_id)),
        can_start_draft=identity.can(actor, Action.ESTIMATE_DRAFT_START, resource),
        can_accept_assumptions=identity.can(actor, Action.ASSUMPTION_ACCEPT, resource),
        can_export=identity.can(actor, Action.ESTIMATE_EXPORT, resource),
        can_edit_lines=identity.can(actor, Action.ESTIMATE_LINE_EDIT, resource),
        can_edit_assumptions=identity.can(actor, Action.ASSUMPTION_EDIT, resource),
        can_create_risks=identity.can(actor, Action.RISK_CREATE, resource),
        can_edit_risks=identity.can(actor, Action.RISK_EDIT, resource),
        assessment_running=await _assessment_running(uow, opportunity_id),
        blockers=blockers,
        can_submit=_may_submit(actor, resource, record),
        can_request_review=record is not None
        and VersionStatus(record.status) in REVIEWABLE
        and identity.can(actor, Action.REVIEW_REQUEST_CREATE, resource),
        # Story 9.4: the current version is a draft whenever one exists, so a current version
        # that isn't one means there is none.
        can_create_version=record is not None
        and VersionStatus(record.status) != VersionStatus.DRAFT
        and identity.can(actor, Action.ESTIMATE_VERSION_CREATE, resource)
        and await may_start_from(uow, record.id, VersionStatus(record.status)),
    )


async def submission_blockers_view(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> SubmissionBlockersView:
    """Story 8.6: the Opportunity's current Estimate Version and its submission blockers,
    for the Overview card and the header (anyone who can read the Opportunity)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    record, blockers = await submission.current_blockers(uow, opportunity_id)
    return SubmissionBlockersView(
        to_submit=blockers.to_submit,
        to_baseline=blockers.to_baseline,
        version=None
        if record is None
        else SubmissionVersion(
            id=str(record.id),
            version=record.version,
            status=VersionStatus(record.status),
            row_version=record.row_version,
            created_at=record.created_at,
            submitted_at=record.submitted_at,
        ),
        can_submit=_may_submit(actor, resource, record),
    )


async def start_draft(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> EstimateDraft:
    """Queue a new Estimate draft of the Opportunity (the Retry of a failed one)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ESTIMATE_DRAFT_START, resource)
    await registry.require_enabled(uow, ESTIMATING_AGENT)  # 409 while it is disabled
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    busy = await repo.draft_in(uow, opportunity_id, tuple(s.value for s in IN_PROGRESS))
    if busy is not None:
        raise EstimateDraftInProgressError(IN_PROGRESS_DETAIL)
    draft_id = await queue_draft(uow, opportunity_id, requested_by=actor.user_id)
    _log.info(
        "estimates.draft_started",
        extra={
            "opportunity_id": str(opportunity_id),
            "draft_id": str(draft_id),
            "actor_id": actor.actor.id,
        },
    )
    return EstimateDraft(status=DraftStatus.QUEUED, error_code=None)


async def accept_assumption(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    assumption_id: UUID,
    if_match: str | None,
) -> Assumption:
    """Accept one Assumption of the current draft as the caller (Story 8.4); the Assumption
    as the Register shows it now."""
    record = await assumption_commands.accept_assumption(
        uow, actor, opportunity_id, assumption_id, if_match
    )
    version = await repo.current_version(uow, opportunity_id)
    assert version is not None  # the Assumption belongs to it
    lines = await repo.lines_of(uow, version.id)
    groups, _, _ = await _register(uow, version, lines, [record])
    (view,) = groups.conditions + groups.contingencies
    return view


async def accept_all_assumptions(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> AcceptAllResult:
    """Accept every unaccepted Assumption of the current draft as the caller (Story 8.4)."""
    return AcceptAllResult(
        count=await assumption_commands.accept_all_assumptions(uow, actor, opportunity_id)
    )


async def edit_line(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    line_id: UUID,
    changes: EstimateLineChanges,
    if_match: str | None,
) -> EstimateView:
    """Edit a line of the current draft's effort and/or role mix with a reason (Story 8.2);
    the Estimate as it is now, every total recalculated."""
    await line_edits.edit_line(uow, actor, opportunity_id, line_id, changes, if_match)
    return await get_estimate(uow, actor, opportunity_id)


async def edit_assumption(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    assumption_id: UUID,
    changes: AssumptionChanges,
    if_match: str | None,
) -> EstimateView:
    """Edit an Assumption of the current draft with a reason (Story 8.5); the Estimate as it
    is now, every total recalculated."""
    await assumption_edits.edit_assumption(
        uow, actor, opportunity_id, assumption_id, changes, if_match
    )
    return await get_estimate(uow, actor, opportunity_id)


async def create_risk(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, body: RiskCreate
) -> Risk:
    """Convert an open Gap to a Risk of the current draft (Story 8.5); the Risk as the
    Estimate shows it."""
    record = await risks.create_risk(uow, actor, opportunity_id, body)
    version = await repo.get_version(uow, record.version_id)
    assert version is not None  # the Risk belongs to it
    return next(r for r in await _risks(uow, version) if r.id == str(record.id))


async def edit_risk(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    risk_id: UUID,
    changes: RiskChanges,
    if_match: str | None,
) -> EstimateView:
    """Edit a Risk of the current draft with a reason (Story 8.5); the Estimate as it is
    now."""
    await risks.edit_risk(uow, actor, opportunity_id, risk_id, changes, if_match)
    return await get_estimate(uow, actor, opportunity_id)
