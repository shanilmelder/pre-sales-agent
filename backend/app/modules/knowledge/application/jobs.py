"""knowledge's job types: `knowledge.parse_source` (Story 3.2) and `knowledge.embed_source`
(Story 3.3).

Every Knowledge Source version enqueues one `ParseKnowledgeSource` job (`enqueue_parse`, in
the adding command's Unit of Work, next to the version's `queued` parse row). The worker's
handler follows intake's parse job (Story 2.2 Part B):

1. marks the parse row `parsing` (short Unit of Work);
2. parses the stored file in the sandboxed child process (`parse_runner`: wall-clock, CPU
   and memory limits), with no Unit of Work open;
3. stores the text UTF-8 encoded in `platform.storage` as the version's immutable
   extracted-text artifact, then marks the row `parsed` with `text_sha256`, `char_count`
   (code points) and `parser`, references the blob and appends `knowledge.source.parsed`,
   and (Story 3.3) inserts the version's `queued` embedding row and enqueues
   `knowledge.embed_source`, in one Unit of Work.

A permanent failure (`PERMANENT_CODES`) marks the row `failed` and finishes the job. Anything
else (a timed-out or killed child, a missing stored file, the database) raises so the queue
retries it; on the final attempt the row is first marked `failed`, best effort.

Idempotent: a version already `parsed` or `failed` is left alone, and only a row still
`parsing` is finished. Logs, trace and `last_error` carry ids, codes and sizes only, never
text or file names.

`knowledge.embed_source` (`background`) chunks and embeds one parsed version:

1. marks its embedding row `embedding` (short Unit of Work), reading the extracted-text
   blob, the product, product version and the Source's Integration Type tags;
2. reads the text from `platform.storage`, splits it (`domain.chunking`, sizes from
   `PSA_KNOWLEDGE_CHUNK_CHARS` / `PSA_KNOWLEDGE_CHUNK_OVERLAP_CHARS`) and embeds every chunk
   through the process's ModelGateway (`PSA_MODEL_PROFILE_EMBED`, `background`; the gateway
   writes the `platform_model_calls` row), with no Unit of Work open;
3. inserts all chunks, marks the row `ready` (`chunk_count`, `model`) and appends
   `knowledge.source.embedded`, in one Unit of Work, so a failed attempt leaves no chunks.

Any error raises so the queue retries; on the final attempt the row is first marked
`failed` with an `EmbedErrorCode`, best effort. Only a row still `queued` or `embedding` is
worked on, and only a row still `embedding` becomes `ready`. Chunk text never reaches logs,
trace or `last_error`.
"""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from app.modules.knowledge.adapters import chunk_repository, parse_runner, source_repository
from app.modules.knowledge.adapters.chunk_repository import NewChunk
from app.modules.knowledge.adapters.parse_runner import ParseTimeoutError
from app.modules.knowledge.domain.chunking import chunk_text
from app.modules.knowledge.domain.embedding import IN_PROGRESS as EMBED_IN_PROGRESS
from app.modules.knowledge.domain.embedding import EmbedErrorCode, EmbedStatus
from app.modules.knowledge.domain.sources import SUBJECT_TYPE
from app.platform import files, trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import (
    CallerMetadata,
    EmbedRequest,
    ModelGatewayError,
    ModelTimeoutError,
)
from app.platform.model_gateway.profiles import get_embed_profile
from app.platform.parsing.rules import PERMANENT_CODES, ParseError, ParseErrorCode, ParseStatus
from app.platform.storage import BlobStore
from app.platform.trace.catalogue import KnowledgeSourceEmbedded, KnowledgeSourceParsed
from app.platform.uow import UnitOfWork, unit_of_work
from app.platform.upload_validation import extension

PARSE_SOURCE = "knowledge.parse_source"
EMBED_SOURCE = "knowledge.embed_source"
_ACTOR = Actor(type="system", id=PARSE_SOURCE)
_EMBED_ACTOR = Actor(type="system", id=EMBED_SOURCE)
_IN_PROGRESS = (ParseStatus.QUEUED.value, ParseStatus.PARSING.value)
_log = get_logger(__name__)


class ParseKnowledgeSource(JobPayload):
    source_id: UUID
    version: int


class EmbedKnowledgeSource(JobPayload):
    source_id: UUID
    version: int


def parse_settings() -> Settings:
    """Settings for the handler (storage root, parse limits). Tests replace this."""
    return get_settings()


async def enqueue_parse(uow: UnitOfWork, *, source_id: UUID, version: int) -> UUID:
    """Queue parsing of a Source version in the caller's Unit of Work."""
    return await enqueue(uow, ParseKnowledgeSource(source_id=source_id, version=version))


async def enqueue_embed(uow: UnitOfWork, *, source_id: UUID, version: int) -> UUID:
    """Queue chunking and embedding of a Source version in the caller's Unit of Work."""
    return await enqueue(uow, EmbedKnowledgeSource(source_id=source_id, version=version))


def _ids(payload: ParseKnowledgeSource | EmbedKnowledgeSource) -> dict[str, object]:
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
            # Story 3.3: a parsed version is chunked and embedded next.
            if await chunk_repository.queue_embed(uow, payload.source_id, payload.version):
                await enqueue_embed(uow, source_id=payload.source_id, version=payload.version)
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


# --- knowledge.embed_source (Story 3.3) ------------------------------------------------------


class TextMissingError(RuntimeError):
    """The version's extracted text isn't parsed or isn't in the store: retried; on the
    final attempt the row is marked `text_missing`."""


