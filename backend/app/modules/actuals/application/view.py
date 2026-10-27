"""The Actuals tab's read model (Story 10.1): `get_actuals`.

Anyone who can read the Opportunity sees it (404 otherwise); `can_record` and `can_close` are
true only for a delivery manager (`identity`). The lines are the current Baseline version's,
labelled "L{n}" in grid order, each with its current Actual and server-calculated variance;
lines with no Actual are left out of the totals. Unplanned work recorded against the Baseline
version counts in the totals with an estimate of 0. Actuals recorded against an earlier
Baseline version stay tied to it and are reported in `version_mismatch`.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.actuals.adapters import repository as repo
from app.modules.actuals.adapters.repository import ActualRecord
from app.modules.actuals.application.models import (
    ActualsBaseline,
    ActualsLine,
    ActualsTotals,
    ActualsView,
    ActualVersionView,
    ActualView,
    AssumptionOption,
    CatalogueRef,
    CauseOption,
    DeliveryView,
    FailedAssumption,
    VarianceView,
    VersionMismatch,
)
from app.modules.actuals.domain.actuals import (
    CAUSE_LABELS,
    UNPLANNED_CAUSES,
    ActualKind,
    Variance,
    VarianceCause,
    open_line_count,
    open_lines_message,
    total_variance,
    variance,
)
from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.public import AssumptionRef, LineRef
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.intake.application import public as intake
from app.modules.knowledge.application import public as knowledge
from app.modules.opportunities.application import public as opportunities
from app.platform.uow import UnitOfWork

UNKNOWN_USER = "Unknown user"
CLOSED_REASON = "Delivery is closed."


def mismatch_message(recorded: list[int], baseline: int) -> str:
    """E.g. "Actuals recorded against v3; the current Baseline is v5"."""
    versions = ", ".join(f"v{v}" for v in recorded)
    return f"Actuals recorded against {versions}; the current Baseline is v{baseline}"


def _hours(value: Decimal) -> float:
    return float(value)


def variance_view(v: Variance) -> VarianceView:
    return VarianceView(
        hours=float(v.hours),
        percent=None if v.percent is None else float(v.percent),
        direction=v.direction,
        label=v.label,
        direction_label=v.direction_label,
    )


@dataclass(frozen=True, slots=True)
class Baseline:
    """The current Baseline as Actuals need it: its version and lines (grid order) and its
    Assumptions Register."""

    version_id: UUID
    version: int
    set_at: datetime
    lines: list[LineRef]
    assumptions: list[AssumptionRef]

    def line(self, line_id: UUID) -> LineRef | None:
        return next((line for line in self.lines if line.id == line_id), None)


async def load_baseline(uow: UnitOfWork, opportunity_id: UUID) -> Baseline | None:
    """The Opportunity's current Baseline with its lines and register, or None."""
    ref = await estimates.current_baseline_ref(uow, opportunity_id)
    if ref is None:
        return None
    version_id = UUID(ref.version_id)
    lines = await estimates.version_lines(uow, opportunity_id, version_id)
    assert lines is not None  # a Baseline row keys one of the Opportunity's versions
    return Baseline(
        version_id=version_id,
        version=ref.version,
        set_at=ref.set_at,
        lines=lines.lines,
        assumptions=await estimates.version_assumptions(uow, version_id),
    )


async def catalogue_refs(uow: UnitOfWork, ids: set[UUID]) -> dict[UUID, CatalogueRef]:
    """The catalogue entries behind these ids (retired ones still resolve)."""
    found: dict[UUID, CatalogueRef] = {}
    for entry_id in sorted(ids, key=str):
        entry = await knowledge.get_catalogue_entry(uow, entry_id)
        if entry is not None:
            kind = (
                "work_package" if entry.kind == knowledge.Kind.WORK_PACKAGE else "integration_type"
            )
            found[entry_id] = CatalogueRef(id=entry.id, kind=kind, name=entry.name)
    return found


async def line_integration_types(
    uow: UnitOfWork, lines: list[LineRef]
) -> dict[UUID, list[CatalogueRef]]:
    """Each line's Integration Types: those its Requirements are tagged with, deduplicated in
    tag order."""
    tagged = await intake.integration_types_by_requirement(
        uow, [r for line in lines for r in line.requirement_ids]
    )
    found: dict[UUID, list[CatalogueRef]] = {}
    for line in lines:
        seen: dict[str, CatalogueRef] = {}
        for requirement_id in line.requirement_ids:
            for t in tagged.get(requirement_id, []):
                seen.setdefault(t.id, CatalogueRef(id=t.id, kind="integration_type", name=t.name))
        found[line.id] = list(seen.values())
    return found


