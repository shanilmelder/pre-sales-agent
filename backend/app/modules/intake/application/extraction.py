"""Requirement extraction (Story 2.5 Part A): the `intake.extract_requirements` job and
`intake.accept_extraction`.

**Queueing.** Each successful parse calls `enqueue_extraction` in its own Unit of Work: it
inserts a `queued` `intake_extractions` row and its job (background priority), unless one
of the Opportunity's extractions is still `queued` (its job not yet started), in which case
nothing is added. `start_extraction` (the Retry API) does the same, but refuses (409) while
one is `queued` or `running`. Both hold the Opportunity's extraction lock until commit.

**The handler.**

1. Short Unit of Work: reads the newest `parsed` version of every Source with its text,
   labelled `S<n>` (the Source's position, oldest first), and marks the extraction `running`
   with their count.
2. Over the profile's budget (`input_budget_chars`): `failed` / `input_too_large`, no model
   call, the job finishes.
3. No Unit of Work open: `intake_agent` proposes Requirements through the ModelGateway. Their
   quotes are resolved; if any citation or Requirement was dropped, one retry call names the
   failing items by index. Then what resolves is accepted.
4. `accept_extraction`, one Unit of Work: passages, the superseding of earlier extracted
   Requirements, the new Requirements and their evidence, the extraction `succeeded` with
   its counts, and an `intake.extraction.completed` trace event.

A gateway error (or any other) is retried by the queue (`max_attempts` 2); on the final
attempt the handler first marks the extraction `failed` with `model_unavailable`,
`model_timeout` or `output_invalid`, then re-raises and the job goes dead. Idempotent: only
an extraction still `queued` or `running` is worked on, and only a `running` one accepted.

Logs, trace and `last_error` carry ids, codes and counts only, never Source or Requirement
text.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta
from uuid import UUID

from app.agents.contract import AgentResult
from app.agents.intake_agent.agent import (
    AGENT_ID,
    IntakeAgent,
    IntakeTask,
    RetryRequest,
    SourceBlock,
)
from app.agents.intake_agent.agent import config as agent_config
from app.agents.intake_agent.schema import IntakeOutput
from app.modules.intake.adapters import requirements_repository as repo
from app.modules.intake.application.texts import extracted_text
from app.modules.intake.domain.requirements import (
    IN_PROGRESS,
    SUBJECT_TYPE,
    ExtractionErrorCode,
    ExtractionStatus,
    ProposedCitation,
    ProposedRequirement,
    Resolution,
    input_budget_chars,
    resolve_requirements,
)
from app.platform import trace
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import (
    ModelGatewayError,
    ModelOutputInvalidError,
    ModelTimeoutError,
)
from app.platform.model_gateway.profiles import get_profile
from app.platform.storage import BlobStore
from app.platform.trace.catalogue import IntakeExtractionCompleted
from app.platform.uow import UnitOfWork, unit_of_work

EXTRACT_REQUIREMENTS = "intake.extract_requirements"
_IN_PROGRESS = tuple(sorted(s.value for s in IN_PROGRESS))
_QUEUED = (ExtractionStatus.QUEUED.value,)
_RUNNING = (ExtractionStatus.RUNNING.value,)
_log = get_logger(__name__)


class ExtractRequirements(JobPayload):
    extraction_id: UUID


def extraction_settings() -> Settings:
    """Settings for the handler (storage root, chat profile). Tests replace this."""
    return get_settings()


# --- queueing -------------------------------------------------------------------------------


async def queue_extraction(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Insert a `queued` extraction and its job. The caller holds the Opportunity's
    extraction lock."""
    extraction_id = new_id()
    await repo.insert_extraction(uow, extraction_id=extraction_id, opportunity_id=opportunity_id)
    await enqueue(
        uow, ExtractRequirements(extraction_id=extraction_id), opportunity_id=opportunity_id
    )
    return extraction_id


async def enqueue_extraction(uow: UnitOfWork, *, opportunity_id: UUID) -> UUID:
    """Queue an extraction of the Opportunity in the caller's Unit of Work, unless one is
    already queued and not yet started: then that one's id is returned and nothing added."""
    await repo.lock_opportunity(uow, opportunity_id)
    await fail_stale(uow, opportunity_id)
    waiting = await repo.extraction_in(uow, opportunity_id, _QUEUED)
    if waiting is not None:
        _log.info(
            "intake.extraction_coalesced",
            extra={"opportunity_id": str(opportunity_id), "extraction_id": str(waiting)},
        )
        return waiting
    extraction_id = await queue_extraction(uow, opportunity_id)
    _log.info(
        "intake.extraction_queued",
        extra={"opportunity_id": str(opportunity_id), "extraction_id": str(extraction_id)},
    )
    return extraction_id


