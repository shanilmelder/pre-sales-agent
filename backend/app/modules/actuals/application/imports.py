"""Importing Actuals from a file (Story 10.2; FR-49, AD-8, AD-18).

Every command and query here is for delivery managers who can record Actuals on the
Opportunity (`actuals.actual.import`, people only): anyone else who can read it gets 403,
everyone else the Opportunity's 404.

- `download_template` (`GET …/actuals/template`): the Baseline version's `.xlsx` template (one
  row per line: Line ID, `L{n}`, Integration Type, Work Package, Estimate h, then empty Actual
  columns), stored in `platform.storage` and returned as a short-lived signed link; traced
  `actuals.template.exported` with the Opportunity.
- `upload_import` (`POST …/actuals/imports`): one `.xlsx` or `.csv` file, checked as it
  streams (size limit `actuals_import_max_bytes` 413, extension allowlist 415, content 415:
  a ZIP with an `xl/` entry, or UTF-8 text) and stored content-addressed by SHA-256 with a
  `platform_files` reference, recorded `queued`, and an `actuals.import_file` job queued, in
  one Unit of Work. The api process never parses it.
- The `actuals.import_file` job (worker): reads the stored file in the parse sandbox
  (`adapters.import_cli` through `platform.parsing.runner`), finds the header row and keeps
  the raw rows (`domain.imports.table_rows`), and marks the import `parsed`. A file that
  can't be read marks it `failed` and the job goes `dead` at once (`PermanentJobError`); any
  other error is retried, and the last attempt marks it `failed` first.
- `get_import` / `latest_import` (`GET …/actuals/imports/{id}`, `…/latest`): the import and,
  once parsed, its preview: each row read and checked afresh with the manual-entry rules
  against the current Actuals (`record.check_items`), and whether the same file was already
  applied ("This file was already imported on 14 Oct").
- `retry_import` (`POST …/{id}/retry`): a `failed` import back to `queued` with a new job (409
  `parse_not_failed` otherwise).
- `apply_import` (`POST …/{id}/apply`, **Confirm**) with `If-Match` the Actuals tab's
  `row_version` the preview was checked against (412 when stale, 428 without): under the
  Opportunity lock, the import must be `parsed` (409), a repeated file needs `confirm_repeat`
  (409 `actuals_import_repeated`), and every row not excluded or blank is read and written
  through `record.apply_items`, the path of **Save Actuals**: any problem is 422
  `actual_invalid` with each row's problem ("Row 12: variance cause missing for a final
  Actual") and nothing is written. Otherwise each row's `actuals.actual.recorded` or
  `.corrected`, then one `actuals.import.completed`, and the import is `applied`.

Logs and job payloads hold ids, codes, sizes and counts only, never the file name or cells.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO, Literal, Protocol
from uuid import UUID

from app.modules.actuals.adapters import repository as repo
from app.modules.actuals.adapters.import_cli import PARSER_CSV, PARSER_XLSX
from app.modules.actuals.adapters.repository import ImportRecord
from app.modules.actuals.adapters.template_xlsx import (
    TemplateDocument,
    TemplateLine,
    file_name,
    render_template,
)
from app.modules.actuals.application.models import (
    ActualInput,
    ActualsImportApply,
    ActualsImportLatest,
    ActualsImportView,
    ActualsTemplate,
    AppliedCounts,
    AppliedImport,
    ImportCounts,
    ImportRowView,
)
from app.modules.actuals.application.record import (
    MAX_ROW_VERSION,
    STALE,
    apply_items,
    check_items,
    open_baseline,
    start_write,
)
from app.modules.actuals.application.view import (
    UNKNOWN_USER,
    Baseline,
    build_view,
    line_integration_types,
)
from app.modules.actuals.domain.actuals import CAUSE_LABELS, ActualKind
from app.modules.actuals.domain.imports import (
    ERROR_MESSAGES,
    IMPORT_EXTENSIONS,
    IMPORT_SUBJECT_TYPE,
    IN_PROGRESS,
    ImportErrorCode,
    ImportReadError,
    ImportStatus,
    RowEntry,
    duplicate_message,
    is_blank,
    read_row,
    row_message,
    rule_text,
    table_rows,
)
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.opportunities.application import public as opportunities
from app.platform import downloads, files, trace
from app.platform.concurrency import parse_if_match
from app.platform.config import Settings, get_settings
from app.platform.errors import (
    ActualInvalidError,
    ActualsImportAppliedError,
    ActualsImportNotReadyError,
    ActualsImportRepeatedError,
    ActualsNoBaselineError,
    DeliveryClosedError,
    ForbiddenError,
    NotFoundError,
    ParseNotFailedError,
    RowVersionMismatchError,
    UnprocessableError,
    UploadContentMismatchError,
    UploadTooLargeError,
    UploadTypeNotAllowedError,
)
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, PermanentJobError, enqueue, register
from app.platform.logging import get_logger
from app.platform.multipart import BodyTooLargeError, MultipartError
from app.platform.parsing import runner
from app.platform.parsing.rules import PERMANENT_CODES, ParseError, ParseErrorCode
from app.platform.parsing.runner import ParseTimeoutError
from app.platform.storage import BlobStore, BlobTooLargeError
from app.platform.trace.catalogue import ActualsImportCompleted, ActualsTemplateExported
from app.platform.uow import UnitOfWork, unit_of_work
from app.platform.upload_validation import (
    EMPTY_MESSAGE,
    InvalidFilenameError,
    clean_filename,
    content_matches,
    extension,
    mismatch_message,
    too_large_message,
)

IMPORT_FILE = "actuals.import_file"
CHILD_MODULE = "app.modules.actuals.adapters.import_cli"
OPPORTUNITY_SUBJECT_TYPE = "opportunities.opportunity"
MULTIPART_OVERHEAD = 64 * 1024
MISSING_FILE_DETAIL = "Invalid fields: body.file"
IMPORT_NOT_FOUND = "No import with this id in this Opportunity."
NOT_FAILED = "Only an import whose file couldn't be read can be retried."
NOT_READY = "This import's file hasn't been read yet, or reading it failed."
ALREADY_APPLIED = "This import was already applied."
NOTHING_TO_IMPORT = "Nothing to import: every row is blank or excluded."
TYPE_RULE = "Rejected: only .xlsx and .csv files can be imported"
REPEAT_TICK = " Tick “Import it again” to import it once more."
_PARSERS = (PARSER_XLSX, PARSER_CSV)
RowStatus = Literal["create", "correct", "invalid", "skipped"]
_log = get_logger(__name__)

__all__ = [
    "IMPORT_FILE",
    "IMPORT_FILE_JOB",
    "ImportActualsFile",
    "ImportStorage",
    "apply_import",
    "download_template",
    "get_import",
    "latest_import",
    "retry_import",
    "upload_import",
]


class IncomingFile(Protocol):
    """An uploaded file read as it arrives (`app.platform.multipart.MultipartFile`)."""

    async def filename(self) -> str: ...

    def chunks(self) -> AsyncIterator[bytes]: ...


class ImportActualsFile(JobPayload):
    import_id: UUID


@dataclass(frozen=True, slots=True)
class ImportStorage:
    """Where uploads and the template go, and how the template link is signed."""

    store: BlobStore
    signing_key: str
    ttl_s: int


def import_settings() -> Settings:
    """Settings for the job (storage root, parse limits). Tests replace this."""
    return get_settings()


def max_body_bytes(max_bytes: int) -> int:
    """The largest request body an upload of at most `max_bytes` may need."""
    return max_bytes + MULTIPART_OVERHEAD


async def _importer(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> tuple[Resource, UUID]:
    """The delivery manager who may import here (404 unless they can read it, then 403)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ACTUAL_IMPORT, resource)
    if actor.user_id is None:  # pragma: no cover - HUMAN_ONLY_ACTIONS denies every non-person
        raise ForbiddenError("Only people can import Actuals.")
    return resource, actor.user_id


