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
4. `accept_extraction`, one Unit of Work: passages; the proposals reconciled with the
   active Requirements (Story 2.7, `domain.requirements.reconcile`): unmatched ones become
   new Requirements, changed matches of unlocked ones their next version (citing the new
   passages too), and changed matches of human-locked ones pending changes
   (`propose_requirement_change`); nothing is superseded. Then the extraction `succeeded`
   with its counts, an `intake.extraction.completed` trace event, and the Opportunity's Gap
   detection queued (`gaps.enqueue_detection`, Story 4.3).

A gateway error (or any other) is retried by the queue (`max_attempts` 2); on the final
attempt the handler first marks the extraction `failed` with `model_unavailable`,
`model_timeout` or `output_invalid`, then re-raises and the job goes dead. Idempotent: only
an extraction still `queued` or `running` is worked on, and only a `running` one accepted.

Logs, trace and `last_error` carry ids, codes and counts only, never Source or Requirement
text.
"""

import asyncio
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Literal
from uuid import UUID

from app.agents.contract import AgentResult
from app.agents.intake_agent.agent import (
    IntakeAgent,
    IntakeTask,
    RetryRequest,
    SourceBlock,
)
from app.agents.intake_agent.schema import IntakeOutput
from app.modules.intake.adapters import requirements_repository as repo
from app.modules.intake.application.texts import extracted_text
from app.modules.intake.domain.requirements import (
    IN_PROGRESS,
    REQUIREMENT_SUBJECT_TYPE,
    SUBJECT_TYPE,
    ExistingRequirement,
    ExtractionErrorCode,
    ExtractionStatus,
    PassageKey,
    ProposedCitation,
    ProposedRequirement,
    ReconcileOutcome,
    ReconcileProposal,
    RequirementStatus,
    Resolution,
    input_budget_chars,
    normalised_text,
    reconcile,
    resolve_requirements,
)
from app.modules.registry.application import public as registry
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
from app.platform.trace.catalogue import IntakeExtractionCompleted, IntakeRequirementEdited
from app.platform.uow import UnitOfWork, unit_of_work

EXTRACT_REQUIREMENTS = "intake.extract_requirements"
INTAKE_AGENT = "intake_agent"
"""The Agent that extracts Requirements; its config comes from the Agent Registry (Story 7.1)."""
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
    raw = result.extensions.get(INTAKE_AGENT)
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
    store: BlobStore | None = None,
) -> Resolution | None:
    """`intake.accept_extraction`: validate the agent's result, resolve every quote to a
    passage, and reconcile the proposals with the Opportunity's active Requirements (add new
    ones, version changed unlocked ones, propose changes to locked ones, keep the rest);
    mark the extraction `succeeded` and trace it. Returns None (and writes nothing) unless
    the extraction is still `running`.

    No Requirement is written, either, when a newer extraction of the Opportunity has
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
    counts = await _reconcile(uow, record, resolution, sources, actor, store)
    completed = IntakeExtractionCompleted(
        requirement_count=len(resolution.requirements),
        dropped_count=resolution.dropped,
        source_count=len(sources),
    )
    await _succeed(uow, record, completed, actor)
    # Story 4.3: every accepted extraction (re)queues the Opportunity's Gap detection, in this
    # Unit of Work. Imported here, not at the top: gaps reads Requirements through
    # `intake.application.public`, which imports this module, so a top-level import would be
    # circular.
    from app.modules.gaps.application import public as gaps

    await gaps.enqueue_detection(uow, record.opportunity_id)
    _log.info(
        "intake.extraction_accepted",
        extra={**ids, **counts, **completed.model_dump()},
    )
    return resolution


async def _passage_ids(
    uow: UnitOfWork, keys: Sequence[PassageKey], known: dict[PassageKey, UUID]
) -> list[UUID]:
    """The passage ids of these spans (inserted if new), without duplicates, in order."""
    ids: list[UUID] = []
    for key in keys:
        passage_id = known.get(key)
        if passage_id is None:
            passage_id = await repo.passage(
                uow, source_id=key.source_id, version=key.version, start=key.start, end=key.end
            )
            known[key] = passage_id
        if passage_id not in ids:
            ids.append(passage_id)
    return ids


