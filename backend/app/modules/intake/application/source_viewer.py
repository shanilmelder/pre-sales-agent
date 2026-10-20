"""The Source viewer queries (Story 2.3), for the Sources tab's inspector.

- `source_text`: the stored extracted text of a parsed Source version.
- `source_download_link`: a short-lived signed link (`platform.downloads`) to a Source
  version's original file, downloaded under the version's stored file name.

Anyone who can read the Opportunity, sales representatives included. A Source of another
Opportunity, an unknown Source or version, or (for the text) a version that isn't `parsed`
gives the Opportunity's 404, as `get_passage` does, so nothing leaks about Sources
elsewhere. Logs carry ids and sizes only, never text or file names.
"""

from uuid import UUID

from app.modules.identity.application.public import Principal
from app.modules.intake.adapters import repository
from app.modules.intake.application.models import (
    OpportunitySourceDownloadLink,
    OpportunitySourceText,
)
from app.modules.intake.application.texts import extracted_text
from app.modules.opportunities.application import public as opportunities
from app.platform import downloads
from app.platform.errors import NotFoundError
from app.platform.logging import get_logger
from app.platform.storage import BlobStore
from app.platform.uow import UnitOfWork

_log = get_logger(__name__)


def _ids(opportunity_id: UUID, source_id: UUID, version: int) -> dict[str, object]:
    return {"opportunity_id": str(opportunity_id), "source_id": str(source_id), "version": version}


async def _version_in(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, source_id: UUID, version: int
) -> repository.ParseTarget:
    await opportunities.readable_resource(uow, actor, opportunity_id)
    target = await repository.parse_target(uow, source_id, version)
    if target is None or target.opportunity_id != opportunity_id:
        raise NotFoundError(opportunities.NOT_FOUND_DETAIL)
    return target


async def source_text(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    source_id: UUID,
    version: int,
    *,
    store: BlobStore | None = None,
) -> OpportunitySourceText:
    """The version's extracted text, exactly as stored. 404 unless it is `parsed`."""
    await _version_in(uow, actor, opportunity_id, source_id, version)
    text = await extracted_text(uow, source_id, version, store=store)
    if text is None:
        raise NotFoundError(opportunities.NOT_FOUND_DETAIL)
    _log.info(
        "intake.source_text_read",
        extra={
            **_ids(opportunity_id, source_id, version),
            "char_count": len(text),
            "actor_id": actor.actor.id,
        },
    )
    return OpportunitySourceText(version=version, char_count=len(text), text=text)


async def source_download_link(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    source_id: UUID,
    version: int,
    *,
    signing_key: str,
    ttl_s: int,
) -> OpportunitySourceDownloadLink:
    """A short-lived signed link to the version's original file, served unchanged."""
    target = await _version_in(uow, actor, opportunity_id, source_id, version)
    token, expires_at = downloads.sign(
        signing_key, sha256=target.file_sha256, filename=target.filename, ttl_s=ttl_s
    )
    _log.info(
        "intake.source_download_linked",
        extra={**_ids(opportunity_id, source_id, version), "actor_id": actor.actor.id},
    )
    return OpportunitySourceDownloadLink(url=downloads.link_for(token), expires_at=expires_at)
