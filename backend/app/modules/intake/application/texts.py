"""The extracted text of a parsed Source version (Story 2.2 Part B), read by Requirement
extraction (Story 2.5). Its own module so that the job modules can import it without a
cycle."""

import asyncio
from uuid import UUID

from app.modules.intake.adapters import repository
from app.modules.intake.domain.parsing import ParseStatus
from app.platform.config import get_settings
from app.platform.logging import get_logger
from app.platform.storage import BlobStore
from app.platform.uow import UnitOfWork

_log = get_logger(__name__)


async def extracted_text(
    uow: UnitOfWork, source_id: UUID, version: int, *, store: BlobStore | None = None
) -> str | None:
    """The extracted text of a Source version, or None unless it is `parsed` and its text
    blob is in the store. Internal: no
    authorization here, so callers (Story 2.5's extraction) must have checked access."""
    state = await repository.parse_state(uow, source_id, version)
    if state is None or state.status != ParseStatus.PARSED or state.text_sha256 is None:
        return None
    blobs = store if store is not None else BlobStore(get_settings().storage_dir)
    try:
        data = await asyncio.to_thread(blobs.path_for(state.text_sha256).read_bytes)
    except FileNotFoundError:
        _log.warning(
            "intake.extracted_text_missing", extra={"source_id": str(source_id), "version": version}
        )
        return None
    return data.decode("utf-8")
