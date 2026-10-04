"""intake's job types (Story 2.2 Part B): `intake.parse_source`.

Every added Source version enqueues one `ParseSource` job (`enqueue_parse`, in the adding
command's Unit of Work, next to the version's `queued` parse row). The worker's handler:

1. marks the parse row `parsing` (short Unit of Work);
2. parses the stored file in a child process with time and memory limits (`parse_runner`),
   with no Unit of Work open;
3. stores the text UTF-8 encoded in `platform.storage`, then marks the row `parsed` with
   `text_sha256`, `char_count` (code points) and `parser`, references the blob, appends
   `intake.source.parsed` and queues the Opportunity's Requirement extraction
   (`intake.extract_requirements`, Story 2.5), in one Unit of Work.

A permanent failure (`PERMANENT_CODES`: `unreadable`, `not_supported`, `no_text`,
`too_large_output`) marks the row `failed` and finishes the job: retrying the same bytes
can't help. Anything else raises so the queue retries it: a timed-out or signal-killed
child, a stored file not found, the database. On the final attempt the handler first marks
the row `failed` (`timeout` for the child, `unreadable` otherwise), best effort, then
raises and the job goes dead.

Idempotent: a version already `parsed` or `failed` is left alone, and only a row still
`parsing` is finished, so a reclaimed or duplicate run never double-counts.
Logs, trace and `last_error` carry ids, codes and sizes only, never text or file names.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from app.modules.intake.adapters import parse_runner, repository
from app.modules.intake.adapters.parse_runner import ParseTimeoutError
from app.modules.intake.application.extraction import enqueue_extraction
from app.modules.intake.domain.parsing import (
    PERMANENT_CODES,
    ParseError,
    ParseErrorCode,
    ParseStatus,
)
from app.modules.intake.domain.sources import PASTED_TEXT_FILENAME, SUBJECT_TYPE, extension
from app.platform import files, trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.storage import BlobStore
from app.platform.trace.catalogue import IntakeSourceParsed
from app.platform.uow import UnitOfWork, unit_of_work

PARSE_SOURCE = "intake.parse_source"
PASTED_TEXT_EXTENSION = ".txt"
_ACTOR = Actor(type="system", id=PARSE_SOURCE)
_IN_PROGRESS = (ParseStatus.QUEUED.value, ParseStatus.PARSING.value)
_log = get_logger(__name__)


class ParseSource(JobPayload):
    source_id: UUID
    version: int


def parse_settings() -> Settings:
    """Settings for the handler (storage root, parse limits). Tests replace this."""
    return get_settings()


def file_extension(filename: str) -> str:
    """The extension a version's file is parsed as: its own, or `.txt` for pasted text."""
    if filename == PASTED_TEXT_FILENAME:
        return PASTED_TEXT_EXTENSION
    return extension(filename)


async def enqueue_parse(
    uow: UnitOfWork, *, source_id: UUID, version: int, opportunity_id: UUID
) -> UUID:
    """Queue parsing of a Source version in the caller's Unit of Work."""
    return await enqueue(
        uow, ParseSource(source_id=source_id, version=version), opportunity_id=opportunity_id
    )


def _ids(payload: ParseSource) -> dict[str, object]:
    return {"source_id": str(payload.source_id), "version": payload.version}


async def _mark_failed(ctx: JobContext, payload: ParseSource, code: ParseErrorCode) -> None:
    async with unit_of_work(ctx.engine) as uow:
        changed = await repository.update_parse(
            uow,
            payload.source_id,
            payload.version,
            from_statuses=_IN_PROGRESS,
            status=ParseStatus.FAILED.value,
            error_code=code.value,
        )
    _log.info(
        "intake.source_parse_failed",
        extra={**_ids(payload), "error_code": code.value, "recorded": changed},
    )


async def _single_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


class BlobMissingError(RuntimeError):
    """The version's stored file isn't in the store (yet): retryable, never `unreadable`
    on its own."""


