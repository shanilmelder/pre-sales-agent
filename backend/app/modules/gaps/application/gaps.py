"""Gap queries and the detection start command (Story 4.3).

- `list_gaps`: the Opportunity's open Gaps, ranked by impact, then its converted Gaps (Story
  8.4) in the same order, each with the Requirements it relates to and its drafted question,
  and its latest detection (anyone who can read the Opportunity).
- `start_detection`: queue a new detection, e.g. to retry a failed one
  (`gaps.detection.start`: the owner and collaborators except sales representatives; other
  readers 403, everyone else the Opportunity's 404). 409 `gap_detection_in_progress` while
  one is queued or running; one past `stale_after()` is marked failed (`model_timeout`)
  first, so it never blocks.
"""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.adapters.repository import DetectionRecord, GapRecord
from app.modules.gaps.application.detection import fail_stale, queue_detection, stale_after
from app.modules.gaps.application.models import (
    ClarificationQuestion,
    Detection,
    Gap,
    GapList,
    GapRequirement,
    GapTrigger,
)
from app.modules.gaps.domain.gaps import (
    IN_PROGRESS,
    ConvertedTo,
    DetectionErrorCode,
    DetectionStatus,
    GapCategory,
    GapOrigin,
    GapStatus,
    Impact,
    QuestionStatus,
    impact_rank,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform.errors import GapDetectionInProgressError
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

IN_PROGRESS_DETAIL = "Gaps are already being detected for this Opportunity."
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


def _detection(record: DetectionRecord | None) -> Detection | None:
    """The read model of the latest detection. One still queued or running past
    `stale_after()` is lost: it reads as failed with `model_timeout`, so it can be retried
    (`start_detection` records that)."""
    if record is None:
        return None
    lost = (
        DetectionStatus(record.status) in IN_PROGRESS
        and datetime.now(UTC) - record.created_at > stale_after()
    )
    if lost:
        return Detection(status=DetectionStatus.FAILED, error_code=DetectionErrorCode.MODEL_TIMEOUT)
    return Detection(
        status=DetectionStatus(record.status),
        error_code=None if record.error_code is None else DetectionErrorCode(record.error_code),
    )


def _ranked(records: list[GapRecord]) -> list[GapRecord]:
    """High, medium, low; oldest first within an impact."""
    return sorted(records, key=lambda g: (impact_rank(g.impact), g.created_at, g.id))


async def gap_views(uow: UnitOfWork, opportunity_id: UUID, records: list[GapRecord]) -> list[Gap]:
    gap_ids = [g.id for g in records]
    links = await repo.links_for(uow, gap_ids)
    questions = await repo.questions_for(uow, gap_ids)
    active = {
        s.id: s.number for s in await intake.active_requirement_snapshots(uow, opportunity_id)
    }
    texts = await intake.requirement_version_texts(
        uow,
        opportunity_id,
        list({(link.requirement_id, link.requirement_version) for link in links}),
    )
    related: dict[UUID, list[tuple[int, GapRequirement]]] = defaultdict(list)
    for link in links:
        number = active.get(link.requirement_id)
        found = texts.get((link.requirement_id, link.requirement_version))
        related[link.gap_id].append(
            (
                number if number is not None else len(active) + 1,
                GapRequirement(
                    id=str(link.requirement_id),
                    version=link.requirement_version,
                    label=f"R{number}" if number is not None else INACTIVE_LABEL,
                    excerpt="" if found is None else excerpt(found.text),
                ),
            )
        )
    views: list[Gap] = []
    for g in records:
        question = questions.get(g.id)
        views.append(
            Gap(
                id=str(g.id),
                title=g.title,
                category=GapCategory(g.category),
                trigger=GapTrigger.model_validate(g.trigger),
                why_it_matters=g.why_it_matters,
                impact=Impact(g.impact),
                impact_basis=g.impact_basis,
                origin=GapOrigin(g.origin),
                status=GapStatus(g.status),
                converted_to=None if g.converted_to is None else ConvertedTo(g.converted_to),
                row_version=g.row_version,
                created_at=g.created_at,
                requirements=[
                    r for _, r in sorted(related[g.id], key=lambda pair: (pair[0], pair[1].id))
                ],
                question=None
                if question is None
                else ClarificationQuestion(
                    id=str(question.id),
                    text=question.text,
                    topic=question.topic,
                    status=QuestionStatus(question.status),
                    status_changed_at=question.status_changed_at,
                    row_version=question.row_version,
                ),
            )
        )
    return views


async def list_gaps(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> GapList:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    records = _ranked(await repo.open_gaps(uow, opportunity_id)) + _ranked(
        await repo.gaps_in(uow, opportunity_id, GapStatus.CONVERTED.value)
    )
    return GapList(
        items=await gap_views(uow, opportunity_id, records),
        detection=_detection(await repo.latest_detection(uow, opportunity_id)),
        can_start_detection=identity.can(actor, Action.GAP_DETECTION_START, resource),
    )


async def start_detection(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> Detection:
    """Queue a new Gap detection of the Opportunity (the Retry of a failed one)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.GAP_DETECTION_START, resource)
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    busy = await repo.detection_in(uow, opportunity_id, tuple(s.value for s in IN_PROGRESS))
    if busy is not None:
        raise GapDetectionInProgressError(IN_PROGRESS_DETAIL)
    detection_id = await queue_detection(uow, opportunity_id)
    _log.info(
        "gaps.detection_started",
        extra={
            "opportunity_id": str(opportunity_id),
            "detection_id": str(detection_id),
            "actor_id": actor.actor.id,
        },
    )
    return Detection(status=DetectionStatus.QUEUED, error_code=None)