def _failed(
    record: ActualRecord, registers: dict[UUID, dict[UUID, AssumptionRef]]
) -> list[FailedAssumption]:
    register = registers.get(record.estimate_version_id, {})
    out: list[FailedAssumption] = []
    for assumption_id, version in record.failed_assumptions:
        found = register.get(assumption_id)
        out.append(
            FailedAssumption(
                assumption_id=str(assumption_id),
                version=version,
                kind="" if found is None else found.kind,
                wording="" if found is None else found.wording,
            )
        )
    return out


def _version_view(
    record: ActualRecord,
    names: dict[UUID, str],
    registers: dict[UUID, dict[UUID, AssumptionRef]],
) -> ActualVersionView:
    return ActualVersionView(
        id=str(record.id),
        version=record.version,
        kind=ActualKind(record.kind),
        milestone_label=record.milestone_label,
        effort_hours=_hours(record.effort_hours),
        duration_days=None if record.duration_days is None else _hours(record.duration_days),
        cost_minor=record.cost_minor,
        currency=record.currency,
        variance_cause=None
        if record.variance_cause is None
        else VarianceCause(record.variance_cause),
        note=record.note,
        failed_assumptions=_failed(record, registers),
        correction_reason=record.correction_reason,
        recorded_by_name=names.get(record.recorded_by, UNKNOWN_USER),
        recorded_at=record.recorded_at,
    )


@dataclass(frozen=True, slots=True)
class ViewContext:
    """What every Actual view needs: names, registers by version id, version numbers by id,
    catalogue entries, and each group's earlier versions (newest first)."""

    names: dict[UUID, str]
    registers: dict[UUID, dict[UUID, AssumptionRef]]
    version_numbers: dict[UUID, int]
    catalogue: dict[UUID, CatalogueRef]
    history: dict[UUID, list[ActualRecord]]


async def view_context(
    uow: UnitOfWork, opportunity_id: UUID, records: list[ActualRecord]
) -> ViewContext:
    version_ids = {r.estimate_version_id for r in records}
    registers: dict[UUID, dict[UUID, AssumptionRef]] = {}
    numbers: dict[UUID, int] = {}
    for version_id in sorted(version_ids, key=str):
        registers[version_id] = {
            a.id: a for a in await estimates.version_assumptions(uow, version_id)
        }
        lines = await estimates.version_lines(uow, opportunity_id, version_id)
        numbers[version_id] = 0 if lines is None else lines.version
    history: dict[UUID, list[ActualRecord]] = defaultdict(list)
    for r in sorted(records, key=lambda r: -r.version):
        if not r.is_current:
            history[r.actual_group_id].append(r)
    catalogue_ids = {i for r in records for i in r.integration_type_ids} | {
        r.work_package_id for r in records if r.work_package_id is not None
    }
    return ViewContext(
        names=await identity.user_names(uow, {r.recorded_by for r in records}),
        registers=registers,
        version_numbers=numbers,
        catalogue=await catalogue_refs(uow, catalogue_ids),
        history=dict(history),
    )


def actual_view(
    record: ActualRecord, estimate_hours: Decimal | None, context: ViewContext
) -> ActualView:
    """The current version of an Actual; `estimate_hours` is its line's (None for Unplanned
    work, which varies against 0)."""
    base = _version_view(record, context.names, context.registers)
    return ActualView(
        **base.model_dump(),
        group_id=str(record.actual_group_id),
        line_id=None if record.estimate_line_id is None else str(record.estimate_line_id),
        estimate_version_id=str(record.estimate_version_id),
        estimate_version=context.version_numbers.get(record.estimate_version_id, 0),
        integration_types=[
            context.catalogue[i] for i in record.integration_type_ids if i in context.catalogue
        ],
        work_package=None
        if record.work_package_id is None
        else context.catalogue.get(record.work_package_id),
        variance=variance_view(variance(estimate_hours or Decimal(0), record.effort_hours)),
        history=[
            _version_view(h, context.names, context.registers)
            for h in context.history.get(record.actual_group_id, [])
        ],
    )


def causes() -> list[CauseOption]:
    return [
        CauseOption(value=c, label=CAUSE_LABELS[c], unplanned=c in UNPLANNED_CAUSES)
        for c in VarianceCause
    ]


def _empty(row_version: int) -> ActualsView:
    return ActualsView(
        baseline=None,
        lines=[],
        unplanned=[],
        totals=ActualsTotals(
            estimate_hours=0,
            actual_hours=0,
            variance=None,
            recorded_line_count=0,
            line_count=0,
            unplanned_count=0,
        ),
        assumptions=[],
        causes=causes(),
        open_line_count=0,
        close_blocked_reason=None,
        can_record=False,  # nothing can be recorded without a Baseline
        can_close=False,
        delivery=None,
        version_mismatch=None,
        row_version=row_version,
    )