def stale_after() -> timedelta:
    """How long an extraction may stay `queued` or `running` before it is taken as lost (its
    job died without recording it, e.g. a worker killed on the final attempt): every
    attempt's timeout, plus a minute."""
    spec = EXTRACT_REQUIREMENTS_JOB
    return timedelta(seconds=spec.timeout_s * spec.max_attempts + 60)


async def fail_stale(uow: UnitOfWork, opportunity_id: UUID) -> None:
    """Mark the Opportunity's lost extractions `failed` / `model_timeout`. The caller holds
    its extraction lock."""
    failed = await repo.fail_stale_extractions(
        uow,
        opportunity_id,
        older_than=stale_after(),
        error_code=ExtractionErrorCode.MODEL_TIMEOUT.value,
    )
    if failed:
        _log.info(
            "intake.extraction_stale_failed",
            extra={"opportunity_id": str(opportunity_id), "count": failed},
        )


# --- resolving ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtractionSource:
    """A Source version the extraction read, with its prompt label `S<n>`."""

    label: str
    source_id: UUID
    version: int
    kind: str
    text: str = field(repr=False)


def proposal(result: AgentResult) -> IntakeOutput:
    """The agent's proposed Requirements, re-validated (AD-4). Raises
    `ModelOutputInvalidError` when the extension is missing or malformed."""
    raw = result.extensions.get(AGENT_ID)
    try:
        return IntakeOutput.model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError("The intake_agent extension is not valid.") from None


def resolve(result: AgentResult, sources: Sequence[ExtractionSource]) -> Resolution:
    """Resolve the proposal's quotes against the Sources' texts."""
    proposed = [
        ProposedRequirement(
            text=item.text,
            classification=item.classification,
            citations=tuple(ProposedCitation(c.source, c.quote) for c in item.citations),
        )
        for item in proposal(result).requirements
    ]
    return resolve_requirements(proposed, {s.label: s.text for s in sources})


# --- accepting ------------------------------------------------------------------------------


async def accept_extraction(
    uow: UnitOfWork,
    *,
    extraction_id: UUID,
    result: AgentResult,
    sources: Sequence[ExtractionSource],
    actor: Actor,
) -> Resolution | None:
    """`intake.accept_extraction`: validate the agent's result, resolve every quote to a
    passage, supersede the Opportunity's earlier extracted, unlocked Requirements and store
    the new ones with their evidence; mark the extraction `succeeded` and trace it. With no
    Sources nothing is superseded. Returns None (and writes nothing) unless the extraction is
    still `running`.

    Nothing is superseded or stored, either, when a newer extraction of the Opportunity has
    already succeeded (this one is `succeeded` with 0 Requirements: its results are out of
    date), or when the model proposed Requirements but none could be cited (`failed` /
    `output_invalid`)."""
    record = await repo.get_extraction(uow, extraction_id)
    if record is None:
        return None
    await repo.lock_opportunity(uow, record.opportunity_id)
    record = await repo.get_extraction(uow, extraction_id, for_update=True)
    if record is None or record.status != ExtractionStatus.RUNNING:
        return None
    resolution = resolve(result, sources)
    ids = {"extraction_id": str(extraction_id), "opportunity_id": str(record.opportunity_id)}
    if await repo.newer_succeeded(uow, record):
        outdated = IntakeExtractionCompleted(
            requirement_count=0, dropped_count=0, source_count=len(sources)
        )
        await _succeed(uow, record, outdated, actor)
        _log.info("intake.extraction_outdated", extra={**ids, **outdated.model_dump()})
        return resolution
    if resolution.dropped and not resolution.requirements:
        await repo.update_extraction(
            uow,
            extraction_id,
            from_statuses=_RUNNING,
            status=ExtractionStatus.FAILED.value,
            error_code=ExtractionErrorCode.OUTPUT_INVALID.value,
            requirement_count=0,
            dropped_count=resolution.dropped,
            source_count=len(sources),
            finished=True,
        )
        _log.info(
            "intake.extraction_failed",
            extra={
                **ids,
                "error_code": ExtractionErrorCode.OUTPUT_INVALID.value,
                "dropped_count": resolution.dropped,
            },
        )
        return resolution
    by_label = {s.label: s for s in sources}
    # With no Source read (none parsed, or their text missing) nothing is replaced.
    superseded = await repo.supersede_extracted(uow, record.opportunity_id) if sources else 0
    for requirement in resolution.requirements:
        passage_ids: list[UUID] = []
        for span in requirement.spans:
            source = by_label[span.source]
            passage_id = await repo.passage(
                uow,
                source_id=source.source_id,
                version=source.version,
                start=span.start,
                end=span.end,
            )
            if passage_id not in passage_ids:
                passage_ids.append(passage_id)
        await repo.insert_requirement(
            uow,
            requirement_id=new_id(),
            opportunity_id=record.opportunity_id,
            text_=requirement.text,
            classification=requirement.classification.value,
            extraction_id=extraction_id,
            passage_ids=passage_ids,
            created_by=actor.id,
        )
    completed = IntakeExtractionCompleted(
        requirement_count=len(resolution.requirements),
        dropped_count=resolution.dropped,
        source_count=len(sources),
    )
    await _succeed(uow, record, completed, actor)
    _log.info(
        "intake.extraction_accepted",
        extra={**ids, "superseded_count": superseded, **completed.model_dump()},
    )
    return resolution