async def _one_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content


# --- the template ---------------------------------------------------------------------------


async def download_template(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, storage: ImportStorage
) -> ActualsTemplate:
    """The Baseline version's import template as a signed link (module docstring)."""
    await _importer(uow, actor, opportunity_id)
    baseline = await open_baseline(uow, opportunity_id)
    types = await line_integration_types(uow, baseline.lines)
    document = TemplateDocument(
        estimate_version=baseline.version,
        lines=[
            TemplateLine(
                line_id=str(line.id),
                label=f"L{number}",
                integration_type=", ".join(t.name for t in types.get(line.id, [])),
                work_package="",
                estimate_hours=float(line.effort_hours),
            )
            for number, line in enumerate(baseline.lines, start=1)
        ],
        kinds=[k.value.capitalize() for k in (ActualKind.FINAL, ActualKind.MILESTONE)],
        causes=list(CAUSE_LABELS.values()),
        assumptions=[
            (f"A{a.position}", a.kind.capitalize(), a.wording) for a in baseline.assumptions
        ],
    )
    content = await asyncio.to_thread(render_template, document)
    blob = await storage.store.put_stream(_one_chunk(content), max_bytes=len(content))
    name = file_name(baseline.version)
    token, expires_at = downloads.sign(
        storage.signing_key, sha256=blob.sha256, filename=name, ttl_s=storage.ttl_s
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ActualsTemplateExported(
            estimate_version_id=str(baseline.version_id),
            estimate_version=baseline.version,
            line_count=len(baseline.lines),
        ),
        subject_type=OPPORTUNITY_SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "actuals.template_exported",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": actor.actor.id,
            "line_count": len(baseline.lines),
            "size": blob.size,
        },
    )
    return ActualsTemplate(
        url=downloads.link_for(token),
        file_name=name,
        expires_at=expires_at,
        line_count=len(baseline.lines),
    )