async def build_view(
    uow: UnitOfWork, actor: Principal, resource: Resource, opportunity_id: UUID
) -> ActualsView:
    """The tab for an actor who may read the Opportunity (module docstring)."""
    can_record = identity.can(actor, Action.ACTUAL_RECORD, resource)
    row_version = await repo.change_count(uow, opportunity_id)
    baseline = await load_baseline(uow, opportunity_id)
    if baseline is None:
        return _empty(row_version)
    delivery_record = await repo.get_delivery(uow, opportunity_id)
    if delivery_record is not None and delivery_record.estimate_version_id != baseline.version_id:
        # Closed delivery keeps showing the version it was closed on, even after a later
        # Baseline.
        closed = await estimates.version_lines(
            uow, opportunity_id, delivery_record.estimate_version_id
        )
        assert closed is not None  # a delivery row keys one of the Opportunity's versions
        baseline = Baseline(
            version_id=closed.version_id,
            version=closed.version,
            set_at=baseline.set_at,
            lines=closed.lines,
            assumptions=await estimates.version_assumptions(uow, closed.version_id),
        )

    records = await repo.actuals_of(uow, opportunity_id)
    current = [r for r in records if r.is_current]
    context = await view_context(uow, opportunity_id, records)
    by_line = {r.estimate_line_id: r for r in current if r.estimate_line_id is not None}
    types = await line_integration_types(uow, baseline.lines)

    lines: list[ActualsLine] = []
    pairs: list[tuple[Decimal, Decimal]] = []
    kinds: list[ActualKind | None] = []
    for number, line in enumerate(baseline.lines, start=1):
        record = by_line.get(line.id)
        view = None if record is None else actual_view(record, line.effort_hours, context)
        if record is not None:
            pairs.append((line.effort_hours, record.effort_hours))
        kinds.append(None if record is None else ActualKind(record.kind))
        lines.append(
            ActualsLine(
                line_id=str(line.id),
                label=f"L{number}",
                title=line.title,
                section=line.section,
                estimate_hours=_hours(line.effort_hours),
                integration_types=types.get(line.id, []),
                actual=view,
                variance=None if view is None else view.variance,
            )
        )
    unplanned_records = [
        r
        for r in current
        if r.estimate_line_id is None and r.estimate_version_id == baseline.version_id
    ]
    unplanned = [actual_view(r, None, context) for r in unplanned_records]
    pairs.extend((Decimal(0), r.effort_hours) for r in unplanned_records)
    total = total_variance(pairs)

    others = [r for r in current if r.estimate_version_id != baseline.version_id]
    mismatch = None
    if others:
        recorded = sorted({context.version_numbers.get(r.estimate_version_id, 0) for r in others})
        mismatch = VersionMismatch(
            recorded_versions=recorded,
            baseline_version=baseline.version,
            actual_count=len(others),
            message=mismatch_message(recorded, baseline.version),
        )

    delivery = None
    if delivery_record is not None:
        closer = await identity.user_names(uow, {delivery_record.closed_by})
        closed_lines = await estimates.version_lines(
            uow, opportunity_id, delivery_record.estimate_version_id
        )
        delivery = DeliveryView(
            closed_at=delivery_record.closed_at,
            closed_by_name=closer.get(delivery_record.closed_by, UNKNOWN_USER),
            estimate_version=0 if closed_lines is None else closed_lines.version,
        )
    open_count = open_line_count(kinds)
    if delivery is not None:
        blocked: str | None = CLOSED_REASON
    elif open_count:
        blocked = open_lines_message(open_count)
    else:
        blocked = None

    return ActualsView(
        baseline=ActualsBaseline(
            version_id=str(baseline.version_id),
            version=baseline.version,
            set_at=baseline.set_at,
        ),
        lines=lines,
        unplanned=unplanned,
        totals=ActualsTotals(
            estimate_hours=_hours(sum((e for e, _ in pairs), Decimal(0))),
            actual_hours=_hours(sum((a for _, a in pairs), Decimal(0))),
            variance=None if total is None else variance_view(total),
            recorded_line_count=len(by_line.keys() & {line.id for line in baseline.lines}),
            line_count=len(baseline.lines),
            unplanned_count=len(unplanned),
        ),
        assumptions=[
            AssumptionOption(
                id=str(a.id),
                kind=a.kind,
                wording=a.wording,
                version=a.version,
                line_id=None if a.line_id is None else str(a.line_id),
            )
            for a in baseline.assumptions
        ],
        causes=causes(),
        open_line_count=open_count,
        close_blocked_reason=blocked,
        can_record=can_record and delivery is None,
        can_close=identity.can(actor, Action.DELIVERY_CLOSE, resource) and blocked is None,
        delivery=delivery,
        version_mismatch=mismatch,
        row_version=row_version,
    )


async def get_actuals(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> ActualsView:
    """`actuals.get_actuals`: the Actuals tab (module docstring)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    return await build_view(uow, actor, resource, opportunity_id)
