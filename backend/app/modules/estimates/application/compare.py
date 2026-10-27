"""Reading one Estimate Version for review, and comparing it with the one before (Story 9.3).

- `version_detail`: the version as the Estimate tab shows it (lines, server totals,
  Assumptions Register and Risks), whatever its status. No authorization: `reviews` reads it
  for a Review Request the caller may see.
- `compare_versions`: a minimal line diff against the version numbered just before. Lines
  are matched by section and title (trimmed, case-insensitive, as a re-draft carries edits);
  when several lines share a key they pair in position order.
- `compare_any` (Story 9.9; FR-42): any two of the Opportunity's versions, `from` against
  `to` (anyone who can read the Opportunity; the same number twice is 422, an unknown one
  404): the line diff above, the totals, the Assumptions and Risks added, removed or changed
  (matched by their origin Gap, else their wording) and **why it changed**: the trace events
  of the listed types between the older version's creation and the newer version's.
  `compare_versions` and its `VersionDiff` stay as Story 9.3 made them (the review panel).
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import TraceRecord, VersionRecord
from app.modules.estimates.application.estimates import version_view
from app.modules.estimates.application.lineage import trace_actors
from app.modules.estimates.application.models import (
    Assumption,
    EstimateLine,
    EstimateVersion,
    ItemDiff,
    LineageActor,
    LineDiff,
    Risk,
    VersionComparison,
    VersionDiff,
    WhyEvent,
    WhySubject,
)
from app.modules.estimates.domain.estimates import section_rank
from app.modules.identity.application.public import Principal
from app.modules.opportunities.application import public as opportunities
from app.platform.errors import NotFoundError, UnprocessableError
from app.platform.uow import UnitOfWork

SAME_VERSION_DETAIL = "Choose two different Estimate Versions to compare."
VERSION_NOT_FOUND_DETAIL = "No Estimate Version with this number."
CREATED = "estimates.estimate_version.created"
WHY_LABELS: dict[str, str] = {
    "estimates.estimate_line.edited": "Estimate line edited",
    CREATED: "Estimate version created",
    "conflicts.conflict.resolved": "Conflict resolved",
    "conflicts.conflict.escalated": "Conflict escalated",
    "reviews.challenge.raised": "Challenge raised",
    "reviews.challenge.confirmed": "Reassessment confirmed",
    "reviews.challenge.declined": "Challenge declined",
    "reviews.review_decision.recorded": "Review decision recorded",
    "assessments.assessment.completed": "Assessment completed",
    "assessments.finding.overridden": "Finding overridden",
    "assessments.finding.resolved": "Finding resolved",
    "estimates.assumption.proposed": "Assumptions proposed",
    "estimates.assumption.accepted": "Assumption accepted",
    "estimates.assumption.edited": "Assumption edited",
    "estimates.risk.created": "Risk created",
    "estimates.risk.edited": "Risk edited",
    "gaps.gap.converted": "Gap converted",
}
"""The event types "Why it changed" lists, with their labels (as the web's `EVENT_LABELS`)."""


async def version_detail(uow: UnitOfWork, version_id: UUID) -> EstimateVersion | None:
    """`estimates.public.version_detail`: the Estimate Version, or None when unknown."""
    record = await repo.get_version(uow, version_id)
    return None if record is None else await version_view(uow, record)


def _key(line: EstimateLine) -> tuple[str, str]:
    return line.section.value, line.title.strip().casefold()


def _lines(version: EstimateVersion) -> list[EstimateLine]:
    return [line for section in version.sections for line in section.lines]


def _round(value: float) -> float:
    return round(value, 1)


def diff_lines(before: list[EstimateLine], after: list[EstimateLine]) -> list[LineDiff]:
    """The added, removed and changed lines, in template order then title. Pure."""
    older: dict[tuple[str, str], list[EstimateLine]] = defaultdict(list)
    for line in sorted(before, key=lambda line: line.position):
        older[_key(line)].append(line)
    found: list[LineDiff] = []
    for line in sorted(after, key=lambda line: line.position):
        matches = older.get(_key(line))
        if not matches:
            found.append(
                LineDiff(
                    change="added",
                    section=line.section,
                    title=line.title,
                    before_hours=None,
                    after_hours=line.total_hours,
                    delta_hours=_round(line.total_hours),
                )
            )
            continue
        old = matches.pop(0)
        if old.total_hours != line.total_hours or old.role_mix != line.role_mix:
            found.append(
                LineDiff(
                    change="changed",
                    section=line.section,
                    title=line.title,
                    before_hours=old.total_hours,
                    after_hours=line.total_hours,
                    delta_hours=_round(line.total_hours - old.total_hours),
                )
            )
    for left in older.values():
        for old in left:
            found.append(
                LineDiff(
                    change="removed",
                    section=old.section,
                    title=old.title,
                    before_hours=old.total_hours,
                    after_hours=None,
                    delta_hours=_round(-old.total_hours),
                )
            )
    return sorted(found, key=lambda d: (section_rank(d.section), d.title.casefold()))


async def compare_versions(uow: UnitOfWork, version_id: UUID) -> VersionDiff | None:
    """`estimates.public.compare_versions`: the version against the one numbered just
    before it ("First version" when there is none); None when the version is unknown."""
    record = await repo.get_version(uow, version_id)
    if record is None:
        return None
    after = await version_view(uow, record)
    previous = (
        None
        if record.version <= 1
        else await repo.version_by_number(uow, record.opportunity_id, record.version - 1)
    )
    if previous is None:
        return VersionDiff(
            version=record.version,
            previous_version=None,
            first=True,
            lines=[],
            total_before=None,
            total_after=after.totals.total_hours,
            total_delta=0.0,
        )
    before = await version_view(uow, previous)
    return VersionDiff(
        version=record.version,
        previous_version=previous.version,
        first=False,
        lines=diff_lines(_lines(before), _lines(after)),
        total_before=before.totals.total_hours,
        total_after=after.totals.total_hours,
        total_delta=_round(after.totals.total_hours - before.totals.total_hours),
    )


# --- any two versions (Story 9.9) -----------------------------------------------------------


def _hours_text(hours: float | None) -> str:
    return "" if hours is None else f" · {hours:g} h"


def _assumption_summary(a: Assumption) -> str:
    line = "" if a.line is None else f" · {a.line.title}"
    kind = "Condition" if a.kind == "condition" else "Contingency"
    return f"{kind}{_hours_text(a.amount_hours)}{line} · {a.wording}"


def _risk_summary(r: Risk) -> str:
    return f"{r.likelihood.value} likelihood · {r.impact.value} impact · {r.description}"


def _items_diff(
    before: Sequence[Assumption | Risk],
    after: Sequence[Assumption | Risk],
    text_of: dict[str, str],
    summary: dict[str, str],
) -> list[ItemDiff]:
    """Items matched by their origin Gap (else their text, case-insensitive)."""

    def key(item: Assumption | Risk) -> str:
        return item.origin.id or text_of[item.id].strip().casefold()

    older = {key(item): item for item in before}
    found: list[ItemDiff] = []
    for item in after:
        old = older.pop(key(item), None)
        if old is None:
            found.append(
                ItemDiff(
                    change="added",
                    id=item.id,
                    text=text_of[item.id],
                    before=None,
                    after=summary[item.id],
                )
            )
        elif summary[old.id] != summary[item.id]:
            found.append(
                ItemDiff(
                    change="changed",
                    id=item.id,
                    text=text_of[item.id],
                    before=summary[old.id],
                    after=summary[item.id],
                )
            )
    found.extend(
        ItemDiff(
            change="removed", id=old.id, text=text_of[old.id], before=summary[old.id], after=None
        )
        for old in older.values()
    )
    return found


def _assumptions(version: EstimateVersion) -> list[Assumption]:
    return [*version.assumptions.conditions, *version.assumptions.contingencies]


def _assumption_diff(before: EstimateVersion, after: EstimateVersion) -> list[ItemDiff]:
    items = [*_assumptions(before), *_assumptions(after)]
    return _items_diff(
        _assumptions(before),
        _assumptions(after),
        {a.id: a.wording for a in items},
        {a.id: _assumption_summary(a) for a in items},
    )


def _risk_diff(before: EstimateVersion, after: EstimateVersion) -> list[ItemDiff]:
    items = [*before.risks, *after.risks]
    return _items_diff(
        before.risks,
        after.risks,
        {r.id: r.description for r in items},
        {r.id: _risk_summary(r) for r in items},
    )


async def _why(uow: UnitOfWork, older: VersionRecord, newer: VersionRecord) -> list[WhyEvent]:
    """The listed trace events from the older version's creation until the newer version
    was superseded by the next one (its creation), or until now when there is none (edits
    to a draft after its creation are listed); the older version's `created` event is left
    out."""
    following = await repo.version_by_number(uow, newer.opportunity_id, newer.version + 1)
    end = datetime.now(UTC) if following is None else following.created_at
    events = [
        e
        for e in await repo.events_between(
            uow,
            older.opportunity_id,
            start=older.created_at,
            end=end,
            event_types=tuple(WHY_LABELS),
        )
        if not (e.event_type == CREATED and e.subject_id == older.id)
    ]
    actors = await trace_actors(uow, events)
    return [_why_event(e, actors[f"{e.actor_type}:{e.actor_id}"]) for e in events]


def _why_event(event: TraceRecord, actor: LineageActor) -> WhyEvent:
    reason = event.payload.get("reason")
    return WhyEvent(
        id=str(event.id),
        event_type=event.event_type,
        label=WHY_LABELS.get(event.event_type, event.event_type),
        actor=actor,
        occurred_at=event.occurred_at,
        reason=reason if isinstance(reason, str) and reason else None,
        subject=WhySubject(
            type=event.subject_type, id=str(event.subject_id), version=event.subject_version
        ),
    )


async def compare_any(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, from_version: int, to_version: int
) -> VersionComparison:
    """`estimates.compare_any`: version `from_version` against `to_version` (module
    docstring)."""
    await opportunities.readable_resource(uow, actor, opportunity_id)
    if from_version == to_version:
        raise UnprocessableError(SAME_VERSION_DETAIL)
    base = await repo.version_by_number(uow, opportunity_id, from_version)
    target = await repo.version_by_number(uow, opportunity_id, to_version)
    if base is None or target is None:
        raise NotFoundError(VERSION_NOT_FOUND_DETAIL)
    before = await version_view(uow, base)
    after = await version_view(uow, target)
    older, newer = (base, target) if base.version < target.version else (target, base)
    return VersionComparison(
        from_version=base.version,
        from_version_id=str(base.id),
        to_version=target.version,
        to_version_id=str(target.id),
        lines=diff_lines(_lines(before), _lines(after)),
        total_before=before.totals.total_hours,
        total_after=after.totals.total_hours,
        total_delta=_round(after.totals.total_hours - before.totals.total_hours),
        assumptions=_assumption_diff(before, after),
        risks=_risk_diff(before, after),
        why=await _why(uow, older, newer),
    )
