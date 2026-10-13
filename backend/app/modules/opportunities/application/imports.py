"""Opportunity imports (Story 1.7, import from file): start a New Opportunity from an email,
transcript or document.

- `upload_import` (`POST /opportunity-imports`): a presales engineer
  (`opportunities.opportunity.create`) uploads one file. It is checked and stored exactly as
  a Source upload is (`intake.store_upload`: same allowlist, size limit and content checks;
  here a wrong type is 415 and a too-large file 413), recorded as a `queued` import owned by
  the uploader, and an `opportunities.read_import` job is queued in the same Unit of Work.
  The api process never parses or calls a model (AD-8).
- `get_import` (`GET /opportunity-imports/{id}`): its status and suggestions; the uploader
  only (anyone else gets 404), 410 once older than 24 hours.
- `create_from_import`: `NewOpportunity.import_id` given. In one Unit of Work: the import is
  checked (the caller's, 404 otherwise; unused, 409; under 24 hours, 410), the Opportunity is
  created (`opportunities.opportunity.created` with `from_import: true`), the import is
  consumed, and its stored file is added as the Opportunity's first Source through
  `intake.add_stored_file` (traced and queued for parsing as any upload).
- The `opportunities.read_import` job (worker): parses the stored file with intake's parsers
  (`intake.read_stored_text`, no Unit of Work open), asks `opportunity_intake_agent` for
  suggestions through the ModelGateway, keeps only those that pass the form's rules and
  quote the text (`domain.imports.validate_suggestions`), and marks the import `succeeded`.
  An unreadable file marks it `failed` / `unreadable` at once; a model error is retried once,
  then `failed` with `model_unavailable`, `model_timeout` or `output_invalid`.

This module imports intake's public API, and intake imports `opportunities.application.public`,
so `public.py` does not re-export this module (the routes and the worker import it directly).
Logs and job payloads carry ids, codes, sizes and counts only: never the file name, text or
quotes.
"""

import asyncio
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from app.agents.contract import AgentResult
from app.agents.opportunity_intake_agent.agent import (
    AGENT_ID,
    OpportunityIntakeAgent,
    OpportunityIntakeTask,
)
from app.agents.opportunity_intake_agent.schema import OpportunityIntakeOutput
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.application import public as intake
from app.modules.intake.application.public import IncomingFile
from app.modules.opportunities.adapters import imports_repository as repo
from app.modules.opportunities.adapters.imports_repository import ImportRecord
from app.modules.opportunities.application import opportunities
from app.modules.opportunities.application.models import (
    ImportSuggestions,
    NewOpportunity,
    Opportunity,
    OpportunityImport,
    SuggestedValue,
)
from app.modules.opportunities.domain.imports import (
    IN_PROGRESS,
    Candidate,
    ImportErrorCode,
    ImportStatus,
    Suggestion,
    Suggestions,
    is_expired,
    suggestion_count,
    validate_suggestions,
)
from app.platform import files
from app.platform.config import Settings, get_settings
from app.platform.errors import (
    FileTooLargeError,
    FileTypeNotAllowedError,
    ForbiddenError,
    ImportConsumedError,
    ImportExpiredError,
    NotFoundError,
    UploadTooLargeError,
    UploadTypeNotAllowedError,
)
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelOutputInvalidError, ModelTimeoutError
from app.platform.storage import BlobStore
from app.platform.uow import UnitOfWork, unit_of_work

READ_IMPORT = "opportunities.read_import"
IMPORT_NOT_FOUND = "No import with this id."
IMPORT_CONSUMED = "This import was already used to create an Opportunity."
IMPORT_EXPIRED = "This import is older than 24 hours. Import the file again."
_IN_PROGRESS = tuple(sorted(s.value for s in IN_PROGRESS))
_RUNNING = (ImportStatus.RUNNING.value,)
_log = get_logger(__name__)


class ReadImport(JobPayload):
    import_id: UUID


def import_settings() -> Settings:
    """Settings for the handler (storage root, parse limits, chat profile). Tests replace
    this."""
    return get_settings()


# --- read model -----------------------------------------------------------------------------


def _view(record: ImportRecord) -> OpportunityImport:
    suggestions = (
        None if record.suggestions is None else ImportSuggestions.model_validate(record.suggestions)
    )
    return OpportunityImport(
        id=str(record.id),
        filename=record.filename,
        size_bytes=record.size_bytes,
        status=ImportStatus(record.status),
        error_code=None if record.error_code is None else ImportErrorCode(record.error_code),
        suggestions=suggestions,
        created_at=record.created_at,
    )


def _stored(suggestions: Suggestions) -> dict[str, Any]:
    def one(s: Suggestion | None) -> SuggestedValue | None:
        return None if s is None else SuggestedValue(value=s.value, quote=s.quote)

    return ImportSuggestions(
        title=one(suggestions.title),
        customer_name=one(suggestions.customer_name),
        industry=one(suggestions.industry),
        industry_inferred=suggestions.industry_inferred,
        products=[SuggestedValue(value=p.value, quote=p.quote) for p in suggestions.products],
        target_proposal_date=one(suggestions.target_proposal_date),
    ).model_dump(mode="json")


