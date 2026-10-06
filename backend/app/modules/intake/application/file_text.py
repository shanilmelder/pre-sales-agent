"""The text of a stored file, for modules outside intake (Story 1.7, Opportunity import).

`read_stored_text` parses a blob from `platform.storage` with the same parsers, child
process and limits as `intake.parse_source`, but stores nothing: the caller (the worker's
`opportunities.read_import` job) only reads the text. Worker only; never in the `api`
process. Errors carry a code, never content or file names.
"""

import asyncio

from app.modules.intake.adapters import parse_runner
from app.modules.intake.adapters.parse_runner import ParseTimeoutError
from app.modules.intake.application.jobs import file_extension
from app.modules.intake.domain.parsing import ParseError
from app.platform.storage import BlobStore


class FileTextUnreadableError(Exception):
    """The stored file could not be turned into text. `code` is a parse error code
    (`unreadable`, `not_supported`, `no_text`, `too_large_output`, `timeout`)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def read_stored_text(
    store: BlobStore,
    sha256: str,
    filename: str,
    *,
    timeout_s: float,
    max_memory_mb: int,
) -> str:
    """The normalised text of the stored blob `sha256`, parsed as `filename`'s type. Raises
    `FileTextUnreadableError` when it can't be read (a missing blob is `unreadable`)."""
    path = store.path_for(sha256)
    if not await asyncio.to_thread(path.is_file):
        raise FileTextUnreadableError("unreadable")
    try:
        output = await parse_runner.run_parse(
            path, file_extension(filename), timeout_s=timeout_s, max_memory_mb=max_memory_mb
        )
    except ParseTimeoutError:
        raise FileTextUnreadableError("timeout") from None
    except ParseError as exc:
        raise FileTextUnreadableError(exc.code.value) from None
    return output.text