async def _succeed(
    uow: UnitOfWork,
    record: repo.ExtractionRecord,
    completed: IntakeExtractionCompleted,
    actor: Actor,
) -> None:
    await repo.update_extraction(
        uow,
        record.id,
        from_statuses=_RUNNING,
        status=ExtractionStatus.SUCCEEDED.value,
        requirement_count=completed.requirement_count,
        dropped_count=completed.dropped_count,
        source_count=completed.source_count,
        finished=True,
    )
    await trace.append(
        uow,
        actor=actor,
        payload=completed,
        subject_type=SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=record.opportunity_id,
    )


# --- the handler ----------------------------------------------------------------------------


def error_code(exc: BaseException) -> ExtractionErrorCode:
    """The extraction's `error_code` for the error that killed its job."""
    if isinstance(exc, ModelTimeoutError):
        return ExtractionErrorCode.MODEL_TIMEOUT
    if isinstance(exc, ModelOutputInvalidError):
        return ExtractionErrorCode.OUTPUT_INVALID
    # The gateway unreachable or missing, or anything else that kept the model from
    # answering: the codes are fixed (Story 2.5 Part A).
    return ExtractionErrorCode.MODEL_UNAVAILABLE


async def _mark_failed(
    ctx: JobContext, extraction_id: UUID, code: ExtractionErrorCode, source_count: int | None
) -> bool:
    async with unit_of_work(ctx.engine) as uow:
        return await repo.update_extraction(
            uow,
            extraction_id,
            from_statuses=_IN_PROGRESS,
            status=ExtractionStatus.FAILED.value,
            error_code=code.value,
            source_count=source_count,
            finished=True,
        )


async def extract_requirements(ctx: JobContext, payload: ExtractRequirements) -> None:
    """The handler. On the job's final attempt any error first marks the extraction
    `failed` (best effort), so none is left `running` once its job is dead; then it
    re-raises."""
    ids = {"extraction_id": str(payload.extraction_id), "job_id": str(ctx.job_id)}
    try:
        await _extract(ctx, payload)
    except asyncio.CancelledError:
        # The job's timeout (or a stopping worker) cancelled the run. On the final attempt
        # nothing will run it again, so record it as timed out, shielded from the
        # cancellation, then let the cancellation through.
        if ctx.attempt >= ctx.max_attempts:
            await _mark_failed_shielded(ctx, payload.extraction_id, ids)
        raise
    except Exception as exc:
        code = error_code(exc)
        if ctx.attempt >= ctx.max_attempts:
            try:
                recorded = await _mark_failed(ctx, payload.extraction_id, code, None)
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "intake.extraction_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "intake.extraction_failed",
                    extra={**ids, "error_code": code.value, "recorded": recorded},
                )
        else:
            _log.warning(
                "intake.extraction_retrying",
                extra={**ids, "exc_type": type(exc).__name__, "error_code": code.value},
            )
        raise


async def _mark_failed_shielded(ctx: JobContext, extraction_id: UUID, ids: dict[str, str]) -> None:
    write = asyncio.ensure_future(
        _mark_failed(ctx, extraction_id, ExtractionErrorCode.MODEL_TIMEOUT, None)
    )
    try:
        recorded = await asyncio.shield(write)
    except asyncio.CancelledError:  # cancelled again: still let the write land
        await asyncio.wait({write})
        recorded = not write.cancelled() and write.exception() is None and write.result()
    except Exception as exc:
        _log.warning(
            "intake.extraction_fail_unrecorded", extra={**ids, "exc_type": type(exc).__name__}
        )
        return
    _log.info(
        "intake.extraction_failed",
        extra={**ids, "error_code": ExtractionErrorCode.MODEL_TIMEOUT.value, "recorded": recorded},
    )