# --- commands and queries -------------------------------------------------------------------


def _uploader(actor: Principal) -> UUID:
    identity.authorize(actor, Action.OPPORTUNITY_CREATE)
    user_id = actor.user_id
    if user_id is None:
        raise ForbiddenError("Only a signed-in user can import a file.")
    return user_id


async def upload_import(
    uow: UnitOfWork,
    actor: Principal,
    incoming: IncomingFile,
    *,
    store: BlobStore,
    max_bytes: int,
    content_length: int | None = None,
) -> OpportunityImport:
    """Store one uploaded file as a `queued` import of the caller's and queue its reading."""
    uploader = _uploader(actor)
    try:
        upload = await intake.store_upload(
            incoming, store=store, max_bytes=max_bytes, content_length=content_length
        )
    except FileTooLargeError as exc:
        raise UploadTooLargeError(exc.detail) from None
    except FileTypeNotAllowedError as exc:
        raise UploadTypeNotAllowedError(exc.detail) from None
    import_id = new_id()
    await files.add_reference(uow, upload.sha256, upload.size)
    await repo.insert_import(
        uow,
        import_id=import_id,
        uploaded_by=uploader,
        file_sha256=upload.sha256,
        size_bytes=upload.size,
        filename=upload.filename,
    )
    await enqueue(uow, ReadImport(import_id=import_id))
    _log.info(
        "opportunities.import_uploaded",
        extra={
            "import_id": str(import_id),
            "kind": upload.kind.value,
            "size_bytes": upload.size,
            "actor_id": actor.actor.id,
        },
    )
    record = await repo.get(uow, import_id)
    if record is None:
        raise RuntimeError("inserted import not found")
    return _view(record)


async def _usable(
    uow: UnitOfWork,
    actor: Principal,
    import_id: UUID,
    *,
    for_update: bool = False,
    unconsumed: bool = False,
) -> ImportRecord:
    """The caller's import, not expired (404 for anyone else's, 410 once expired). With
    `unconsumed`, an import already used is 409, checked before expiry."""
    record = await repo.get(uow, import_id, for_update=for_update)
    if record is None or actor.user_id is None or record.uploaded_by != actor.user_id:
        raise NotFoundError(IMPORT_NOT_FOUND)
    if unconsumed and record.consumed_at is not None:
        raise ImportConsumedError(IMPORT_CONSUMED)
    if is_expired(record.created_at, await repo.now(uow)):
        raise ImportExpiredError(IMPORT_EXPIRED)
    return record


async def get_import(uow: UnitOfWork, actor: Principal, import_id: UUID) -> OpportunityImport:
    """The caller's import with its status and suggestions."""
    return _view(await _usable(uow, actor, import_id))


async def create_from_import(
    uow: UnitOfWork, actor: Principal, new: NewOpportunity, import_id: UUID
) -> Opportunity:
    """Create the Opportunity and add the import's file as its first Source, consuming the
    import, all in the caller's Unit of Work."""
    identity.authorize(actor, Action.OPPORTUNITY_CREATE)
    record = await _usable(uow, actor, import_id, for_update=True, unconsumed=True)
    if not await repo.consume(uow, import_id):
        raise ImportConsumedError(IMPORT_CONSUMED)
    created = await opportunities.create(uow, actor, new, from_import=True)
    source = await intake.add_stored_file(
        uow,
        actor,
        UUID(created.id),
        sha256=record.file_sha256,
        size=record.size_bytes,
        filename=record.filename,
    )
    _log.info(
        "opportunities.import_consumed",
        extra={
            "import_id": str(import_id),
            "opportunity_id": created.id,
            "source_id": source.id,
            "actor_id": actor.actor.id,
        },
    )
    return created


async def create(uow: UnitOfWork, actor: Principal, new: NewOpportunity) -> Opportunity:
    """`POST /opportunities`: from an import when `new.import_id` is set, else plain."""
    if new.import_id is None:
        return await opportunities.create(uow, actor, new)
    return await create_from_import(uow, actor, new, new.import_id)


# --- the job --------------------------------------------------------------------------------


def proposal(result: AgentResult) -> OpportunityIntakeOutput:
    """The agent's proposed suggestions, re-validated (AD-4). Raises
    `ModelOutputInvalidError` when the extension is missing or malformed."""
    try:
        return OpportunityIntakeOutput.model_validate(result.extensions.get(AGENT_ID))
    except ValueError:
        raise ModelOutputInvalidError(
            "The opportunity_intake_agent extension is not valid."
        ) from None


def checked(output: OpportunityIntakeOutput, text: str, today: date) -> Suggestions:
    return validate_suggestions(
        title=Candidate(output.title.value, output.title.quote),
        customer_name=Candidate(output.customer_name.value, output.customer_name.quote),
        industry=Candidate(output.industry.value, output.industry.quote),
        industry_inferred=output.industry_inferred,
        products=[Candidate(p.value, p.quote) for p in output.products],
        target_proposal_date=Candidate(
            output.target_proposal_date.value, output.target_proposal_date.quote
        ),
        text=text,
        today=today,
    )


