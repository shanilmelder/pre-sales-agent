"""Opportunity Source commands and queries (Story 2.1).

`add_file` (Part A) and `add_text` (Part B, pasted text) follow the AD-3 path in the
caller's Unit of Work: authorize, validate, write, trace. Access goes through the
Opportunity (`opportunities.readable_resource`):

- listing: anyone who can read the Opportunity;
- adding: its owner and collaborators (`intake.source.add`, any role); other readers get
  403 `forbidden`, everyone else the Opportunity's 404 `not_found`.

Pasted text is trimmed, checked (`clean_pasted_text`) and stored UTF-8 encoded as a
`note` Source named `Pasted text`, through the same write path as an upload.

A rejected upload or paste stores nothing: an upload's type is checked from the filename
before any bytes are read, its size while they stream, and its content before the blob is
stored; pasted text is checked in full before it is stored.

Identical bytes added again to the same Opportunity (any filename, pasted or not) become the next
version of the Source that already holds them; different bytes are always a new Source.
Every added version appends one `intake.source.added` event, and gets a `queued` parse row
and an `intake.parse_source` job (Story 2.2 Part B) in the same Unit of Work. Adding a
Source never changes the Opportunity's `row_version`. Logs and trace payloads hold ids,
kinds and sizes only.
"""

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.intake.adapters import repository
from app.modules.intake.adapters.repository import SourceRecord
from app.modules.intake.application.jobs import enqueue_parse
from app.modules.intake.application.models import Source, SourceList, SourceParse
from app.modules.intake.domain.parsing import ParseErrorCode, ParseStatus
from app.modules.intake.domain.sources import (
    EMPTY_MESSAGE,
    PASTED_TEXT_FILENAME,
    PASTED_TEXT_KIND,
    SUBJECT_TYPE,
    TEXT_MAX_CHARS,
    InvalidFilenameError,
    PastedTextEmptyError,
    PastedTextTooLongError,
    PastedTextUnsupportedError,
    SourceKind,
    clean_filename,
    clean_pasted_text,
    content_matches,
    extension,
    kind_for,
    mismatch_message,
    too_large_message,
    type_rejected_message,
)
from app.modules.opportunities.application import public as opportunities
from app.modules.opportunities.application.public import UserRef
from app.platform import files, trace
from app.platform.errors import (
    FileContentMismatchError,
    FileEmptyError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    ForbiddenError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.multipart import BodyTooLargeError, MultipartError
from app.platform.storage import BlobStore, BlobTooLargeError, StoredBlob
from app.platform.trace.catalogue import IntakeSourceAdded
from app.platform.uow import UnitOfWork

MULTIPART_OVERHEAD = 64 * 1024
"""Room on top of the file size for the multipart framing (boundaries, part headers)."""
TEXT_BODY_MAX_BYTES = TEXT_MAX_CHARS * 12 + 64 * 1024
"""The largest pasted-text JSON body read: every character as a 12-byte surrogate-pair
escape, plus room for whitespace and the surrounding JSON."""
MISSING_FILE_DETAIL = "Invalid fields: body.file"
UNKNOWN_USER = "Unknown user"
_log = get_logger(__name__)


class IncomingFile(Protocol):
    """An uploaded file read as it arrives (`app.platform.multipart.MultipartFile`)."""

    async def filename(self) -> str: ...

    def chunks(self) -> AsyncIterator[bytes]: ...


def max_body_bytes(max_bytes: int) -> int:
    """The largest request body an upload of at most `max_bytes` may need."""
    return max_bytes + MULTIPART_OVERHEAD


# --- queries --------------------------------------------------------------------------------


def _parse(record: SourceRecord) -> SourceParse | None:
    if record.parse_status is None:
        return None
    return SourceParse(
        status=ParseStatus(record.parse_status),
        error_code=(
            None if record.parse_error_code is None else ParseErrorCode(record.parse_error_code)
        ),
    )


async def _sources(uow: UnitOfWork, records: Iterable[SourceRecord]) -> list[Source]:
    records = list(records)
    names = await identity.user_names(uow, {r.uploaded_by for r in records})
    return [
        Source(
            id=str(r.id),
            kind=SourceKind(r.kind),
            filename=r.filename,
            version=r.version,
            version_count=r.version_count,
            size_bytes=r.size_bytes,
            uploaded_by=UserRef(id=str(r.uploaded_by), name=names.get(r.uploaded_by, UNKNOWN_USER)),
            uploaded_at=r.uploaded_at,
            created_at=r.created_at,
            parse=_parse(r),
        )
        for r in records
    ]


async def list_sources(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> SourceList:
    """The Opportunity's Sources, newest first, each with its latest version."""
    await opportunities.readable_resource(uow, actor, opportunity_id)
    return SourceList(items=await _sources(uow, await repository.list_for(uow, opportunity_id)))


# --- commands -------------------------------------------------------------------------------


async def _authorized_uploader(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> UUID:
    """The signed-in user allowed to add Sources to the Opportunity (404, then 403)."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.SOURCE_ADD, resource)
    uploader = actor.user_id
    if uploader is None:
        raise ForbiddenError("Only a signed-in user can add Sources.")
    return uploader


@dataclass(frozen=True, slots=True)
class StoredUpload:
    """An uploaded file checked and stored in `platform.storage`, not yet a Source (an
    Opportunity import holds one until the Opportunity is created)."""

    sha256: str
    size: int
    filename: str
    kind: SourceKind


async def store_upload(
    incoming: IncomingFile,
    *,
    store: BlobStore,
    max_bytes: int,
    content_length: int | None = None,
) -> StoredUpload:
    """Check and store an uploaded file exactly as a Source upload is checked: the type from
    the filename before any byte is read, the size as it streams, the content before the
    blob is stored. A rejected file stores nothing. No authorization and no database: the
    caller authorizes first and records the blob in its Unit of Work."""
    if content_length is not None and content_length > max_body_bytes(max_bytes):
        raise FileTooLargeError(too_large_message(max_bytes))

    try:
        filename = clean_filename(await incoming.filename())
        kind = kind_for(filename)
        if kind is None:
            raise FileTypeNotAllowedError(type_rejected_message(filename))
        ext = extension(filename)

        def check(stream: BinaryIO, size: int) -> None:
            if size == 0:
                raise FileEmptyError(EMPTY_MESSAGE)
            if not content_matches(ext, stream):
                raise FileContentMismatchError(mismatch_message(ext))

        blob = await store.put_stream(incoming.chunks(), max_bytes, check=check)
    except (BlobTooLargeError, BodyTooLargeError):
        raise FileTooLargeError(too_large_message(max_bytes)) from None
    except InvalidFilenameError as exc:
        raise UnprocessableError(exc.message) from None
    except MultipartError:
        raise UnprocessableError(MISSING_FILE_DETAIL) from None
    return StoredUpload(sha256=blob.sha256, size=blob.size, filename=filename, kind=kind)


async def add_file(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    incoming: IncomingFile,
    *,
    store: BlobStore,
    max_bytes: int,
    content_length: int | None = None,
) -> Source:
    """Add an uploaded file as a Source (or as the next version of the Source that already
    holds the same bytes). `content_length` is the request's, checked before any byte is
    read; the file itself is counted as it streams."""
    uploader = await _authorized_uploader(uow, actor, opportunity_id)
    upload = await store_upload(
        incoming, store=store, max_bytes=max_bytes, content_length=content_length
    )
    return await _record(
        uow,
        actor,
        opportunity_id,
        uploader,
        blob=StoredBlob(sha256=upload.sha256, size=upload.size),
        kind=upload.kind,
        filename=upload.filename,
    )


async def add_stored_file(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    *,
    sha256: str,
    size: int,
    filename: str,
) -> Source:
    """Add a file already checked and stored by `store_upload` (e.g. an Opportunity import)
    as a Source, through the same write path as an upload: authorized like one, versioned,
    referenced, traced (`intake.source.added`) and queued for parsing in the caller's Unit
    of Work."""
    uploader = await _authorized_uploader(uow, actor, opportunity_id)
    kind = kind_for(filename)
    if kind is None:
        raise FileTypeNotAllowedError(type_rejected_message(filename))
    return await _record(
        uow,
        actor,
        opportunity_id,
        uploader,
        blob=StoredBlob(sha256=sha256, size=size),
        kind=kind,
        filename=filename,
    )


async def add_text(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    text: str,
    *,
    store: BlobStore,
) -> Source:
    """Add pasted text as a `note` Source named `Pasted text` (Story 2.1 Part B). The
    trimmed text is stored UTF-8 encoded exactly like a `.txt` upload, so identical bytes
    become the next version of the Source already holding them, pasted or uploaded."""
    uploader = await _authorized_uploader(uow, actor, opportunity_id)
    try:
        cleaned = clean_pasted_text(text)
    except PastedTextEmptyError as exc:
        raise FileEmptyError(exc.message) from None
    except PastedTextTooLongError as exc:
        raise FileTooLargeError(exc.message) from None
    except PastedTextUnsupportedError as exc:
        raise FileContentMismatchError(exc.message) from None
    data = cleaned.encode("utf-8")

    async def single_chunk() -> AsyncIterator[bytes]:
        yield data

    blob = await store.put_stream(single_chunk(), len(data))
    return await _record(
        uow,
        actor,
        opportunity_id,
        uploader,
        blob=blob,
        kind=PASTED_TEXT_KIND,
        filename=PASTED_TEXT_FILENAME,
    )


async def _record(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    uploader: UUID,
    *,
    blob: StoredBlob,
    kind: SourceKind,
    filename: str,
) -> Source:
    """Write a stored blob as a new Source, or as the next version of the Source in this
    Opportunity that already holds the same bytes; reference the blob, trace it, and
    return the Source as read back."""
    await repository.lock_content(uow, opportunity_id, blob.sha256)
    source_id = await repository.source_with_content(uow, opportunity_id, blob.sha256)
    if source_id is None:
        source_id = new_id()
        await repository.insert_source(
            uow,
            source_id=source_id,
            opportunity_id=opportunity_id,
            kind=kind.value,
            created_by=uploader,
        )
        version, source_kind = 1, kind.value
    else:
        version, source_kind = await repository.next_version(uow, source_id)
    await files.add_reference(uow, blob.sha256, blob.size)
    await repository.insert_version(
        uow,
        source_id=source_id,
        version=version,
        file_sha256=blob.sha256,
        filename=filename,
        size_bytes=blob.size,
        uploaded_by=uploader,
    )
    await repository.insert_parse(uow, source_id=source_id, version=version)
    await enqueue_parse(uow, source_id=source_id, version=version, opportunity_id=opportunity_id)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=IntakeSourceAdded(version=version, kind=source_kind, size_bytes=blob.size),
        subject_type=SUBJECT_TYPE,
        subject_id=source_id,
        opportunity_id=opportunity_id,
        subject_version=version,
    )
    _log.info(
        "intake.source_added",
        extra={
            "opportunity_id": str(opportunity_id),
            "source_id": str(source_id),
            "version": version,
            "kind": source_kind,
            "size_bytes": blob.size,
            "actor_id": actor.actor.id,
        },
    )
    record = await repository.get(uow, source_id)
    if record is None:
        raise RuntimeError("added source not found")
    (source,) = await _sources(uow, [record])
    return source