def _final_code(exc: Exception) -> ParseErrorCode:
    if isinstance(exc, ParseTimeoutError):
        return ParseErrorCode.TIMEOUT
    if isinstance(exc, ParseError):
        return exc.code
    return ParseErrorCode.UNREADABLE


async def parse_source(ctx: JobContext, payload: ParseSource) -> None:
    """The handler. On the job's final attempt any error first marks the row `failed`
    (`timeout` for a timed-out or killed child, else `unreadable`), best effort, so no row
    is left `parsing` once its job is dead; then it re-raises."""
    try:
        await _parse(ctx, payload)
    except Exception as exc:
        if ctx.attempt >= ctx.max_attempts:
            try:
                await _mark_failed(ctx, payload, _final_code(exc))
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "intake.source_parse_fail_unrecorded",
                    extra={**_ids(payload), "exc_type": type(mark_exc).__name__},
                )
        else:
            _log.warning(
                "intake.source_parse_retrying",
                extra={**_ids(payload), "exc_type": type(exc).__name__},
            )
        raise


async def _parse(ctx: JobContext, payload: ParseSource) -> None:
    settings = parse_settings()
    store = BlobStore(settings.storage_dir)
    async with unit_of_work(ctx.engine) as uow:
        target = await repository.parse_target(uow, payload.source_id, payload.version)
        if target is None or target.status not in _IN_PROGRESS:
            _log.info(
                "intake.source_parse_skipped",
                extra={**_ids(payload), "status": None if target is None else target.status},
            )
            return
        await repository.update_parse(
            uow,
            payload.source_id,
            payload.version,
            from_statuses=_IN_PROGRESS,
            status=ParseStatus.PARSING.value,
        )

    path = store.path_for(target.file_sha256)
    if not await asyncio.to_thread(path.is_file):
        raise BlobMissingError("stored file missing")
    try:
        output = await parse_runner.run_parse(
            path,
            file_extension(target.filename),
            timeout_s=settings.parse_timeout_s,
            max_memory_mb=settings.parse_max_memory_mb,
        )
    except ParseError as exc:
        if exc.code not in PERMANENT_CODES:
            raise  # retryable; marked on the final attempt by `parse_source`
        await _mark_failed(ctx, payload, exc.code)
        return

    data = output.text.encode("utf-8")
    blob = await store.put_stream(_single_chunk(data), len(data))
    char_count = len(output.text)
    async with unit_of_work(ctx.engine) as uow:
        parsed = await repository.update_parse(
            uow,
            payload.source_id,
            payload.version,
            from_statuses=(ParseStatus.PARSING.value,),
            status=ParseStatus.PARSED.value,
            text_sha256=blob.sha256,
            char_count=char_count,
            parser=output.parser,
        )
        if parsed:
            await files.add_reference(uow, blob.sha256, blob.size)
            await trace.append(
                uow,
                actor=_ACTOR,
                payload=IntakeSourceParsed(version=payload.version, char_count=char_count),
                subject_type=SUBJECT_TYPE,
                subject_id=payload.source_id,
                opportunity_id=target.opportunity_id,
                subject_version=payload.version,
            )
            # Story 2.5: every successful parse (re)queues the Opportunity's extraction.
            await enqueue_extraction(uow, opportunity_id=target.opportunity_id)
    _log.info(
        "intake.source_parsed",
        extra={
            **_ids(payload),
            "char_count": char_count,
            "size_bytes": blob.size,
            "parser": output.parser,
            "recorded": parsed,
        },
    )


PARSE_SOURCE_JOB = register(
    JobType(
        name=PARSE_SOURCE,
        payload=ParseSource,
        handler=parse_source,
        priority="interactive",
        # Above the largest `PSA_PARSE_TIMEOUT_S` (600 s), so the child's own limit fires first.
        timeout_s=720.0,
        max_attempts=2,
        backoff_base_s=5.0,
        backoff_cap_s=60.0,
    )
)
