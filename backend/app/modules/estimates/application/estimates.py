"""The Estimate query and the draft start command (Story 8.1).

- `get_estimate`: the Opportunity's current `draft` Estimate Version, with its sections,
  lines, covered Requirements and every server-calculated total, and its latest draft run
  (anyone who can read the Opportunity). Superseded versions are hidden.
- `start_draft`: queue a new draft, e.g. to retry a failed one (`estimates.draft.start`: the
  owner and collaborators except sales representatives; other readers 403, everyone else
  the Opportunity's 404). 409 `estimate_draft_in_progress` while one is queued or running;
  one past `stale_after()` is marked failed (`model_timeout`) first, so it never blocks.
"""

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import DraftRecord, LineRecord, VersionRecord
from app.modules.estimates.application.draft import fail_stale, queue_draft, stale_after
from app.modules.estimates.application.models import (
    EstimateDraft,
    EstimateLine,
    EstimateSection,
    EstimateVersion,
    EstimateView,
    LineRequirement,
    RoleHours,
    RoleMix,
    Totals,
)
from app.modules.estimates.domain import arithmetic
from app.modules.estimates.domain.estimates import (
    IN_PROGRESS,
    ROLES,
    DraftErrorCode,
    DraftStatus,
    EstimateRole,
    Section,
    VersionStatus,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform.errors import EstimateDraftInProgressError
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

IN_PROGRESS_DETAIL = "An Estimate is already being drafted for this Opportunity."
EXCERPT_MAX = 140
INACTIVE_LABEL = "Superseded"
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


async def version_view(uow: UnitOfWork, record: VersionRecord) -> EstimateVersion:
    """The version with its sections, lines, covered Requirements and every total."""
    lines = await repo.lines_of(uow, record.id)
    covered = await _requirements(uow, record.opportunity_id, lines)
    inputs = [
        arithmetic.LineInput(
            section=Section(line.section),
            effort=line.effort_hours,
            mix=_mix(line.role_mix),
            contingencies=(),  # no Contingency Assumptions before Story 8.4
        )
        for line in lines
    ]
    calculated = arithmetic.estimate_totals(inputs)
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
    )


async def get_estimate(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> EstimateView:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    record = await repo.current_version(uow, opportunity_id)
    return EstimateView(
        version=None if record is None else await version_view(uow, record),
        draft=_draft(await repo.latest_draft(uow, opportunity_id)),
        can_start_draft=identity.can(actor, Action.ESTIMATE_DRAFT_START, resource),
    )


async def start_draft(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> EstimateDraft:
    """Queue a new Estimate draft of the Opportunity (the Retry of a failed one)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ESTIMATE_DRAFT_START, resource)
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    busy = await repo.draft_in(uow, opportunity_id, tuple(s.value for s in IN_PROGRESS))
    if busy is not None:
        raise EstimateDraftInProgressError(IN_PROGRESS_DETAIL)
    draft_id = await queue_draft(uow, opportunity_id)
    _log.info(
        "estimates.draft_started",
        extra={
            "opportunity_id": str(opportunity_id),
            "draft_id": str(draft_id),
            "actor_id": actor.actor.id,
        },
    )
    return EstimateDraft(status=DraftStatus.QUEUED, error_code=None)
