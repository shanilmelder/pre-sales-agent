"""Knowledge Source commands and queries (Story 3.2).

Writes follow the AD-3 path in the caller's Unit of Work: `identity.authorize` (the
`knowledge.source.*` actions: platform administrators, or the Source's owner for an existing
Source), field and tag rules, the `If-Match` check (428 without, 412 when stale), the write,
then trace with no Opportunity. Reads need only a role.

- `register_source`: a file, a title, product, product version and at least one active
  Integration Type tag. The registrant owns it; an administrator may name another user with a
  role. Stored by SHA-256, version 1, last reviewed today, parse job queued.
- `add_version`: the next version from a new file; earlier versions stay readable.
- `edit_source`: title, product, owner (administrators only) and the tag set (retagging).
- `mark_reviewed`: last reviewed becomes today, which clears `stale`.
- `retire_source`: with a reason; retiring a retired Source is a 200 no-op.
- `retry_parse`: queue a failed latest version's parse again.

`stale` is derived on every read from the last-reviewed date, today and the configured
months; it is never stored. A rejected upload stores nothing: the type is checked from the
file name before any byte is read, the size while it streams, the content before the blob is
stored. Tags are validated through `validate_catalogue_ref`, so a retired entry is a 422.
Logs and trace payloads hold ids, counts and sizes only.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable
from datetime import UTC, date, datetime
from typing import BinaryIO, Protocol
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.knowledge.adapters import source_repository as repo
from app.modules.knowledge.adapters.source_repository import SourceRecord
from app.modules.knowledge.application.catalogue import list_catalogue, validate_catalogue_ref
from app.modules.knowledge.application.jobs import enqueue_parse
from app.modules.knowledge.application.source_models import (
    DownloadLink,
    IntegrationTypeTag,
    KnowledgeSource,
    KnowledgeSourceList,
    KnowledgeSourceParse,
    KnowledgeSourceVersion,
    KnowledgeSourceVersionList,
    KnowledgeUserRef,
    RetireSource,
    SourceChanges,
    SourceText,
)
from app.modules.knowledge.domain import sources as rules
from app.modules.knowledge.domain.catalogue import Kind
from app.platform import downloads, files, trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    FileContentMismatchError,
    FileEmptyError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    ForbiddenError,
    NotFoundError,
    ParseNotFailedError,
    RowVersionMismatchError,
    SourceRetiredError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.multipart import BodyTooLargeError, MultipartError
from app.platform.parsing.rules import ParseErrorCode, ParseStatus
from app.platform.storage import BlobStore, BlobTooLargeError, StoredBlob
from app.platform.trace.catalogue import (
    KnowledgeSourceParseRetried,
    KnowledgeSourceRegistered,
    KnowledgeSourceRetagged,
    KnowledgeSourceRetired,
    KnowledgeSourceReviewed,
    KnowledgeSourceVersionAdded,
)
from app.platform.uow import UnitOfWork
from app.platform.upload_validation import (
    EMPTY_MESSAGE,
    InvalidFilenameError,
    clean_filename,
    content_matches,
    extension,
    mismatch_message,
    too_large_message,
    type_rejected_message,
)

MULTIPART_OVERHEAD = 64 * 1024
MAX_ROW_VERSION = 2**31 - 1
MISSING_FILE_DETAIL = "Invalid fields: body.file"
NOT_FOUND_DETAIL = "No Knowledge Source with this id."
VERSION_NOT_FOUND_DETAIL = "No such version of this Knowledge Source."
RETIRED_DETAIL = "A retired Knowledge Source can't be changed."
NOT_FAILED_DETAIL = "Only a Source whose parse failed can be retried."
NO_TEXT_DETAIL = "The extracted text of this version isn't available."
UNKNOWN_USER = "Unknown user"
OWNER_INVALID_DETAIL = "The owner must be a user with a role."
_log = get_logger(__name__)


class IncomingFile(Protocol):
    """An uploaded file read as it arrives (`app.platform.multipart.MultipartFile`)."""

    async def filename(self) -> str: ...

    def chunks(self) -> AsyncIterator[bytes]: ...


def max_body_bytes(max_bytes: int) -> int:
    """The largest request body an upload of at most `max_bytes` may need."""
    return max_bytes + MULTIPART_OVERHEAD


def today_utc() -> date:
    return datetime.now(UTC).date()


# --- helpers --------------------------------------------------------------------------------


def _invalid[T](value: str, check: Callable[[str], T]) -> T:
    """Run a field rule; a rule's `ValueError` is a 422 whose detail is the sentence to show."""
    try:
        return check(value)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None