async def _start(
    ctx: JobContext, extraction_id: UUID, store: BlobStore
) -> tuple[UUID, list[ExtractionSource]] | None:
    """Read the extraction's Sources and mark it `running` with their count; None if it is
    no longer queued or running (a duplicate or late run)."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_extraction(uow, extraction_id)
        if record is None:
            return None
        await repo.lock_opportunity(uow, record.opportunity_id)
        record = await repo.get_extraction(uow, extraction_id, for_update=True)
        if record is None or record.status not in _IN_PROGRESS:
            return None
        sources: list[ExtractionSource] = []
        for version in await repo.newest_parsed_versions(uow, record.opportunity_id):
            text = await extracted_text(uow, version.source_id, version.version, store=store)
            if text is None:  # its text blob is missing: skipped, never fatal
                continue
            sources.append(
                ExtractionSource(
                    label=f"S{version.number}",
                    source_id=version.source_id,
                    version=version.version,
                    kind=version.kind,
                    text=text,
                )
            )
        await repo.update_extraction(
            uow,
            extraction_id,
            from_statuses=_IN_PROGRESS,
            status=ExtractionStatus.RUNNING.value,
            source_count=len(sources),
        )
        return record.opportunity_id, sources


async def _extract(ctx: JobContext, payload: ExtractRequirements) -> None:
    settings = extraction_settings()
    extraction_id = payload.extraction_id
    ids: dict[str, object] = {"extraction_id": str(extraction_id)}
    started = await _start(ctx, extraction_id, BlobStore(settings.storage_dir))
    if started is None:
        _log.info("intake.extraction_skipped", extra=ids)
        return
    opportunity_id, sources = started
    ids["opportunity_id"] = str(opportunity_id)
    chars = sum(len(s.text) for s in sources)
    budget = input_budget_chars(get_profile(settings.model_profile_chat).num_ctx)
    if chars > budget:
        await _mark_failed(ctx, extraction_id, ExtractionErrorCode.INPUT_TOO_LARGE, len(sources))
        _log.info(
            "intake.extraction_failed",
            extra={
                **ids,
                "error_code": ExtractionErrorCode.INPUT_TOO_LARGE.value,
                "char_count": chars,
                "budget_chars": budget,
                "source_count": len(sources),
            },
        )
        return

    if sources:
        agent = IntakeAgent(provider.current(), profile=settings.model_profile_chat)
        task = IntakeTask(
            opportunity_id=opportunity_id,
            run_id=extraction_id,
            sources=[SourceBlock(s.label, s.kind, s.text) for s in sources],
        )
        result = await agent.run(task)
        first = resolve(result, sources)
        if first.failing:
            _log.info(
                "intake.extraction_quotes_unresolved",
                extra={**ids, "failing_count": len(first.failing), "dropped_count": first.dropped},
            )
            retry = RetryRequest(previous=proposal(result), failing=first.failing)
            try:
                retried = await agent.run(replace(task, retry=retry))
            except ModelGatewayError as exc:  # keep what the first reply resolved
                _log.warning(
                    "intake.extraction_retry_failed",
                    extra={**ids, "exc_type": type(exc).__name__},
                )
            else:
                # Keep whichever reply kept more Requirements (the retry on a tie).
                if len(resolve(retried, sources).requirements) >= len(first.requirements):
                    result = retried
    else:  # nothing parsed with text: nothing to ask the model
        result = AgentResult(
            confidence=1.0,
            confidence_basis="No parsed Sources.",
            needs_human_review=False,
            extensions={AGENT_ID: IntakeOutput(requirements=[])},
        )

    actor = Actor(type="agent", id=agent_config(settings.model_profile_chat).actor_id)
    async with unit_of_work(ctx.engine) as uow:
        accepted = await accept_extraction(
            uow, extraction_id=extraction_id, result=result, sources=sources, actor=actor
        )
    if accepted is None:
        _log.info("intake.extraction_skipped", extra=ids)


EXTRACT_REQUIREMENTS_JOB = register(
    JobType(
        name=EXTRACT_REQUIREMENTS,
        payload=ExtractRequirements,
        handler=extract_requirements,
        priority="background",
        # Above the worst case: (1 + PSA_MODEL_MAX_RETRIES) attempts of PSA_MODEL_TIMEOUT_S
        # (3 x 120 s) for the call, the same again for the quote-resolution retry, plus the
        # wait for a model slot.
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=15.0,
        backoff_cap_s=120.0,
    )
)