# --- upload ---------------------------------------------------------------------------------


async def _store(
    incoming: IncomingFile, store: BlobStore, max_bytes: int, content_length: int | None
) -> tuple[str, int, str, str]:
    """Check and store the file: SHA-256, size, filename and kind. Nothing stored on a
    rejection."""
    if content_length is not None and content_length > max_body_bytes(max_bytes):
        raise UploadTooLargeError(too_large_message(max_bytes))
    try:
        filename = clean_filename(await incoming.filename())
        ext = extension(filename)
        kind = IMPORT_EXTENSIONS.get(ext)
        if kind is None:
            raise UploadTypeNotAllowedError(TYPE_RULE)

        def check(stream: BinaryIO, size: int) -> None:
            if size == 0:
                raise UnprocessableError(EMPTY_MESSAGE)
            if not content_matches(ext, stream):
                raise UploadContentMismatchError(mismatch_message(ext))

        blob = await store.put_stream(incoming.chunks(), max_bytes, check=check)
    except (BlobTooLargeError, BodyTooLargeError):
        raise UploadTooLargeError(too_large_message(max_bytes)) from None
    except InvalidFilenameError as exc:
        raise UnprocessableError(exc.message) from None
    except MultipartError:
        raise UnprocessableError(MISSING_FILE_DETAIL) from None
    return blob.sha256, blob.size, filename, kind


