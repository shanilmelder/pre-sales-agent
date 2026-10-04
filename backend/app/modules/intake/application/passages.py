"""The cited-passage query (Story 2.5 Part B).

`get_passage`: a Source passage of the Opportunity, its exact span and up to 300 code points
of context on each side, for the Evidence inspector. Anyone who can read the Opportunity.
A passage of another Opportunity, an unknown id, or one whose text can't be read gives the
Opportunity's 404, so nothing leaks about passages elsewhere. Logs ids only.
"""

from uuid import UUID

from app.modules.identity.application.public import Principal
from app.modules.intake.adapters import requirements_repository as repo
from app.modules.intake.application.models import Passage
from app.modules.intake.application.requirements import LABEL_SEPARATOR
from app.modules.intake.application.texts import extracted_text
from app.modules.intake.domain.passages import context_window
from app.modules.opportunities.application import public as opportunities
from app.platform.errors import NotFoundError
from app.platform.logging import get_logger
from app.platform.storage import BlobStore
from app.platform.uow import UnitOfWork

_log = get_logger(__name__)


async def get_passage(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    passage_id: UUID,
    *,
    store: BlobStore | None = None,
) -> Passage:
    await opportunities.readable_resource(uow, actor, opportunity_id)
    record = await repo.passage_in(uow, opportunity_id, passage_id)
    if record is None:
        raise NotFoundError(opportunities.NOT_FOUND_DETAIL)
    text = await extracted_text(uow, record.source_id, record.source_version, store=store)
    if text is None or record.end > len(text):
        _log.warning(
            "intake.passage_unreadable",
            extra={"opportunity_id": str(opportunity_id), "passage_id": str(passage_id)},
        )
        raise NotFoundError(opportunities.NOT_FOUND_DETAIL)
    window = context_window(text, record.start, record.end)
    number = (await repo.source_numbers(uow, opportunity_id)).get(record.source_id, 0)
    _log.info(
        "intake.passage_read",
        extra={
            "opportunity_id": str(opportunity_id),
            "passage_id": str(passage_id),
            "actor_id": actor.actor.id,
        },
    )
    return Passage(
        passage_id=str(record.id),
        source_id=str(record.source_id),
        source_version=record.source_version,
        filename=record.filename,
        label=f"S{number}{LABEL_SEPARATOR}{record.filename}",
        before=window.before,
        text=window.text,
        after=window.after,
    )