async def _reconcile(
    uow: UnitOfWork,
    record: repo.ExtractionRecord,
    resolution: Resolution,
    sources: Sequence[ExtractionSource],
    actor: Actor,
    store: BlobStore | None,
) -> dict[str, int]:
    """Write the reconciliation of the resolved proposals with the active Requirements.
    Returns the count of each outcome, for the log."""
    # Imported here: requirement_edits imports requirements, which imports this module.
    from app.modules.intake.application.requirement_edits import propose_requirement_change

    by_label = {s.label: s for s in sources}
    proposals = [
        ReconcileProposal(
            text=r.text,
            classification=r.classification,
            passages=tuple(
                PassageKey(
                    by_label[span.source].source_id,
                    by_label[span.source].version,
                    span.start,
                    span.end,
                    normalised_text(by_label[span.source].text[span.start : span.end]),
                )
                for span in r.spans
            ),
        )
        for r in resolution.requirements
    ]
    active = await repo.active_requirements(uow, record.opportunity_id)
    # Story 2.6: a proposal whose best match is a Requirement a person deleted, split or
    # merged away is dropped, so re-extraction never revives what a person removed.
    removed = await repo.removed_requirements(uow, record.opportunity_id)
    removed_ids = {r.id for r in removed}
    cited: dict[UUID, list[PassageKey]] = defaultdict(list)
    known: dict[PassageKey, UUID] = {}
    # The texts of the cited Source versions, so passages in different versions of a Source
    # can match by their quoted text (Story 2.7 review decision). A file read, no model call.
    texts: dict[tuple[UUID, int], str | None] = {(s.source_id, s.version): s.text for s in sources}
    for status in (
        RequirementStatus.ACTIVE,
        RequirementStatus.DELETED,
        RequirementStatus.SUPERSEDED,
    ):
        for c in await repo.active_cited_passages(uow, record.opportunity_id, status.value):
            if status is not RequirementStatus.ACTIVE and c.requirement_id not in removed_ids:
                continue
            version = (c.source_id, c.source_version)
            if version not in texts:
                texts[version] = await extracted_text(uow, *version, store=store)
            text = texts[version]
            key = PassageKey(
                c.source_id,
                c.source_version,
                c.start,
                c.end,
                None if text is None else normalised_text(text[c.start : c.end]),
            )
            cited[c.requirement_id].append(key)
            known[key] = c.passage_id
    by_id = {r.id: r for r in active}

    def existing(records: list[repo.RequirementRecord]) -> list[ExistingRequirement]:
        return [
            ExistingRequirement(
                id=r.id,
                text=r.text,
                classification=r.classification,
                locked=r.locked_by_human,
                passages=tuple(cited[r.id]),
            )
            for r in records
        ]

    counts = {outcome.value: 0 for outcome in ReconcileOutcome}
    for step in reconcile(proposals, existing(active), existing(removed)):
        outcome = step.outcome
        if outcome in (ReconcileOutcome.UNCHANGED, ReconcileOutcome.REMOVED):
            counts[outcome.value] += 1
            continue
        passage_ids = await _passage_ids(uow, step.new_passages, known)
        text, classification = step.proposal.text, step.proposal.classification.value
        if outcome is ReconcileOutcome.ADD:
            await repo.insert_requirement(
                uow,
                requirement_id=new_id(),
                opportunity_id=record.opportunity_id,
                text_=text,
                classification=classification,
                extraction_id=record.id,
                passage_ids=passage_ids,
                created_by=actor.id,
            )
            counts[outcome.value] += 1
            continue
        if step.requirement_id is None:  # pragma: no cover - only `add` has no match
            raise AssertionError("A matched step names its Requirement.")
        current = by_id[step.requirement_id]
        if outcome is ReconcileOutcome.VERSION:
            updated = await repo.version_extracted(
                uow,
                current.id,
                expected_row_version=current.row_version,
                text_=text,
                classification=classification,
            )
            if updated is not None:
                await _record_version(uow, record, current, updated, actor, passage_ids)
                counts[outcome.value] += 1
                continue
            # Locked by a person since it was read: the change becomes a proposal.
        if await repo.active_requirement(uow, record.opportunity_id, current.id) is None:
            # Deleted, split or merged away by a person since it was read (Story 2.6): like a
            # match with a removed Requirement, nothing is written.
            counts[ReconcileOutcome.REMOVED.value] += 1
            continue
        proposed = await propose_requirement_change(
            uow,
            opportunity_id=record.opportunity_id,
            requirement_id=current.id,
            text=text,
            classification=classification,
            passage_ids=passage_ids,
            actor=actor,
            extraction_id=record.id,
        )
        done = ReconcileOutcome.PROPOSE if proposed else ReconcileOutcome.UNCHANGED
        counts[done.value] += 1
    return {f"{name}_count": count for name, count in counts.items()}