async def upload_import(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    incoming: IncomingFile,
    *,
    store: BlobStore,
    max_bytes: int,
    content_length: int | None = None,
) -> ActualsImportView:
    """Store one file as a `queued` import and queue its reading (module docstring)."""
    resource, user_id = await _importer(uow, actor, opportunity_id)
    await open_baseline(uow, opportunity_id)  # 409 before anything is stored
    sha256, size, filename, kind = await _store(incoming, store, max_bytes, content_length)
    import_id = new_id()
    await files.add_reference(uow, sha256, size)
    await repo.insert_import(
        uow,
        import_id=import_id,
        opportunity_id=opportunity_id,
        uploaded_by=user_id,
        file_sha256=sha256,
        size_bytes=size,
        filename=filename,
        file_kind=kind,
    )
    await enqueue(uow, ImportActualsFile(import_id=import_id), opportunity_id=opportunity_id)
    _log.info(
        "actuals.import_uploaded",
        extra={
            "opportunity_id": str(opportunity_id),
            "import_id": str(import_id),
            "kind": kind,
            "size_bytes": size,
            "actor_id": actor.actor.id,
        },
    )
    record = await repo.get_import(uow, import_id)
    assert record is not None
    return await _view(uow, actor, resource, record)


# --- reading the rows (preview and apply) ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Rows:
    """An import's rows read against the Baseline: blank rows, rows with read problems, and
    the entries to check (with each one's row)."""

    skipped: list[int]
    problems: dict[int, list[str]]
    entries: list[RowEntry]
    excluded: list[int]


def _read_rows(record: ImportRecord, baseline: Baseline, excluded: frozenset[int]) -> _Rows:
    line_ids = {line.id for line in baseline.lines}
    assumptions = {a.position: a.id for a in baseline.assumptions}
    skipped: list[int] = []
    problems: dict[int, list[str]] = {}
    entries: list[RowEntry] = []
    left_out: list[int] = []
    for raw in record.rows or []:
        number = int(raw["row"])
        values: dict[str, str] = {str(k): str(v) for k, v in dict(raw["values"]).items()}
        if is_blank(values):
            skipped.append(number)
            continue
        if number in excluded:
            left_out.append(number)
            continue
        entry, found = read_row(
            number,
            values,
            baseline_version=baseline.version,
            line_ids=line_ids,
            assumptions=assumptions,
        )
        if entry is None:
            problems[number] = found
        else:
            entries.append(entry)
    return _Rows(skipped=skipped, problems=problems, entries=entries, excluded=left_out)


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _input(entry: RowEntry) -> ActualInput:
    return ActualInput(
        line_id=entry.line_id,
        kind=entry.kind,
        milestone_label=entry.milestone_label,
        effort_hours=float(entry.effort_hours),
        duration_days=_float(entry.duration_days),
        cost_minor=entry.cost_minor,
        currency=entry.currency,
        variance_cause=entry.variance_cause,
        note=entry.note,
        failed_assumption_ids=entry.failed_assumption_ids,
    )