def _embed_code(exc: Exception) -> EmbedErrorCode:
    if isinstance(exc, TextMissingError):
        return EmbedErrorCode.TEXT_MISSING
    if isinstance(exc, ModelTimeoutError):
        return EmbedErrorCode.MODEL_TIMEOUT
    if isinstance(exc, ModelGatewayError):
        if exc.error_code == "bad_envelope":
            return EmbedErrorCode.MODEL_BAD_OUTPUT
        return EmbedErrorCode.MODEL_UNAVAILABLE
    if isinstance(exc, provider.NoModelGatewayError):
        return EmbedErrorCode.MODEL_UNAVAILABLE
    return EmbedErrorCode.INTERNAL_ERROR


async def _mark_embed_failed(
    ctx: JobContext, payload: EmbedKnowledgeSource, code: EmbedErrorCode
) -> None:
    async with unit_of_work(ctx.engine) as uow:
        changed = await chunk_repository.update_embed(
            uow,
            payload.source_id,
            payload.version,
            from_statuses=EMBED_IN_PROGRESS,
            status=EmbedStatus.FAILED.value,
            error_code=code.value,
        )
    _log.info(
        "knowledge.source_embed_failed",
        extra={**_ids(payload), "error_code": code.value, "recorded": changed},
    )


async def embed_source(ctx: JobContext, payload: EmbedKnowledgeSource) -> None:
    """The handler. On the job's final attempt any error first marks the row `failed`
    with its `EmbedErrorCode`, best effort, so no row is left `embedding` once its job is
    dead; then it re-raises."""
    try:
        await _embed(ctx, payload)
    except Exception as exc:
        if ctx.attempt >= ctx.max_attempts:
            try:
                await _mark_embed_failed(ctx, payload, _embed_code(exc))
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "knowledge.source_embed_fail_unrecorded",
                    extra={**_ids(payload), "exc_type": type(mark_exc).__name__},
                )
        else:
            _log.warning(
                "knowledge.source_embed_retrying",
                extra={**_ids(payload), "exc_type": type(exc).__name__},
            )
        raise


async def _read_text(store: BlobStore, sha256: str) -> str:
    try:
        data = await asyncio.to_thread(store.path_for(sha256).read_bytes)
    except FileNotFoundError:
        raise TextMissingError("extracted text missing") from None
    return data.decode("utf-8")


async def _embed(ctx: JobContext, payload: EmbedKnowledgeSource) -> None:
    settings = parse_settings()
    profile = get_embed_profile(settings.model_profile_embed)
    async with unit_of_work(ctx.engine) as uow:
        target = await chunk_repository.embed_target(uow, payload.source_id, payload.version)
        if target is None or target.embed_status not in EMBED_IN_PROGRESS:
            _log.info(
                "knowledge.source_embed_skipped",
                extra={
                    **_ids(payload),
                    "status": None if target is None else target.embed_status,
                },
            )
            return
        if target.text_sha256 is None:
            raise TextMissingError("version not parsed")
        await chunk_repository.update_embed(
            uow,
            payload.source_id,
            payload.version,
            from_statuses=EMBED_IN_PROGRESS,
            status=EmbedStatus.EMBEDDING.value,
        )

    text = await _read_text(BlobStore(settings.storage_dir), target.text_sha256)
    pieces = chunk_text(
        text,
        max_chars=settings.knowledge_chunk_chars,
        overlap=settings.knowledge_chunk_overlap_chars,
    )
    vectors: list[list[float]] = []
    if pieces:
        vectors = await provider.current().embed(
            EmbedRequest(
                texts=[c.text for c in pieces],
                caller=CallerMetadata(agent_id=EMBED_SOURCE, config_version=profile.name),
                profile=profile.name,
                priority="background",
            )
        )
    new_chunks = [
        NewChunk(ordinal=c.ordinal, start=c.start, end=c.end, text=c.text, embedding=v)
        for c, v in zip(pieces, vectors, strict=True)
    ]
    async with unit_of_work(ctx.engine) as uow:
        ready = await chunk_repository.update_embed(
            uow,
            payload.source_id,
            payload.version,
            from_statuses=(EmbedStatus.EMBEDDING.value,),
            status=EmbedStatus.READY.value,
            chunk_count=len(new_chunks),
            model=profile.name,
        )
        if ready:
            await chunk_repository.insert_chunks(
                uow,
                ids=[new_id() for _ in new_chunks],
                source_id=payload.source_id,
                version=payload.version,
                chunks=new_chunks,
                product=target.product,
                product_version=target.product_version,
                integration_type_ids=target.integration_type_ids,
                model=profile.name,
                dims=profile.dims,
            )
            await trace.append(
                uow,
                actor=_EMBED_ACTOR,
                payload=KnowledgeSourceEmbedded(
                    version=payload.version, chunk_count=len(new_chunks), model=profile.name
                ),
                subject_type=SUBJECT_TYPE,
                subject_id=payload.source_id,
                subject_version=payload.version,
            )
    _log.info(
        "knowledge.source_embedded",
        extra={
            **_ids(payload),
            "chunk_count": len(new_chunks),
            "char_count": len(text),
            "model": profile.name,
            "recorded": ready,
        },
    )


def embed_stale_after_s() -> float:
    """How long a `queued` or `embedding` row may go untouched before its job counts as dead:
    the job's timeout plus a lease. A handler cancelled on timeout, or whose final attempt
    lost its lease, never records `failed`; `retry_embed` re-queues such a row."""
    return EMBED_SOURCE_JOB.timeout_s + parse_settings().job_lease_s


EMBED_SOURCE_JOB = register(
    JobType(
        name=EMBED_SOURCE,
        payload=EmbedKnowledgeSource,
        handler=embed_source,
        priority="background",
        # A large Source is many embedding requests; the lease heartbeat keeps the claim.
        timeout_s=3600.0,
        max_attempts=3,
        backoff_base_s=30.0,
        backoff_cap_s=300.0,
    )
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