def error_code(exc: BaseException) -> ImportErrorCode:
    if isinstance(exc, ModelTimeoutError):
        return ImportErrorCode.MODEL_TIMEOUT
    if isinstance(exc, ModelOutputInvalidError):
        return ImportErrorCode.OUTPUT_INVALID
    return ImportErrorCode.MODEL_UNAVAILABLE


async def _mark_failed(ctx: JobContext, import_id: UUID, code: ImportErrorCode) -> bool:
    async with unit_of_work(ctx.engine) as uow:
        return await repo.update_status(
            uow,
            import_id,
            from_statuses=_IN_PROGRESS,
            status=ImportStatus.FAILED.value,
            error_code=code.value,
        )


async def read_import(ctx: JobContext, payload: ReadImport) -> None:
    """The handler. On the job's final attempt any error first marks the import `failed`
    (best effort), so none is left `running` once its job is dead; then it re-raises."""
    ids = {"import_id": str(payload.import_id), "job_id": str(ctx.job_id)}
    try:
        await _read(ctx, payload)
    except asyncio.CancelledError:
        # The job's timeout (or a stopping worker) cancelled the read. On the final attempt
        # nothing will run it again, so record it as timed out, shielded from the
        # cancellation, then let the cancellation through.
        if ctx.attempt >= ctx.max_attempts:
            await _mark_failed_shielded(ctx, payload.import_id, ids)
        raise
    except Exception as exc:
        code = error_code(exc)
        if ctx.attempt >= ctx.max_attempts:
            try:
                recorded = await _mark_failed(ctx, payload.import_id, code)
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "opportunities.import_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "opportunities.import_failed",
                    extra={**ids, "error_code": code.value, "recorded": recorded},
                )
        else:
            _log.warning(
                "opportunities.import_retrying",
                extra={**ids, "exc_type": type(exc).__name__, "error_code": code.value},
            )
        raise


async def _mark_failed_shielded(ctx: JobContext, import_id: UUID, ids: dict[str, str]) -> None:
    write = asyncio.ensure_future(_mark_failed(ctx, import_id, ImportErrorCode.MODEL_TIMEOUT))
    try:
        recorded = await asyncio.shield(write)
    except asyncio.CancelledError:  # cancelled again: still let the write land
        await asyncio.wait({write})
        recorded = not write.cancelled() and write.exception() is None and write.result()
    except Exception as exc:
        _log.warning(
            "opportunities.import_fail_unrecorded", extra={**ids, "exc_type": type(exc).__name__}
        )
        return
    _log.info(
        "opportunities.import_failed",
        extra={**ids, "error_code": ImportErrorCode.MODEL_TIMEOUT.value, "recorded": recorded},
    )


async def _read(ctx: JobContext, payload: ReadImport) -> None:
    settings = import_settings()
    import_id = payload.import_id
    ids: dict[str, object] = {"import_id": str(import_id)}
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get(uow, import_id, for_update=True)
        if record is None or record.status not in _IN_PROGRESS:
            _log.info("opportunities.import_skipped", extra=ids)
            return
        await repo.update_status(
            uow, import_id, from_statuses=_IN_PROGRESS, status=ImportStatus.RUNNING.value
        )

    try:
        text = await intake.read_stored_text(
            BlobStore(settings.storage_dir),
            record.file_sha256,
            record.filename,
            timeout_s=settings.parse_timeout_s,
            max_memory_mb=settings.parse_max_memory_mb,
        )
    except intake.FileTextUnreadableError as exc:
        recorded = await _mark_failed(ctx, import_id, ImportErrorCode.UNREADABLE)
        _log.info(
            "opportunities.import_unreadable",
            extra={**ids, "parse_error_code": exc.code, "recorded": recorded},
        )
        return

    today = datetime.now(UTC).date()
    agent = OpportunityIntakeAgent(provider.current(), profile=settings.model_profile_chat)
    result = await agent.run(OpportunityIntakeTask(import_id=import_id, today=today, text=text))
    suggestions = checked(proposal(result), text, today)
    async with unit_of_work(ctx.engine) as uow:
        recorded = await repo.update_status(
            uow,
            import_id,
            from_statuses=_RUNNING,
            status=ImportStatus.SUCCEEDED.value,
            suggestions=_stored(suggestions),
        )
    _log.info(
        "opportunities.import_read",
        extra={
            **ids,
            "char_count": len(text),
            "suggestion_count": suggestion_count(suggestions),
            "recorded": recorded,
        },
    )


READ_IMPORT_JOB = register(
    JobType(
        name=READ_IMPORT,
        payload=ReadImport,
        handler=read_import,
        # Someone is waiting on the New Opportunity form.
        priority="interactive",
        # Above the parse limit plus the worst-case model call (3 x 120 s).
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=2.0,
        backoff_cap_s=10.0,
    )
)