def _row_errors(
    entries: Sequence[RowEntry], errors: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Rule errors by entry index as row problems: `item` is the sheet row, `message` reads
    "Row N: ...". A missing reason with no row is the batch's."""
    found: list[dict[str, Any]] = []
    for error in errors:
        index = error.get("item")
        if index is None or not 0 <= index < len(entries):
            found.append(error)
            continue
        row = entries[index].row
        text = rule_text(str(error["field"]), str(error["message"]))
        found.append({"item": row, "field": error["field"], "message": row_message(row, text)})
    return found


async def _repeat(uow: UnitOfWork, record: ImportRecord) -> ImportRecord | None:
    return await repo.applied_with_sha(
        uow, record.opportunity_id, record.file_sha256, excluding=record.id
    )


async def _preview(
    uow: UnitOfWork,
    actor: Principal,
    resource: Resource,
    record: ImportRecord,
    baseline: Baseline,
) -> tuple[list[ImportRowView], ImportCounts]:
    rows = _read_rows(record, baseline, frozenset())
    entries = rows.entries
    checked = await check_items(
        uow,
        actor,
        resource,
        record.opportunity_id,
        baseline,
        [_input(e) for e in entries],
        None,
        item_reasons=[e.correction_reason for e in entries],
    )
    reason_missing: set[int] = set()
    rule_problems: dict[int, list[str]] = {}
    for error in _row_errors(entries, checked.errors):
        if error["item"] is None:
            continue
        if error["field"] == "reason":
            reason_missing.add(int(error["item"]))
        else:
            rule_problems.setdefault(int(error["item"]), []).append(str(error["message"]))
    correcting = {
        entries[plan.index].row
        for plan, _, _ in checked.plans
        if plan.existing is not None and plan.index is not None
    }
    by_id = {line.id: (f"L{n}", line) for n, line in enumerate(baseline.lines, start=1)}
    entry_by_row = {e.row: e for e in entries}
    views: list[ImportRowView] = []
    for raw in record.rows or []:
        number = int(raw["row"])
        entry = entry_by_row.get(number)
        problems = rows.problems.get(number, []) + rule_problems.get(number, [])
        status: RowStatus
        if number in rows.skipped:
            status = "skipped"
        elif problems:
            status = "invalid"
        elif number in correcting:
            status = "correct"
        else:
            status = "create"
        found = None if entry is None else by_id.get(entry.line_id)
        views.append(
            ImportRowView(
                row=number,
                status=status,
                line_id=None if entry is None else str(entry.line_id),
                line_label=None if found is None else found[0],
                line_title=None if found is None else found[1].title,
                estimate_hours=None if found is None else float(found[1].effort_hours),
                kind=None if entry is None else entry.kind,
                effort_hours=None if entry is None else float(entry.effort_hours),
                variance_cause=None if entry is None else entry.variance_cause,
                correction_reason=None if entry is None else entry.correction_reason,
                reason_missing=status == "correct" and number in reason_missing,
                problems=problems,
            )
        )
    counts = ImportCounts(
        create=sum(1 for v in views if v.status == "create"),
        correct=sum(1 for v in views if v.status == "correct"),
        invalid=sum(1 for v in views if v.status == "invalid"),
        skipped=sum(1 for v in views if v.status == "skipped"),
    )
    return views, counts


async def _view(
    uow: UnitOfWork, actor: Principal, resource: Resource, record: ImportRecord
) -> ActualsImportView:
    names = await identity.user_names(uow, {record.uploaded_by})
    # Read before the rows are checked: a save in between then fails Confirm's If-Match
    # rather than letting a preview checked against older Actuals through.
    row_version = await repo.change_count(uow, record.opportunity_id)
    rows: list[ImportRowView] = []
    counts: ImportCounts | None = None
    version: int | None = None
    repeat = None
    if record.status == ImportStatus.PARSED:
        try:
            baseline: Baseline | None = await open_baseline(uow, record.opportunity_id)
        except (ActualsNoBaselineError, DeliveryClosedError):
            baseline = None  # nothing can be applied any more; Confirm answers 409
        if baseline is not None:
            version = baseline.version
            rows, counts = await _preview(uow, actor, resource, record, baseline)
        repeat = await _repeat(uow, record)
    code = None if record.error_code is None else ImportErrorCode(record.error_code)
    applied = None
    if record.status == ImportStatus.APPLIED:
        applied = AppliedCounts(
            created=record.created_count or 0,
            corrected=record.corrected_count or 0,
            excluded=record.excluded_count or 0,
            skipped=record.skipped_count or 0,
        )
    return ActualsImportView(
        id=str(record.id),
        filename=record.filename,
        size_bytes=record.size_bytes,
        file_kind="csv" if record.file_kind == "csv" else "xlsx",
        status=ImportStatus(record.status).value,
        error_code=None if code is None else code.value,
        error_message=None if code is None else ERROR_MESSAGES[code],
        uploaded_by_name=names.get(record.uploaded_by, UNKNOWN_USER),
        created_at=record.created_at,
        estimate_version=version,
        rows=rows,
        counts=counts,
        repeat_applied_at=None if repeat is None else repeat.applied_at,
        repeat_message=None
        if repeat is None or repeat.applied_at is None
        else duplicate_message(repeat.applied_at),
        applied_at=record.applied_at,
        applied=applied,
        row_version=row_version,
    )


async def _owned(
    uow: UnitOfWork, opportunity_id: UUID, import_id: UUID, *, for_update: bool = False
) -> ImportRecord:
    record = await repo.get_import(uow, import_id, for_update=for_update)
    if record is None or record.opportunity_id != opportunity_id:
        raise NotFoundError(IMPORT_NOT_FOUND)
    return record


async def get_import(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, import_id: UUID
) -> ActualsImportView:
    """The import and, once parsed, its preview checked now (module docstring)."""
    resource, _ = await _importer(uow, actor, opportunity_id)
    return await _view(uow, actor, resource, await _owned(uow, opportunity_id, import_id))


async def latest_import(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> ActualsImportLatest:
    """The Opportunity's most recent import, with its preview when parsed."""
    resource, _ = await _importer(uow, actor, opportunity_id)
    record = await repo.latest_import(uow, opportunity_id)
    return ActualsImportLatest(
        latest=None if record is None else await _view(uow, actor, resource, record)
    )


async def retry_import(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, import_id: UUID
) -> ActualsImportView:
    """Read a failed import's file again: `queued` with a new job (409 unless `failed`)."""
    resource, _ = await _importer(uow, actor, opportunity_id)
    record = await _owned(uow, opportunity_id, import_id, for_update=True)
    if record.status != ImportStatus.FAILED or not await repo.update_import_status(
        uow,
        import_id,
        from_statuses=(ImportStatus.FAILED.value,),
        status=ImportStatus.QUEUED.value,
    ):
        raise ParseNotFailedError(NOT_FAILED)
    await enqueue(uow, ImportActualsFile(import_id=import_id), opportunity_id=opportunity_id)
    _log.info(
        "actuals.import_retried",
        extra={
            "opportunity_id": str(opportunity_id),
            "import_id": str(import_id),
            "error_code": record.error_code,
            "actor_id": actor.actor.id,
        },
    )
    return await _view(uow, actor, resource, await _owned(uow, opportunity_id, import_id))


async def apply_import(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    import_id: UUID,
    body: ActualsImportApply,
    if_match: str | None,
) -> AppliedImport:
    """**Confirm**: every row in one Unit of Work, or nothing (module docstring)."""
    resource, user_id = await start_write(uow, actor, opportunity_id, Action.ACTUAL_IMPORT)
    identity.authorize(actor, Action.ACTUAL_RECORD, resource)
    record = await _owned(uow, opportunity_id, import_id, for_update=True)
    if record.status == ImportStatus.APPLIED:
        raise ActualsImportAppliedError(ALREADY_APPLIED)
    if record.status != ImportStatus.PARSED:
        raise ActualsImportNotReadyError(NOT_READY)
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or expected != await repo.change_count(uow, opportunity_id):
        raise RowVersionMismatchError(STALE)
    repeat = await _repeat(uow, record)
    if repeat is not None and repeat.applied_at is not None and not body.confirm_repeat:
        raise ActualsImportRepeatedError(
            duplicate_message(repeat.applied_at) + "." + REPEAT_TICK,
            applied_at=repeat.applied_at.isoformat(),
        )
    baseline = await open_baseline(uow, opportunity_id)
    rows = _read_rows(record, baseline, frozenset(body.excluded_rows))
    read_errors = [
        {"item": row, "field": "row", "message": message}
        for row, messages in sorted(rows.problems.items())
        for message in messages
    ]
    if not rows.entries and not read_errors:
        nothing = {"item": None, "field": "rows", "message": NOTHING_TO_IMPORT}
        raise ActualInvalidError(NOTHING_TO_IMPORT, errors=[nothing])
    entries = rows.entries
    checked = await apply_items(
        uow,
        actor,
        resource,
        user_id,
        opportunity_id,
        [_input(e) for e in entries],
        body.reason,
        item_reasons=[e.correction_reason for e in entries],
        read_errors=read_errors,
        describe=lambda errors: _row_errors(entries, errors),
    )
    counts = AppliedCounts(
        created=checked.recorded,
        corrected=checked.corrected,
        excluded=len(rows.excluded),
        skipped=len(rows.skipped),
    )
    if not await repo.mark_applied(
        uow,
        import_id,
        applied_by=user_id,
        created=counts.created,
        corrected=counts.corrected,
        excluded=counts.excluded,
        skipped=counts.skipped,
    ):  # pragma: no cover - the row lock and status check above make this unreachable
        raise ActualsImportAppliedError(ALREADY_APPLIED)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ActualsImportCompleted(
            import_id=str(import_id),
            file_sha256=record.file_sha256,
            estimate_version_id=str(baseline.version_id),
            estimate_version=baseline.version,
            created_count=counts.created,
            corrected_count=counts.corrected,
            excluded_count=counts.excluded,
            skipped_count=counts.skipped,
            repeated_file=repeat is not None,
        ),
        subject_type=IMPORT_SUBJECT_TYPE,
        subject_id=import_id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "actuals.import_applied",
        extra={
            "opportunity_id": str(opportunity_id),
            "import_id": str(import_id),
            "created_count": counts.created,
            "corrected_count": counts.corrected,
            "excluded_count": counts.excluded,
            "skipped_count": counts.skipped,
            "actor_id": actor.actor.id,
        },
    )
    applied = await _owned(uow, opportunity_id, import_id)
    return AppliedImport(
        imported=await _view(uow, actor, resource, applied),
        actuals=await build_view(uow, actor, resource, opportunity_id),
    )


# --- the job --------------------------------------------------------------------------------


async def _mark_failed(ctx: JobContext, import_id: UUID, code: ImportErrorCode) -> bool:
    async with unit_of_work(ctx.engine) as uow:
        return await repo.update_import_status(
            uow,
            import_id,
            from_statuses=IN_PROGRESS,
            status=ImportStatus.FAILED.value,
            error_code=code.value,
        )


def _final_code(exc: BaseException) -> ImportErrorCode:
    if isinstance(exc, ParseTimeoutError):
        return ImportErrorCode.TIMEOUT
    return ImportErrorCode.UNREADABLE


def _parse_code(code: ParseErrorCode) -> ImportErrorCode:
    if code == ParseErrorCode.TOO_LARGE_OUTPUT:
        return ImportErrorCode.TOO_LARGE
    return ImportErrorCode.UNREADABLE


class StoredFileMissingError(RuntimeError):
    """The import's stored file isn't in the store (yet): retried."""


async def import_file(ctx: JobContext, payload: ImportActualsFile) -> None:
    """The handler. A file that can't be read is `failed` at once and the job goes `dead`
    (`PermanentJobError`). Any other error is retried; on the final attempt the import is
    first marked `failed` (`timeout` for a timed-out child, else `unreadable`), best effort,
    so none is left `running` once its job is dead. The runner enforces the job's timeout by
    cancelling the handler: on the final attempt a cancellation also marks it `failed`
    (`timeout`), shielded from that cancellation, before it goes on."""
    ids = {"import_id": str(payload.import_id), "job_id": str(ctx.job_id)}
    try:
        await _read(ctx, payload)
    except PermanentJobError:
        raise
    except asyncio.CancelledError:
        if ctx.attempt >= ctx.max_attempts:
            try:
                recorded = await asyncio.shield(
                    _mark_failed(ctx, payload.import_id, ImportErrorCode.TIMEOUT)
                )
            except BaseException as mark_exc:  # best effort: the cancellation still wins
                _log.warning(
                    "actuals.import_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "actuals.import_failed",
                    extra={
                        **ids,
                        "error_code": ImportErrorCode.TIMEOUT.value,
                        "recorded": recorded,
                    },
                )
        raise
    except Exception as exc:
        if ctx.attempt >= ctx.max_attempts:
            code = _final_code(exc)
            try:
                recorded = await _mark_failed(ctx, payload.import_id, code)
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "actuals.import_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "actuals.import_failed",
                    extra={**ids, "error_code": code.value, "recorded": recorded},
                )
        else:
            _log.warning("actuals.import_retrying", extra={**ids, "exc_type": type(exc).__name__})
        raise