def _require_role(actor: Principal) -> None:
    if not actor.roles:
        raise ForbiddenError("You are not allowed to perform this action.")


def _user_id(actor: Principal) -> UUID:
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants these actions to users only
        raise ForbiddenError("Only people can change Knowledge Sources.")
    return user_id


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Knowledge Source was changed by someone else since you opened it. "
        "Reload and try again."
    )


def _expected(if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        # The stored version can't be this large, or bumping it would overflow int4.
        raise _stale()
    return expected


def _resource(record: SourceRecord) -> Resource:
    return Resource(type=identity.KNOWLEDGE_SOURCE_RESOURCE, id=record.id, owner_id=record.owner_id)


async def _load(uow: UnitOfWork, source_id: UUID, *, version: int | None = None) -> SourceRecord:
    record = await repo.get_source(uow, source_id, version=version)
    if record is None:
        if version is not None and await repo.get_source(uow, source_id) is not None:
            raise NotFoundError(VERSION_NOT_FOUND_DETAIL)
        raise NotFoundError(NOT_FOUND_DETAIL)
    return record


async def _writable(
    uow: UnitOfWork, actor: Principal, action: Action, source_id: UUID
) -> SourceRecord:
    """The Source, if the actor may do `action` to it: 404, then 403, then (a retired
    Source) 409."""
    record = await _load(uow, source_id)
    identity.authorize(actor, action, _resource(record))
    if record.status == rules.Status.RETIRED:
        raise SourceRetiredError(RETIRED_DETAIL)
    return record


def _ref(user_id: UUID, names: dict[UUID, str]) -> KnowledgeUserRef:
    return KnowledgeUserRef(id=str(user_id), name=names.get(user_id, UNKNOWN_USER))


def _parse_view(status: str, error_code: str | None) -> KnowledgeSourceParse:
    return KnowledgeSourceParse(
        status=ParseStatus(status),
        error_code=None if error_code is None else ParseErrorCode(error_code),
    )


async def _views(
    uow: UnitOfWork,
    records: Iterable[SourceRecord],
    *,
    stale_months: int,
    today: date,
) -> list[KnowledgeSource]:
    records = list(records)
    names = await identity.user_names(
        uow, {r.owner_id for r in records} | {r.uploaded_by for r in records}
    )
    tags = await repo.tags_for(uow, [r.id for r in records])
    # Every Integration Type, retired ones too: existing tags keep resolving.
    entries = {
        UUID(e.id): e
        for e in await list_catalogue(uow, Kind.INTEGRATION_TYPE, include_retired=True)
    }
    views: list[KnowledgeSource] = []
    for r in records:
        tag_views = [
            IntegrationTypeTag(
                id=str(i), code=entries[i].code, name=entries[i].name, retired=entries[i].retired
            )
            for i in tags.get(r.id, [])
            if i in entries
        ]
        tag_views.sort(key=lambda t: t.name.casefold())
        views.append(
            KnowledgeSource(
                id=str(r.id),
                title=r.title,
                product=r.product,
                owner=_ref(r.owner_id, names),
                integration_types=tag_views,
                status=rules.Status(r.status).value,
                retired=r.status == rules.Status.RETIRED,
                retired_reason=r.retired_reason,
                last_reviewed_on=r.last_reviewed_on,
                stale=rules.is_stale(r.last_reviewed_on, today, stale_months),
                version=r.version,
                version_count=r.version_count,
                product_version=r.product_version,
                filename=r.filename,
                size_bytes=r.size_bytes,
                uploaded_by=_ref(r.uploaded_by, names),
                uploaded_at=r.uploaded_at,
                parse=_parse_view(r.parse_status, r.parse_error_code),
                row_version=r.row_version,
                created_at=r.created_at,
            )
        )
    return views


async def _view(
    uow: UnitOfWork, source_id: UUID, *, stale_months: int, today: date
) -> KnowledgeSource:
    (view,) = await _views(
        uow, [await _load(uow, source_id)], stale_months=stale_months, today=today
    )
    return view


async def _tag_ids(uow: UnitOfWork, raw: list[str]) -> list[UUID]:
    """The Integration Type ids to tag with: distinct, at least one, each an active
    Integration Type (`validate_catalogue_ref`). 422 otherwise."""
    try:
        ids = rules.distinct_tags([_uuid(r) for r in raw])
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    kinds = await repo.entry_kinds(uow, ids)
    for entry_id in ids:
        if kinds.get(entry_id) != Kind.INTEGRATION_TYPE.value or not await validate_catalogue_ref(
            uow, entry_id
        ):
            raise UnprocessableError(rules.RETIRED_TAG_MESSAGE)
    return ids


def _uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError:
        raise ValueError(rules.RETIRED_TAG_MESSAGE) from None


async def _valid_owner(uow: UnitOfWork, owner_id: UUID) -> UUID:
    if owner_id not in await identity.user_names(uow, {owner_id}, with_roles_only=True):
        raise UnprocessableError(OWNER_INVALID_DETAIL)
    return owner_id


# --- queries --------------------------------------------------------------------------------


async def list_sources(
    uow: UnitOfWork,
    actor: Principal,
    *,
    product: str | None,
    integration_type_id: UUID | None,
    owner_id: UUID | None,
    stale: bool | None,
    include_retired: bool,
    stale_months: int,
    today: date | None = None,
) -> KnowledgeSourceList:
    """Sources at their latest version, longest-unreviewed first. Any user with a role."""
    _require_role(actor)
    now = today or today_utc()
    records = await repo.list_sources(
        uow,
        product=product,
        integration_type_id=integration_type_id,
        owner_id=owner_id,
        stale_before=rules.stale_cutoff(now, stale_months),
        stale=stale,
        include_retired=include_retired,
    )
    return KnowledgeSourceList(
        items=await _views(uow, records, stale_months=stale_months, today=now),
        stale_months=stale_months,
    )


async def read_source(
    uow: UnitOfWork,
    actor: Principal,
    source_id: UUID,
    *,
    stale_months: int,
    today: date | None = None,
) -> KnowledgeSource:
    _require_role(actor)
    return await _view(uow, source_id, stale_months=stale_months, today=today or today_utc())


async def read_versions(
    uow: UnitOfWork, actor: Principal, source_id: UUID
) -> KnowledgeSourceVersionList:
    """Every version, newest first, each with its parse state."""
    _require_role(actor)
    await _load(uow, source_id)
    versions = await repo.list_versions(uow, source_id)
    names = await identity.user_names(uow, {v.uploaded_by for v in versions})
    return KnowledgeSourceVersionList(
        items=[
            KnowledgeSourceVersion(
                version=v.version,
                product_version=v.product_version,
                filename=v.filename,
                size_bytes=v.size_bytes,
                uploaded_by=_ref(v.uploaded_by, names),
                uploaded_at=v.uploaded_at,
                parse=_parse_view(v.parse_status, v.parse_error_code),
                char_count=v.char_count,
            )
            for v in versions
        ]
    )


async def read_text(
    uow: UnitOfWork, actor: Principal, source_id: UUID, version: int, *, store: BlobStore
) -> SourceText:
    """The stored extracted text of a parsed version (404 until it is parsed)."""
    _require_role(actor)
    await _load(uow, source_id, version=version)
    state = await repo.parse_state(uow, source_id, version)
    if state is None or state.status != ParseStatus.PARSED or state.text_sha256 is None:
        raise NotFoundError(NO_TEXT_DETAIL)
    path = store.path_for(state.text_sha256)
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except FileNotFoundError:
        raise NotFoundError(NO_TEXT_DETAIL) from None
    text = data.decode("utf-8")
    return SourceText(version=version, char_count=len(text), text=text)


async def download_link(
    uow: UnitOfWork,
    actor: Principal,
    source_id: UUID,
    version: int,
    *,
    signing_key: str,
    ttl_s: int,
) -> DownloadLink:
    """A short-lived signed link to the version's original file, unchanged."""
    _require_role(actor)
    record = await _load(uow, source_id, version=version)
    token, expires_at = downloads.sign(
        signing_key, sha256=record.file_sha256, filename=record.filename, ttl_s=ttl_s
    )
    return DownloadLink(url=downloads.link_for(token), expires_at=expires_at)


async def search_owners(uow: UnitOfWork, actor: Principal, q: str) -> identity.UserSearchResult:
    """Users an administrator may name as a Source's owner."""
    return await identity.search_owner_candidates(uow, actor, q)


# --- uploads ----------------------------------------------------------------------------------


async def _store_upload(
    incoming: IncomingFile,
    *,
    store: BlobStore,
    max_bytes: int,
    content_length: int | None,
) -> tuple[StoredBlob, str]:
    """Validate and store the uploaded file: the blob and its cleaned file name."""
    if content_length is not None and content_length > max_body_bytes(max_bytes):
        raise FileTooLargeError(too_large_message(max_bytes))
    try:
        filename = clean_filename(await incoming.filename())
        if not rules.allowed(filename):
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
    return blob, filename


async def _attach_version(
    uow: UnitOfWork,
    source_id: UUID,
    *,
    blob: StoredBlob,
    filename: str,
    product_version: str,
    uploaded_by: UUID,
) -> int:
    """The next version row (with its `queued` parse row and job) for a stored blob."""
    version = await repo.next_version(uow, source_id)
    await files.add_reference(uow, blob.sha256, blob.size)
    await repo.insert_version(
        uow,
        source_id=source_id,
        version=version,
        product_version=product_version,
        file_sha256=blob.sha256,
        filename=filename,
        size_bytes=blob.size,
        uploaded_by=uploaded_by,
    )
    await enqueue_parse(uow, source_id=source_id, version=version)
    return version


async def register_source(
    uow: UnitOfWork,
    actor: Principal,
    incoming: IncomingFile,
    *,
    title: str,
    product: str,
    product_version: str,
    integration_type_ids: list[str],
    owner_id: UUID | None,
    store: BlobStore,
    max_bytes: int,
    content_length: int | None,
    stale_months: int,
    today: date | None = None,
) -> KnowledgeSource:
    """Register a Knowledge Source with its first file. Fields and tags are checked before
    any byte of the file is read."""
    identity.authorize(actor, Action.KNOWLEDGE_SOURCE_REGISTER)
    user_id = _user_id(actor)
    owner = user_id
    if owner_id is not None and owner_id != user_id:
        identity.authorize(actor, Action.KNOWLEDGE_SOURCE_RETAG)  # administrators only
        owner = await _valid_owner(uow, owner_id)
    clean_title = _invalid(title, rules.source_title)
    clean_product = _invalid(product, rules.source_product)
    clean_version = _invalid(product_version, rules.product_version)
    tag_ids = await _tag_ids(uow, integration_type_ids)
    blob, filename = await _store_upload(
        incoming, store=store, max_bytes=max_bytes, content_length=content_length
    )

    now = today or today_utc()
    source_id = new_id()
    await repo.insert_source(
        uow,
        source_id=source_id,
        title=clean_title,
        product=clean_product,
        owner_id=owner,
        last_reviewed_on=now,
        created_by=user_id,
    )
    await repo.set_tags(uow, source_id, tag_ids)
    version = await _attach_version(
        uow,
        source_id,
        blob=blob,
        filename=filename,
        product_version=clean_version,
        uploaded_by=user_id,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeSourceRegistered(
            version=version,
            owner_id=str(owner),
            tag_count=len(tag_ids),
            size_bytes=blob.size,
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=source_id,
        subject_version=version,
    )
    _log.info(
        "knowledge.source_registered",
        extra={
            "source_id": str(source_id),
            "version": version,
            "size_bytes": blob.size,
            "tag_count": len(tag_ids),
            "actor_id": actor.actor.id,
        },
    )
    return await _view(uow, source_id, stale_months=stale_months, today=now)


async def add_version(
    uow: UnitOfWork,
    actor: Principal,
    source_id: UUID,
    incoming: IncomingFile,
    *,
    product_version: str,
    if_match: str | None,
    store: BlobStore,
    max_bytes: int,
    content_length: int | None,
    stale_months: int,
    today: date | None = None,
) -> KnowledgeSource:
    """Upload the next version of a Source. Earlier versions stay readable."""
    record = await _writable(uow, actor, Action.KNOWLEDGE_SOURCE_ADD_VERSION, source_id)
    user_id = _user_id(actor)
    clean_version = _invalid(product_version, rules.product_version)
    expected = _expected(if_match)
    if record.row_version != expected:
        raise _stale()
    blob, filename = await _store_upload(
        incoming, store=store, max_bytes=max_bytes, content_length=content_length
    )

    if await repo.bump(uow, source_id, expected_row_version=expected) is None:
        raise _stale()
    version = await _attach_version(
        uow,
        source_id,
        blob=blob,
        filename=filename,
        product_version=clean_version,
        uploaded_by=user_id,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeSourceVersionAdded(
            from_version=record.version, to_version=version, size_bytes=blob.size
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=source_id,
        subject_version=version,
    )
    _log.info(
        "knowledge.source_version_added",
        extra={
            "source_id": str(source_id),
            "version": version,
            "size_bytes": blob.size,
            "actor_id": actor.actor.id,
        },
    )
    return await _view(uow, source_id, stale_months=stale_months, today=today or today_utc())


# --- changes ----------------------------------------------------------------------------------


async def edit_source(
    uow: UnitOfWork,
    actor: Principal,
    source_id: UUID,
    changes: SourceChanges,
    if_match: str | None,
    *,
    stale_months: int,
    today: date | None = None,
) -> KnowledgeSource:
    """Change the title, product, owner (administrators only) and/or tag set. Nothing
    changed writes nothing (a stale `If-Match` is still 412)."""
    record = await _writable(uow, actor, Action.KNOWLEDGE_SOURCE_RETAG, source_id)
    title = None if changes.title is None else _invalid(changes.title, rules.source_title)
    product = None if changes.product is None else _invalid(changes.product, rules.source_product)
    new_owner: UUID | None = None
    if changes.owner_id is not None:
        try:
            wanted_owner = UUID(changes.owner_id)
        except ValueError:
            raise UnprocessableError(OWNER_INVALID_DETAIL) from None
        if wanted_owner != record.owner_id:
            # Only a platform administrator hands a Source to someone else.
            identity.authorize(actor, Action.KNOWLEDGE_SOURCE_RETAG)
            new_owner = await _valid_owner(uow, wanted_owner)
    expected = _expected(if_match)
    if record.row_version != expected:
        raise _stale()
    tag_ids = (
        None
        if changes.integration_type_ids is None
        else await _tag_ids_for_edit(uow, source_id, changes.integration_type_ids)
    )

    title_changed = title is not None and title != record.title
    product_changed = product is not None and product != record.product
    current_tags = set((await repo.tags_for(uow, [source_id])).get(source_id, []))
    tags_changed = tag_ids is not None and set(tag_ids) != current_tags
    if not (title_changed or product_changed or new_owner is not None or tags_changed):
        return await _view(uow, source_id, stale_months=stale_months, today=today or today_utc())

    if (
        await repo.bump(
            uow,
            source_id,
            expected_row_version=expected,
            title=title if title_changed else None,
            product=product if product_changed else None,
            owner_id=new_owner,
        )
        is None
    ):
        raise _stale()
    added: list[UUID] = []
    removed: list[UUID] = []
    if tag_ids is not None and tags_changed:
        added, removed = await repo.set_tags(uow, source_id, tag_ids)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeSourceRetagged(
            tag_ids_added=[str(i) for i in added],
            tag_ids_removed=[str(i) for i in removed],
            product_changed=product_changed,
            title_changed=title_changed,
            owner_changed=new_owner is not None,
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=source_id,
        subject_version=record.version,
    )
    _log.info(
        "knowledge.source_retagged",
        extra={
            "source_id": str(source_id),
            "added": len(added),
            "removed": len(removed),
            "actor_id": actor.actor.id,
        },
    )
    return await _view(uow, source_id, stale_months=stale_months, today=today or today_utc())


async def _tag_ids_for_edit(uow: UnitOfWork, source_id: UUID, raw: list[str]) -> list[UUID]:
    """The new tag set. A tag the Source already has stays even if it was retired since
    (existing references keep resolving); a newly added one must be active."""
    try:
        ids = rules.distinct_tags([_uuid(r) for r in raw])
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None
    existing = set((await repo.tags_for(uow, [source_id])).get(source_id, []))
    kinds = await repo.entry_kinds(uow, ids)
    for entry_id in ids:
        if kinds.get(entry_id) != Kind.INTEGRATION_TYPE.value:
            raise UnprocessableError(rules.RETIRED_TAG_MESSAGE)
        if entry_id not in existing and not await validate_catalogue_ref(uow, entry_id):
            raise UnprocessableError(rules.RETIRED_TAG_MESSAGE)
    return ids


async def mark_reviewed(
    uow: UnitOfWork,
    actor: Principal,
    source_id: UUID,
    if_match: str | None,
    *,
    stale_months: int,
    today: date | None = None,
) -> KnowledgeSource:
    """Set the Source's last-reviewed date to today, which clears its stale flag."""
    record = await _writable(uow, actor, Action.KNOWLEDGE_SOURCE_REVIEW, source_id)
    now = today or today_utc()
    expected = _expected(if_match)
    if record.row_version != expected:
        raise _stale()
    was_stale = rules.is_stale(record.last_reviewed_on, now, stale_months)
    if await repo.bump(uow, source_id, expected_row_version=expected, last_reviewed_on=now) is None:
        raise _stale()
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeSourceReviewed(was_stale=was_stale),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=source_id,
        subject_version=record.version,
    )
    _log.info(
        "knowledge.source_reviewed",
        extra={"source_id": str(source_id), "was_stale": was_stale, "actor_id": actor.actor.id},
    )
    return await _view(uow, source_id, stale_months=stale_months, today=now)


async def retire_source(
    uow: UnitOfWork,
    actor: Principal,
    source_id: UUID,
    request: RetireSource,
    if_match: str | None,
    *,
    stale_months: int,
    today: date | None = None,
) -> KnowledgeSource:
    """Retire the Source with a reason. Its versions and text stay readable."""
    record = await _load(uow, source_id)
    identity.authorize(actor, Action.KNOWLEDGE_SOURCE_RETIRE, _resource(record))
    reason = _invalid(request.reason, rules.retire_reason)
    expected = _expected(if_match)
    if record.row_version != expected:
        raise _stale()
    now = today or today_utc()
    if record.status == rules.Status.RETIRED:
        return await _view(uow, source_id, stale_months=stale_months, today=now)
    if (
        await repo.bump(uow, source_id, expected_row_version=expected, retire_with_reason=reason)
        is None
    ):
        raise _stale()
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeSourceRetired(version=record.version),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=source_id,
        subject_version=record.version,
    )
    _log.info(
        "knowledge.source_retired",
        extra={"source_id": str(source_id), "actor_id": actor.actor.id},
    )
    return await _view(uow, source_id, stale_months=stale_months, today=now)


async def retry_parse(
    uow: UnitOfWork,
    actor: Principal,
    source_id: UUID,
    *,
    stale_months: int,
    today: date | None = None,
) -> KnowledgeSource:
    """Set the Source's failed latest version back to `queued` and enqueue its parse.
    409 `parse_not_failed` unless the latest version's parse is `failed`."""
    record = await _writable(uow, actor, Action.KNOWLEDGE_SOURCE_RETRY_PARSE, source_id)
    state = await repo.parse_state(uow, source_id, record.version, for_update=True)
    if state is None or state.status != ParseStatus.FAILED or state.error_code is None:
        raise ParseNotFailedError(NOT_FAILED_DETAIL)
    await repo.update_parse(
        uow,
        source_id,
        record.version,
        from_statuses=(ParseStatus.FAILED.value,),
        status=ParseStatus.QUEUED.value,
    )
    await enqueue_parse(uow, source_id=source_id, version=record.version)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeSourceParseRetried(version=record.version, error_code=state.error_code),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=source_id,
        subject_version=record.version,
    )
    _log.info(
        "knowledge.source_parse_retried",
        extra={
            "source_id": str(source_id),
            "version": record.version,
            "error_code": state.error_code,
            "actor_id": actor.actor.id,
        },
    )
    return await _view(uow, source_id, stale_months=stale_months, today=today or today_utc())
