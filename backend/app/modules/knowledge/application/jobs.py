"""knowledge's job types (Story 3.2): `knowledge.parse_source`.

Every Knowledge Source version enqueues one `ParseKnowledgeSource` job (`enqueue_parse`, in
the adding command's Unit of Work, next to the version's `queued` parse row). The worker's
handler follows intake's parse job (Story 2.2 Part B):

1. marks the parse row `parsing` (short Unit of Work);
2. parses the stored file in the sandboxed child process (`parse_runner`: wall-clock, CPU
   and memory limits), with no Unit of Work open;
3. stores the text UTF-8 encoded in `platform.storage` as the version's immutable
   extracted-text artifact, then marks the row `parsed` with `text_sha256`, `char_count`
   (code points) and `parser`, references the blob and appends `knowledge.source.parsed`,
   in one Unit of Work.

A permanent failure (`PERMANENT_CODES`) marks the row `failed` and finishes the job. Anything
else (a timed-out or killed child, a missing stored file, the database) raises so the queue
retries it; on the final attempt the row is first marked `failed`, best effort.

Idempotent: a version already `parsed` or `failed` is left alone, and only a row still
`parsing` is finished. Chunking and embedding are Story 3.3's. Logs, trace and `last_error`
carry ids, codes and sizes only, never text or file names.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from app.modules.knowledge.adapters import parse_runner, source_repository
from app.modules.knowledge.adapters.parse_runner import ParseTimeoutError
from app.modules.knowledge.domain.sources import SUBJECT_TYPE
from app.platform import files, trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.parsing.rules import PERMANENT_CODES, ParseError, ParseErrorCode, ParseStatus
from app.platform.storage import BlobStore
from app.platform.trace.catalogue import KnowledgeSourceParsed
from app.platform.uow import UnitOfWork, unit_of_work
from app.platform.upload_validation import extension

PARSE_SOURCE = "knowledge.parse_source"
_ACTOR = Actor(type="system", id=PARSE_SOURCE)
_IN_PROGRESS = (ParseStatus.QUEUED.value, ParseStatus.PARSING.value)
_log = get_logger(__name__)


class ParseKnowledgeSource(JobPayload):
    source_id: UUID
    version: int


def parse_settings() -> Settings:
    """Settings for the handler (storage root, parse limits). Tests replace this."""
    return get_settings()


async def enqueue_parse(uow: UnitOfWork, *, source_id: UUID, version: int) -> UUID:
    """Queue parsing of a Source version in the caller's Unit of Work."""
    return await enqueue(uow, ParseKnowledgeSource(source_id=source_id, version=version))


def _ids(payload: ParseKnowledgeSource) -> dict[str, object]:
    return {"source_id": str(payload.source_id), "version": payload.version}


async def _mark_failed(
    ctx: JobContext, payload: ParseKnowledgeSource, code: ParseErrorCode
) -> None:
    async with unit_of_work(ctx.engine) as uow:
        changed = await source_repository.update_parse(
            uow,
            payload.source_id,
            payload.version,
            from_statuses=_IN_PROGRESS,
            status=ParseStatus.FAILED.value,
            error_code=code.value,
        )
    _log.info(
        "knowledge.source_parse_failed",
        extra={**_ids(payload), "error_code": code.value, "recorded": changed},
    )


async def _single_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


class BlobMissingError(RuntimeError):
    """The version's stored file isn't in the store: retried like a timeout. If it is still missing
    on the final attempt the row is marked `unreadable`, the only code that fits."""


def _final_code(exc: Exception) -> ParseErrorCode:
    if isinstance(exc, ParseTimeoutError):
        return ParseErrorCode.TIMEOUT
    if isinstance(exc, ParseError):
        return exc.code
    return ParseErrorCode.UNREADABLE


async def parse_source(ctx: JobContext, payload: ParseKnowledgeSource) -> None:
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
                    "knowledge.source_parse_fail_unrecorded",
                    extra={**_ids(payload), "exc_type": type(mark_exc).__name__},
                )
        else:
            _log.warning(
                "knowledge.source_parse_retrying",
                extra={**_ids(payload), "exc_type": type(exc).__name__},
            )
        raise


async def _parse(ctx: JobContext, payload: ParseKnowledgeSource) -> None:
    settings = parse_settings()
    store = BlobStore(settings.storage_dir)
    async with unit_of_work(ctx.engine) as uow:
        target = await source_repository.parse_target(uow, payload.source_id, payload.version)
        if target is None or target.status not in _IN_PROGRESS:
            _log.info(
                "knowledge.source_parse_skipped",
                extra={**_ids(payload), "status": None if target is None else target.status},
            )
            return
        await source_repository.update_parse(
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
            extension(target.filename),
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
        parsed = await source_repository.update_parse(
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
                payload=KnowledgeSourceParsed(version=payload.version, char_count=char_count),
                subject_type=SUBJECT_TYPE,
                subject_id=payload.source_id,
                subject_version=payload.version,
            )
    _log.info(
        "knowledge.source_parsed",
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
        payload=ParseKnowledgeSource,
        handler=parse_source,
        priority="interactive",
        # Above the largest `PSA_PARSE_TIMEOUT_S` (600 s), so the child's own limit fires first.
        timeout_s=720.0,
        max_attempts=2,
        backoff_base_s=5.0,
        backoff_cap_s=60.0,
    )
)