async def _fail_permanently(ctx: JobContext, import_id: UUID, code: ImportErrorCode) -> None:
    recorded = await _mark_failed(ctx, import_id, code)
    _log.info(
        "actuals.import_failed",
        extra={"import_id": str(import_id), "error_code": code.value, "recorded": recorded},
    )
    raise PermanentJobError(f"import file unreadable: {code.value}")


def _table(text: str) -> list[tuple[int, list[Any]]]:
    data = json.loads(text)
    if not isinstance(data, list):
        raise ImportReadError(ImportErrorCode.UNREADABLE)
    table: list[tuple[int, list[Any]]] = []
    for entry in data:
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not isinstance(entry[0], int)
            or not isinstance(entry[1], list)
        ):
            raise ImportReadError(ImportErrorCode.UNREADABLE)
        table.append((entry[0], entry[1]))
    return table


async def _read(ctx: JobContext, payload: ImportActualsFile) -> None:
    settings = import_settings()
    store = BlobStore(settings.storage_dir)
    import_id = payload.import_id
    async with unit_of_work(ctx.engine) as uow:
        record = await repo.get_import(uow, import_id, for_update=True)
        if record is None or record.status not in IN_PROGRESS:
            _log.info("actuals.import_skipped", extra={"import_id": str(import_id)})
            return
        await repo.update_import_status(
            uow, import_id, from_statuses=IN_PROGRESS, status=ImportStatus.RUNNING.value
        )

    path = store.path_for(record.file_sha256)
    if not await asyncio.to_thread(Path.is_file, path):
        raise StoredFileMissingError("stored file missing")
    try:
        output = await runner.run_parse(
            path,
            f".{record.file_kind}",
            timeout_s=settings.parse_timeout_s,
            max_memory_mb=settings.parse_max_memory_mb,
            child_module=CHILD_MODULE,
        )
    except ParseError as exc:
        if exc.code not in PERMANENT_CODES:
            raise  # retryable; marked on the final attempt by `import_file`
        await _fail_permanently(ctx, import_id, _parse_code(exc.code))
        return  # pragma: no cover - `_fail_permanently` always raises
    if output.parser not in _PARSERS:  # pragma: no cover - our own child names its parser
        await _fail_permanently(ctx, import_id, ImportErrorCode.UNREADABLE)
    try:
        rows = table_rows(_table(output.text))
    except ImportReadError as exc:
        await _fail_permanently(ctx, import_id, exc.code)
        return  # pragma: no cover
    except ValueError:  # not JSON
        await _fail_permanently(ctx, import_id, ImportErrorCode.UNREADABLE)
        return  # pragma: no cover
    async with unit_of_work(ctx.engine) as uow:
        recorded = await repo.update_import_status(
            uow,
            import_id,
            from_statuses=(ImportStatus.RUNNING.value,),
            status=ImportStatus.PARSED.value,
            rows=rows,
        )
    _log.info(
        "actuals.import_read",
        extra={"import_id": str(import_id), "row_count": len(rows), "recorded": recorded},
    )


IMPORT_FILE_JOB = register(
    JobType(
        name=IMPORT_FILE,
        payload=ImportActualsFile,
        handler=import_file,
        # A delivery manager is waiting on the preview.
        priority="interactive",
        # Above the largest `PSA_PARSE_TIMEOUT_S` (600 s), so the child's own limit fires first.
        timeout_s=720.0,
        max_attempts=2,
        backoff_base_s=5.0,
        backoff_cap_s=60.0,
    )
)
