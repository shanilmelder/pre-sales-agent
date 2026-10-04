"""Source parse commands and queries (Story 2.2 Part B).

- `retry_parse`: queue a failed latest version's parse again (`intake.source.add`, so the
  Opportunity's owner and collaborators; others get 403, or 404 like adding a Source).
- `extracted_text` (re-exported from `texts`): the stored text of a parsed version, for
  extraction (Story 2.5). Code-point offsets into it are stable: the text never changes once
  stored.
"""

from uuid import UUID

from app.modules.identity.application.public import Principal
from app.modules.intake.adapters import repository
from app.modules.intake.application.jobs import enqueue_parse
from app.modules.intake.application.models import Source
from app.modules.intake.application.sources import _authorized_uploader, _sources
from app.modules.intake.application.texts import extracted_text
from app.modules.intake.domain.parsing import ParseStatus
from app.modules.intake.domain.sources import SUBJECT_TYPE
from app.platform import trace
from app.platform.errors import NotFoundError, ParseNotFailedError
from app.platform.logging import get_logger
from app.platform.trace.catalogue import IntakeSourceParseRetried
from app.platform.uow import UnitOfWork

SOURCE_NOT_FOUND = "No Source with this id in this Opportunity."
NOT_FAILED = "Only a Source whose parse failed can be retried."
_log = get_logger(__name__)

__all__ = ["extracted_text", "retry_parse"]


async def retry_parse(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, source_id: UUID
) -> Source:
    """Set the Source's failed latest version back to `queued` and enqueue its parse.
    404 if the Source isn't in this Opportunity; 409 `parse_not_failed` unless the latest
    version's parse is `failed`."""
    await _authorized_uploader(uow, actor, opportunity_id)
    record = await repository.get(uow, source_id)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(SOURCE_NOT_FOUND)
    state = await repository.parse_state(uow, source_id, record.version, for_update=True)
    if state is None or state.status != ParseStatus.FAILED or state.error_code is None:
        raise ParseNotFailedError(NOT_FAILED)
    await repository.update_parse(
        uow,
        source_id,
        record.version,
        from_statuses=(ParseStatus.FAILED.value,),
        status=ParseStatus.QUEUED.value,
    )
    await enqueue_parse(
        uow, source_id=source_id, version=record.version, opportunity_id=opportunity_id
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=IntakeSourceParseRetried(version=record.version, error_code=state.error_code),
        subject_type=SUBJECT_TYPE,
        subject_id=source_id,
        opportunity_id=opportunity_id,
        subject_version=record.version,
    )
    _log.info(
        "intake.source_parse_retried",
        extra={
            "opportunity_id": str(opportunity_id),
            "source_id": str(source_id),
            "version": record.version,
            "error_code": state.error_code,
            "actor_id": actor.actor.id,
        },
    )
    updated = await repository.get(uow, source_id)
    if updated is None:
        raise RuntimeError("retried source not found")
    (source,) = await _sources(uow, [updated])
    return source