async def _record_version(
    uow: UnitOfWork,
    record: repo.ExtractionRecord,
    before: repo.RequirementRecord,
    updated: repo.RequirementRecord,
    actor: Actor,
    passage_ids: list[UUID],
) -> None:
    """The history row, the new evidence and the `intake.requirement.edited` event of an
    unlocked Requirement that extraction moved to its next version."""
    await repo.insert_version(
        uow,
        requirement_id=updated.id,
        version=updated.version,
        text_=updated.text,
        classification=updated.classification,
        created_by=actor.id,
    )
    await repo.link_evidence(uow, updated.id, passage_ids)
    fields: list[Literal["text", "classification"]] = []
    if updated.text != before.text:
        fields.append("text")
    if updated.classification != before.classification:
        fields.append("classification")
    await trace.append(
        uow,
        actor=actor,
        payload=IntakeRequirementEdited(fields=fields, version=updated.version),
        subject_type=REQUIREMENT_SUBJECT_TYPE,
        subject_id=updated.id,
        opportunity_id=record.opportunity_id,
        subject_version=updated.version,
    )


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
) -> tuple[UUID, list[ExtractionSource], registry.ConfigVersion] | None:
    """Read the extraction's Sources and the agent's current config version, and mark it
    `running` with their count; None if it is no longer queued or running (a duplicate or
    late run). While the agent is disabled (or `eval_only`) in the Agent Registry the
    extraction is marked `failed` / `registry_agent_disabled` instead, with no retry."""
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_extraction(uow, extraction_id)
        if record is None:
            return None
        await repo.lock_opportunity(uow, record.opportunity_id)
        record = await repo.get_extraction(uow, extraction_id, for_update=True)
        if record is None or record.status not in _IN_PROGRESS:
            return None
        agent = await registry.current_config(uow, INTAKE_AGENT)
        if not agent.runs_tasks:
            await repo.update_extraction(
                uow,
                extraction_id,
                from_statuses=_IN_PROGRESS,
                status=ExtractionStatus.FAILED.value,
                error_code=ExtractionErrorCode.AGENT_DISABLED.value,
                finished=True,
            )
            _log.info(
                "intake.extraction_agent_disabled",
                extra={"extraction_id": str(extraction_id), "agent_id": INTAKE_AGENT},
            )
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
        return record.opportunity_id, sources, agent.current


async def _extract(ctx: JobContext, payload: ExtractRequirements) -> None:
    settings = extraction_settings()
    extraction_id = payload.extraction_id
    ids: dict[str, object] = {"extraction_id": str(extraction_id)}
    started = await _start(ctx, extraction_id, BlobStore(settings.storage_dir))
    if started is None:
        _log.info("intake.extraction_skipped", extra=ids)
        return
    opportunity_id, sources, version = started
    ids["opportunity_id"] = str(opportunity_id)
    config = registry.agent_config(version, settings)
    chars = sum(len(s.text) for s in sources)
    budget = input_budget_chars(get_profile(config.profile).num_ctx)
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
        agent = IntakeAgent(provider.current(), config=config)
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
            extensions={INTAKE_AGENT: IntakeOutput(requirements=[])},
        )

    actor = Actor(type="agent", id=config.actor_id)
    async with unit_of_work(ctx.engine) as uow:
        accepted = await accept_extraction(
            uow,
            extraction_id=extraction_id,
            result=result,
            sources=sources,
            actor=actor,
            store=BlobStore(settings.storage_dir),
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
