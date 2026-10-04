"""Requirement queries and the extraction start command (Story 2.5 Part A).

- `list_requirements`: the Opportunity's active Requirements with their evidence, and its
  latest extraction (anyone who can read the Opportunity).
- `start_extraction`: queue a new extraction, e.g. to retry a failed one
  (`intake.extraction.start`: the owner and collaborators; other readers 403, everyone else
  the Opportunity's 404). 409 `extraction_in_progress` while one is queued or running; one
  past `stale_after()` is marked failed (`model_timeout`) first, so it never blocks.
"""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.adapters import requirements_repository as repo
from app.modules.intake.adapters.requirements_repository import ExtractionRecord
from app.modules.intake.application.extraction import fail_stale, queue_extraction, stale_after
from app.modules.intake.application.models import (
    Extraction,
    Requirement,
    RequirementEvidence,
    RequirementList,
)
from app.modules.intake.domain.requirements import (
    IN_PROGRESS,
    Classification,
    ExtractionErrorCode,
    ExtractionStatus,
    RequirementOrigin,
)
from app.modules.opportunities.application import public as opportunities
from app.platform.errors import ExtractionInProgressError
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

IN_PROGRESS_DETAIL = "Requirements are already being extracted for this Opportunity."
LABEL_SEPARATOR = " · "
_log = get_logger(__name__)


def _extraction(record: ExtractionRecord | None) -> Extraction | None:
    """The read model of the latest extraction. One still queued or running past
    `stale_after()` is lost (its job died without recording it): it reads as failed with
    `model_timeout`, so it can be retried (`start_extraction` records that)."""
    if record is None:
        return None
    lost = (
        ExtractionStatus(record.status) in IN_PROGRESS
        and datetime.now(UTC) - record.created_at > stale_after()
    )
    if lost:
        return Extraction(
            status=ExtractionStatus.FAILED,
            error_code=ExtractionErrorCode.MODEL_TIMEOUT,
            source_count=record.source_count,
        )
    return Extraction(
        status=ExtractionStatus(record.status),
        error_code=None if record.error_code is None else ExtractionErrorCode(record.error_code),
        source_count=record.source_count,
    )


async def list_requirements(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> RequirementList:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    records = await repo.active_requirements(uow, opportunity_id)
    numbers = await repo.source_numbers(uow, opportunity_id)
    evidence: dict[UUID, list[tuple[int, RequirementEvidence]]] = defaultdict(list)
    for row in await repo.evidence_for(uow, [r.id for r in records]):
        number = numbers.get(row.source_id, 0)
        evidence[row.requirement_id].append(
            (
                number,
                RequirementEvidence(
                    passage_id=str(row.passage_id),
                    source_id=str(row.source_id),
                    source_version=row.source_version,
                    filename=row.filename,
                    label=f"S{number}{LABEL_SEPARATOR}{row.filename}",
                ),
            )
        )
    items = [
        Requirement(
            id=str(r.id),
            text=r.text,
            classification=Classification(r.classification),
            origin=RequirementOrigin(r.origin),
            locked_by_human=r.locked_by_human,
            version=r.version,
            row_version=r.row_version,
            created_at=r.created_at,
            # Stable sort: Source order, then the span order the query returned.
            evidence=[e for _, e in sorted(evidence[r.id], key=lambda pair: pair[0])],
        )
        for r in records
    ]
    return RequirementList(
        items=items,
        extraction=_extraction(await repo.latest_extraction(uow, opportunity_id)),
        can_start_extraction=identity.can(actor, Action.EXTRACTION_START, resource),
    )


async def start_extraction(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> Extraction:
    """Queue a new extraction of the Opportunity (the Retry of a failed one)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.EXTRACTION_START, resource)
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    busy = await repo.extraction_in(uow, opportunity_id, tuple(s.value for s in IN_PROGRESS))
    if busy is not None:
        raise ExtractionInProgressError(IN_PROGRESS_DETAIL)
    extraction_id = await queue_extraction(uow, opportunity_id)
    _log.info(
        "intake.extraction_started",
        extra={
            "opportunity_id": str(opportunity_id),
            "extraction_id": str(extraction_id),
            "actor_id": actor.actor.id,
        },
    )
    return Extraction(status=ExtractionStatus.QUEUED, error_code=None, source_count=None)
