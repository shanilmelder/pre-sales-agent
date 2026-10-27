"""Recording and correcting Actuals (Story 10.1; AD-11, AD-13, FR-49).

`save_actuals` (**Save Actuals**, action `actuals.actual.record`, plus `actuals.actual.correct`
when an entry corrects an Actual) and `correct_actual` (`actuals.actual.correct`) follow the
single mutation path, in one Unit of Work:

1. `opportunities.readable_resource` (404 unless the caller can read the Opportunity), then
   `identity.authorize`: delivery managers only, people only (403 for everyone else).
2. The Opportunity's shared lock (`platform.locks.opportunity_lock`).
3. `If-Match`: the tab's `row_version` for Save Actuals (it grows with every Actual version
   and delivery, so any concurrent write is 412), the Actual's `version` for a correction
   (412 when stale or no longer current); 428 without.
4. Rules: a Baseline must exist (409 `actuals_no_baseline`) and delivery must be open (409
   `delivery_closed`); then every entry is checked (`domain.actuals.validate`, the line and
   catalogue references, failed Assumptions from the Actual's own Baseline version register)
   and every broken rule is returned at once as 422 `actual_invalid` with `errors`. A
   correction needs a reason (1 to 1,000 characters).
5. Writes: a new Actual is version 1 of a new group; a correction clears `is_current` on the
   version it replaces and inserts the next version with the reason. Each write appends its
   trace event (`actuals.actual.recorded` or `.corrected`).

Nothing is written on any error. A line's Actual stores the Integration Types of the line's
Requirements and no Work Package; Unplanned work stores the Integration Type or Work Package
the delivery manager picked.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.modules.actuals.adapters import repository as repo
from app.modules.actuals.adapters.repository import ActualRecord, NewActual
from app.modules.actuals.application.models import (
    ActualCorrection,
    ActualFields,
    ActualInput,
    ActualsSave,
    SavedActuals,
)
from app.modules.actuals.application.view import (
    Baseline,
    build_view,
    line_integration_types,
    load_baseline,
)
from app.modules.actuals.domain.actuals import (
    ACTUAL_SUBJECT_TYPE,
    REASON_MAX,
    ActualDraft,
    clean_reason,
    clean_text,
    tenths,
    validate,
)
from app.modules.estimates.application import public as estimates
from app.modules.estimates.application.public import AssumptionRef, LineRef
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.knowledge.application import public as knowledge
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ActualInvalidError,
    ActualsNoBaselineError,
    DeliveryClosedError,
    ForbiddenError,
    NotFoundError,
    RowVersionMismatchError,
)
from app.platform.ids import new_id
from app.platform.locks import opportunity_lock
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    ActualsActualCorrected,
    ActualsActualRecorded,
    FailedAssumptionRef,
)
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
STALE = "Actuals changed since you opened them. Reload and try again."
NOT_FOUND = "No Actual with this id."
NO_BASELINE = "No Baseline yet. Actuals are recorded against the Baseline."
CLOSED = "Delivery is closed, so Actuals no longer change."
INVALID = "Some Actuals could not be saved. Check the highlighted fields."
REASON_RULE = f"Corrections need a reason of 1 to {REASON_MAX:,} characters."
NOT_A_LINE = "This line isn't part of the Baseline v{version}."
DUPLICATE_LINE = "Each line can be entered once."
DUPLICATE_ACTUAL = "Each Actual can be corrected once per save."
UNKNOWN_ASSUMPTION = "Failed Assumptions must come from the Baseline v{version} register."
UNKNOWN_ENTRY = "Choose an active {label} from the catalogue."
NOT_UNPLANNED = "This Actual isn't Unplanned work."
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Plan:
    """One checked entry, ready to write."""

    index: int | None
    fields: ActualFields
    line: LineRef | None
    existing: ActualRecord | None
    estimate_version_id: UUID
    estimate_version: int


def _error(index: int | None, field: str, message: str) -> dict[str, Any]:
    return {"item": index, "field": field, "message": message}


def _decimal(value: int | float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:  # pragma: no cover - JSON numbers always convert
        return Decimal("NaN")


async def _catalogue_ok(
    uow: UnitOfWork, entry_id: UUID | None, kind: knowledge.Kind, previous: UUID | None
) -> bool:
    """A picked entry of the right kind; a newly picked one must be active."""
    if entry_id is None:
        return True
    entry = await knowledge.get_catalogue_entry(uow, entry_id)
    if entry is None or entry.kind != kind:
        return False
    return entry_id == previous or await knowledge.validate_catalogue_ref(uow, entry_id)


async def _check(
    uow: UnitOfWork, plan: _Plan, register: Mapping[UUID, AssumptionRef]
) -> tuple[list[dict[str, Any]], list[tuple[UUID, int]]]:
    """Every rule the entry breaks, and its failed-Assumption refs at their versions."""
    f, i = plan.fields, plan.index
    errors: list[dict[str, Any]] = []
    unplanned = plan.line is None
    previous_it = (
        None
        if plan.existing is None or not plan.existing.integration_type_ids
        else plan.existing.integration_type_ids[0]
    )
    previous_wp = None if plan.existing is None else plan.existing.work_package_id
    if unplanned:
        if not await _catalogue_ok(
            uow, f.integration_type_id, knowledge.Kind.INTEGRATION_TYPE, previous_it
        ):
            errors.append(
                _error(i, "integration_type_id", UNKNOWN_ENTRY.format(label="Integration Type"))
            )
        if not await _catalogue_ok(
            uow, f.work_package_id, knowledge.Kind.WORK_PACKAGE, previous_wp
        ):
            errors.append(_error(i, "work_package_id", UNKNOWN_ENTRY.format(label="Work Package")))
    draft = ActualDraft(
        kind=f.kind,
        effort_hours=_decimal(f.effort_hours) or Decimal(0),
        estimate_hours=None if plan.line is None else plan.line.effort_hours,
        cause=f.variance_cause,
        note=f.note,
        milestone_label=f.milestone_label,
        duration_days=_decimal(f.duration_days),
        cost_minor=f.cost_minor,
        currency=None if f.currency is None else f.currency.strip(),
        has_catalogue_ref=f.integration_type_id is not None or f.work_package_id is not None,
    )
    errors.extend(_error(i, e.field, e.message) for e in validate(draft))
    refs: list[tuple[UUID, int]] = []
    for assumption_id in dict.fromkeys(f.failed_assumption_ids):
        found = register.get(assumption_id)
        if found is None:
            errors.append(
                _error(
                    i,
                    "failed_assumption_ids",
                    UNKNOWN_ASSUMPTION.format(version=plan.estimate_version),
                )
            )
            break
        refs.append((found.id, found.version))
    return errors, refs


def _failed_refs(refs: list[tuple[UUID, int]]) -> list[FailedAssumptionRef]:
    return [FailedAssumptionRef(assumption_id=str(a), version=v) for a, v in refs]


async def _write(
    uow: UnitOfWork,
    actor: Principal,
    user_id: UUID,
    opportunity_id: UUID,
    plan: _Plan,
    refs: list[tuple[UUID, int]],
    line_types: Mapping[UUID, list[UUID]],
    reason: str | None,
) -> ActualRecord:
    f, existing = plan.fields, plan.existing
    if existing is not None and not await repo.retire(uow, existing.id):
        raise RowVersionMismatchError(STALE)  # pragma: no cover - the lock serialises writes
    if plan.line is None:
        integration_types = [] if f.integration_type_id is None else [f.integration_type_id]
        work_package = f.work_package_id
    else:
        integration_types = list(line_types.get(plan.line.id, []))
        work_package = None
    effort = _decimal(f.effort_hours)
    assert effort is not None
    stored = await repo.insert_actual(
        uow,
        NewActual(
            id=new_id(),
            opportunity_id=opportunity_id,
            estimate_version_id=plan.estimate_version_id,
            estimate_line_id=None if plan.line is None else plan.line.id,
            actual_group_id=new_id() if existing is None else existing.actual_group_id,
            version=1 if existing is None else existing.version + 1,
            kind=f.kind.value,
            effort_hours=tenths(effort),
            recorded_by=user_id,
            integration_type_ids=integration_types,
            work_package_id=work_package,
            milestone_label=clean_text(f.milestone_label),
            duration_days=_decimal(f.duration_days),
            cost_minor=f.cost_minor,
            currency=None if f.currency is None else f.currency.strip(),
            variance_cause=None if f.variance_cause is None else f.variance_cause.value,
            failed_assumptions=refs,
            note=clean_text(f.note),
            correction_reason=None if existing is None else reason,
        ),
    )
    common: dict[str, Any] = {
        "actual_id": str(stored.id),
        "group_id": str(stored.actual_group_id),
        "version": stored.version,
        "estimate_version_id": str(plan.estimate_version_id),
        "estimate_version": plan.estimate_version,
        "line_id": None if plan.line is None else str(plan.line.id),
        "kind": stored.kind,
        "effort_hours": f"{stored.effort_hours:.1f}",
        "duration_days": None if stored.duration_days is None else f"{stored.duration_days:.1f}",
        "cost_minor": stored.cost_minor,
        "currency": stored.currency,
        "milestone_label": stored.milestone_label,
        "integration_type_ids": [str(i) for i in stored.integration_type_ids],
        "work_package_id": None if stored.work_package_id is None else str(stored.work_package_id),
        "variance_cause": stored.variance_cause,
        "failed_assumptions": _failed_refs(refs),
    }
    if existing is None:
        payload: ActualsActualRecorded | ActualsActualCorrected = ActualsActualRecorded(**common)
    else:
        assert reason is not None
        payload = ActualsActualCorrected(
            **common,
            previous_actual_id=str(existing.id),
            previous_version=existing.version,
            reason=reason,
        )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=payload,
        subject_type=ACTUAL_SUBJECT_TYPE,
        subject_id=stored.id,
        opportunity_id=opportunity_id,
        subject_version=stored.version,
    )
    return stored


async def start_write(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, action: Action
) -> tuple[Resource, UUID]:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, action, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - HUMAN_ONLY_ACTIONS denies every non-person
        raise ForbiddenError("Only people can record Actuals.")
    await opportunity_lock(uow, opportunity_id)
    return resource, user_id


async def open_baseline(uow: UnitOfWork, opportunity_id: UUID) -> Baseline:
    if await repo.get_delivery(uow, opportunity_id) is not None:
        raise DeliveryClosedError(CLOSED)
    baseline = await load_baseline(uow, opportunity_id)
    if baseline is None:
        raise ActualsNoBaselineError(NO_BASELINE)
    return baseline


async def _line_type_ids(uow: UnitOfWork, lines: list[LineRef]) -> dict[UUID, list[UUID]]:
    types = await line_integration_types(uow, lines)
    return {line_id: [UUID(t.id) for t in refs] for line_id, refs in types.items()}


@dataclass(frozen=True, slots=True)
class CheckedItems:
    """Entries checked against the current state: every broken rule (`errors`, each
    `{item, field, message}` with `item` the entry's index), and the entries ready to write,
    each with its failed-Assumption refs and its correction reason."""

    errors: list[dict[str, Any]]
    plans: list[tuple[_Plan, list[tuple[UUID, int]], str | None]]

    @property
    def corrected(self) -> int:
        return sum(1 for plan, _, _ in self.plans if plan.existing is not None)

    @property
    def recorded(self) -> int:
        return len(self.plans) - self.corrected


def _reasons(
    plans: list[_Plan],
    reason: str | None,
    item_reasons: Sequence[str | None] | None,
    errors: list[dict[str, Any]],
) -> dict[int, str | None]:
    """Each correcting entry's reason by index; a missing or too-long one is an error."""
    batch = clean_reason(reason)
    found: dict[int, str | None] = {}
    corrections = [p for p in plans if p.existing is not None and p.index is not None]
    if item_reasons is None:
        if corrections and batch is None:
            errors.append(_error(None, "reason", REASON_RULE))
        return {p.index: batch for p in corrections if p.index is not None}
    for plan in corrections:
        assert plan.index is not None
        raw = item_reasons[plan.index] if plan.index < len(item_reasons) else None
        own = clean_reason(raw)
        if (clean_text(raw) is not None and own is None) or (own is None and batch is None):
            errors.append(_error(plan.index, "reason", REASON_RULE))
        found[plan.index] = own or batch
    return found


async def check_items(
    uow: UnitOfWork,
    actor: Principal,
    resource: Resource,
    opportunity_id: UUID,
    baseline: Baseline,
    items: Sequence[ActualInput],
    reason: str | None,
    *,
    item_reasons: Sequence[str | None] | None = None,
) -> CheckedItems:
    """Check entries against the Opportunity's current Actuals and the Baseline, as **Save
    Actuals** does, without writing anything. A correction needs a reason: `reason` for the
    whole batch, or (Story 10.2, an import) the entry's own `item_reasons[i]`, falling back to
    `reason`. Without `item_reasons` a missing reason is one error with no item."""
    current = await repo.actuals_of(uow, opportunity_id, current_only=True)
    by_line = {r.estimate_line_id: r for r in current if r.estimate_line_id is not None}
    by_id = {r.id: r for r in current}

    errors: list[dict[str, Any]] = []
    plans: list[_Plan] = []
    seen: set[UUID] = set()
    for index, item in enumerate(items):
        line: LineRef | None = None
        existing: ActualRecord | None = None
        if item.line_id is not None:
            line = baseline.line(item.line_id)
            if line is None:
                errors.append(_error(index, "line_id", NOT_A_LINE.format(version=baseline.version)))
                continue
            if line.id in seen:
                errors.append(_error(index, "line_id", DUPLICATE_LINE))
                continue
            seen.add(line.id)
            existing = by_line.get(line.id)
            if item.actual_id is not None and (existing is None or existing.id != item.actual_id):
                raise RowVersionMismatchError(STALE)
        elif item.actual_id is not None:
            if item.actual_id in seen:
                errors.append(_error(index, "actual_id", DUPLICATE_ACTUAL))
                continue
            seen.add(item.actual_id)
            existing = by_id.get(item.actual_id)
            if existing is None:
                stored = await repo.get_actual(uow, item.actual_id)
                if stored is not None and stored.opportunity_id == opportunity_id:
                    raise RowVersionMismatchError(STALE)
                errors.append(_error(index, "actual_id", NOT_FOUND))
                continue
            if existing.estimate_line_id is not None:
                errors.append(_error(index, "actual_id", NOT_UNPLANNED))
                continue
        version_id = baseline.version_id if existing is None else existing.estimate_version_id
        number = baseline.version
        if version_id != baseline.version_id:  # Unplanned work recorded on an older Baseline
            older = await estimates.version_lines(uow, opportunity_id, version_id)
            number = 0 if older is None else older.version
        plans.append(
            _Plan(
                index=index,
                fields=item,
                line=line,
                existing=existing,
                estimate_version_id=version_id,
                estimate_version=number,
            )
        )

    if any(p.existing is not None for p in plans):
        identity.authorize(actor, Action.ACTUAL_CORRECT, resource)
    reasons = _reasons(plans, reason, item_reasons, errors)
    registers: dict[UUID, dict[UUID, AssumptionRef]] = {
        baseline.version_id: {a.id: a for a in baseline.assumptions}
    }
    checked: list[tuple[_Plan, list[tuple[UUID, int]], str | None]] = []
    for plan in plans:
        if plan.estimate_version_id not in registers:  # an Unplanned Actual on an older version
            registers[plan.estimate_version_id] = {
                a.id: a for a in await estimates.version_assumptions(uow, plan.estimate_version_id)
            }
        found, refs = await _check(uow, plan, registers[plan.estimate_version_id])
        errors.extend(found)
        plan_reason = None if plan.index is None else reasons.get(plan.index)
        checked.append((plan, refs, plan_reason))
    return CheckedItems(errors=errors, plans=checked)


async def apply_items(
    uow: UnitOfWork,
    actor: Principal,
    resource: Resource,
    user_id: UUID,
    opportunity_id: UUID,
    items: Sequence[ActualInput],
    reason: str | None,
    *,
    item_reasons: Sequence[str | None] | None = None,
    read_errors: Sequence[dict[str, Any]] = (),
    describe: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> CheckedItems:
    """The one validate-and-write path of **Save Actuals** and an import's **Confirm** (Story
    10.2), under the caller's lock: a Baseline and open delivery, then `check_items`, then 422
    `actual_invalid` with every broken rule, or every entry written with its trace event.
    Nothing is written on any error. An import adds the problems found reading its rows
    (`read_errors`) and words the rule errors for its rows (`describe`)."""
    baseline = await open_baseline(uow, opportunity_id)
    checked = await check_items(
        uow, actor, resource, opportunity_id, baseline, items, reason, item_reasons=item_reasons
    )
    errors = [*read_errors, *(checked.errors if describe is None else describe(checked.errors))]
    if errors:
        _log.info(
            "actuals.save_invalid",
            extra={"opportunity_id": str(opportunity_id), "error_count": len(errors)},
        )
        raise ActualInvalidError(INVALID, errors=errors)
    line_types = await _line_type_ids(uow, baseline.lines)
    for plan, refs, plan_reason in checked.plans:
        await _write(uow, actor, user_id, opportunity_id, plan, refs, line_types, plan_reason)
    return checked


async def save_actuals(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    body: ActualsSave,
    if_match: str | None,
) -> SavedActuals:
    """`actuals.save_actuals`: **Save Actuals** (module docstring)."""
    resource, user_id = await start_write(uow, actor, opportunity_id, Action.ACTUAL_RECORD)
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or expected != await repo.change_count(uow, opportunity_id):
        raise RowVersionMismatchError(STALE)
    checked = await apply_items(
        uow, actor, resource, user_id, opportunity_id, body.items, body.reason
    )
    _log.info(
        "actuals.saved",
        extra={
            "opportunity_id": str(opportunity_id),
            "recorded": checked.recorded,
            "corrected": checked.corrected,
            "actor_id": actor.actor.id,
        },
    )
    return SavedActuals(
        recorded=checked.recorded,
        corrected=checked.corrected,
        view=await build_view(uow, actor, resource, opportunity_id),
    )


async def correct_actual(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    actual_id: UUID,
    body: ActualCorrection,
    if_match: str | None,
) -> SavedActuals:
    """`actuals.correct_actual`: a new version of one Actual (module docstring). It stays
    tied to the Estimate Version it was recorded against."""
    resource, user_id = await start_write(uow, actor, opportunity_id, Action.ACTUAL_CORRECT)
    existing = await repo.get_actual(uow, actual_id)
    if existing is None or existing.opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND)
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or not existing.is_current or existing.version != expected:
        raise RowVersionMismatchError(STALE)
    await open_baseline(uow, opportunity_id)
    version = await estimates.version_lines(uow, opportunity_id, existing.estimate_version_id)
    assert version is not None  # an Actual keys one of the Opportunity's versions
    line = None
    if existing.estimate_line_id is not None:
        line = next((x for x in version.lines if x.id == existing.estimate_line_id), None)
        assert line is not None
    plan = _Plan(
        index=None,
        fields=body,
        line=line,
        existing=existing,
        estimate_version_id=existing.estimate_version_id,
        estimate_version=version.version,
    )
    register = {
        a.id: a for a in await estimates.version_assumptions(uow, existing.estimate_version_id)
    }
    errors, refs = await _check(uow, plan, register)
    reason = clean_reason(body.reason)
    if reason is None:
        errors.append(_error(None, "reason", REASON_RULE))
    if errors:
        raise ActualInvalidError(INVALID, errors=list(errors))
    line_types = {} if line is None else await _line_type_ids(uow, [line])
    await _write(uow, actor, user_id, opportunity_id, plan, refs, line_types, reason)
    _log.info(
        "actuals.corrected",
        extra={
            "opportunity_id": str(opportunity_id),
            "actual_id": str(actual_id),
            "actor_id": actor.actor.id,
        },
    )
    return SavedActuals(
        recorded=0,
        corrected=1,
        view=await build_view(uow, actor, resource, opportunity_id),
    )
