"""The catalogue's commands and queries (Story 3.1).

Writes follow the AD-3 path: `identity.authorize` (the `knowledge.catalogue_entry.*` actions,
platform administrators only), validate, `If-Match` check (428 without, 412 when stale), write,
then trace with no Opportunity. Each write that can add to the active set (create, rename,
reactivate; retiring only shrinks it) takes a per-kind lock first, so the duplicate rule
(a code or name equal, ignoring case, to an active entry of the same kind: 409
`catalogue_duplicate`) can't be raced.

- `create_entry`: version 1.
- `edit_entry`: a changed name or definition saves a new version; unchanged: 200, nothing
  written (a stale `If-Match` is still 412).
- `retire_entry`: needs a reason; retiring a retired entry is a 200 no-op.
- `reactivate_entry`: re-runs the duplicate rule; reactivating an active entry is a no-op.

Reads (`list_entries`, `read_entry`, `read_versions`) need only a role. The public queries
`get_catalogue_entry` etc. are for other modules and don't authorize.

Trace and logs carry ids, kinds and version numbers only, never the text.
"""

from collections.abc import Callable
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.knowledge.adapters import repository as repo
from app.modules.knowledge.adapters.repository import EntryRecord
from app.modules.knowledge.application.models import (
    CatalogueEntry,
    CatalogueList,
    CatalogueVersion,
    CatalogueVersionList,
    EntryChanges,
    NewEntry,
    RetireRequest,
)
from app.modules.knowledge.domain import catalogue as rules
from app.modules.knowledge.domain.catalogue import ActiveEntry, Kind, Status
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    CatalogueDuplicateError,
    ForbiddenError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    KnowledgeCatalogueEntryCreated,
    KnowledgeCatalogueEntryReactivated,
    KnowledgeCatalogueEntryRetired,
    KnowledgeCatalogueEntryUpdated,
)
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No catalogue entry with this id."
UNKNOWN_USER = "Unknown user"
_log = get_logger(__name__)


def view(record: EntryRecord) -> CatalogueEntry:
    return CatalogueEntry(
        id=str(record.id),
        kind=Kind(record.kind),
        code=record.code,
        name=record.name,
        definition=record.definition,
        version=record.version,
        current_version=record.current_version,
        status=Status(record.status),
        retired=record.status == Status.RETIRED,
        retired_reason=record.retired_reason,
        row_version=record.row_version,
        created_at=record.created_at,
    )


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The catalogue entry was changed by someone else since you opened it. Reload and try again."
    )


def _expected(if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        # The stored version can't be this large, or bumping it would overflow int4.
        raise _stale()
    return expected


def _require_role(actor: Principal) -> None:
    if not actor.roles:
        raise ForbiddenError("You are not allowed to perform this action.")


def _writer(actor: Principal, action: Action) -> UUID:
    identity.authorize(actor, action)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants these actions to users only
        raise ForbiddenError("Only people can change the catalogue.")
    return user_id


def _invalid[T](value: str, check: Callable[[str], T]) -> T:
    """Run a field rule; a rule's `ValueError` is a 422 whose detail is the sentence to show."""
    try:
        return check(value)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None


async def _load(uow: UnitOfWork, entry_id: UUID) -> EntryRecord:
    record = await repo.get_entry(uow, entry_id)
    if record is None:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return record


async def _check_duplicate(
    uow: UnitOfWork,
    kind: Kind,
    *,
    code: str | None,
    name: str | None,
    ignore: UUID | None = None,
) -> None:
    active = [ActiveEntry(i, c, n) for i, c, n in await repo.active_entries(uow, kind.value)]
    clash = rules.duplicate_field(active, code=code, name=name, ignore=ignore)
    if clash is not None:
        raise CatalogueDuplicateError(rules.duplicate_message(kind, clash))


# --- reads --------------------------------------------------------------------------------


async def list_entries(
    uow: UnitOfWork, actor: Principal, *, kind: Kind | None, include_retired: bool
) -> CatalogueList:
    """Entries at their current version (active only unless `include_retired`), by kind
    then name. Any user with a role."""
    _require_role(actor)
    records = await repo.list_entries(
        uow, kind=None if kind is None else kind.value, include_retired=include_retired
    )
    return CatalogueList(items=[view(r) for r in records])


async def read_entry(
    uow: UnitOfWork, actor: Principal, entry_id: UUID, version: int | None
) -> CatalogueEntry:
    """One entry, retired or not, at `version` (the current one when None). 404 when the
    entry or the version doesn't exist."""
    _require_role(actor)
    record = await repo.get_entry(uow, entry_id, version=version)
    if record is None:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return view(record)


async def read_versions(uow: UnitOfWork, actor: Principal, entry_id: UUID) -> CatalogueVersionList:
    """The entry's versions, newest first, with who saved each."""
    _require_role(actor)
    await _load(uow, entry_id)
    versions = await repo.list_versions(uow, entry_id)
    names = await identity.user_names(uow, {v.changed_by for v in versions})
    return CatalogueVersionList(
        items=[
            CatalogueVersion(
                version=v.version,
                name=v.name,
                definition=v.definition,
                changed_by_id=str(v.changed_by),
                changed_by_name=names.get(v.changed_by, UNKNOWN_USER),
                changed_at=v.changed_at,
            )
            for v in versions
        ]
    )


# --- writes -------------------------------------------------------------------------------


async def create_entry(uow: UnitOfWork, actor: Principal, new: NewEntry) -> CatalogueEntry:
    user_id = _writer(actor, Action.CATALOGUE_ENTRY_CREATE)
    kind = Kind(new.kind)
    code = _invalid(new.code, rules.entry_code)
    name = _invalid(new.name, rules.entry_name)
    definition = _invalid(new.definition, rules.entry_definition)
    await repo.lock_kind(uow, kind.value)
    await _check_duplicate(uow, kind, code=code, name=name)
    entry_id = new_id()
    await repo.insert_entry(
        uow,
        entry_id=entry_id,
        kind=kind.value,
        code=code,
        name=name,
        definition=definition,
        user_id=user_id,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeCatalogueEntryCreated(kind=kind.value, version=1),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=entry_id,
        subject_version=1,
    )
    _log.info(
        "knowledge.catalogue_entry_created",
        extra={"entry_id": str(entry_id), "kind": kind.value, "actor_id": str(user_id)},
    )
    return view(await _load(uow, entry_id))


async def edit_entry(
    uow: UnitOfWork,
    actor: Principal,
    entry_id: UUID,
    changes: EntryChanges,
    if_match: str | None,
) -> CatalogueEntry:
    """Change the name and/or definition. `if_match` is the raw `If-Match` header."""
    user_id = _writer(actor, Action.CATALOGUE_ENTRY_EDIT)
    name = None if changes.name is None else _invalid(changes.name, rules.entry_name)
    definition = (
        None if changes.definition is None else _invalid(changes.definition, rules.entry_definition)
    )
    expected = _expected(if_match)
    record = await _load(uow, entry_id)
    kind = Kind(record.kind)
    await repo.lock_kind(uow, kind.value)
    record = await _load(uow, entry_id)
    if record.row_version != expected:
        raise _stale()
    new_name = record.name if name is None else name
    new_definition = record.definition if definition is None else definition
    if new_name == record.name and new_definition == record.definition:
        return view(record)
    if new_name != record.name:
        await _check_duplicate(uow, kind, code=None, name=new_name, ignore=entry_id)
    if await repo.bump(uow, entry_id, expected_row_version=expected) is None:
        raise _stale()
    to_version = record.current_version + 1
    await repo.insert_version(
        uow,
        entry_id=entry_id,
        version=to_version,
        name=new_name,
        definition=new_definition,
        user_id=user_id,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeCatalogueEntryUpdated(
            kind=kind.value, from_version=record.current_version, to_version=to_version
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=entry_id,
        subject_version=to_version,
    )
    _log.info(
        "knowledge.catalogue_entry_updated",
        extra={
            "entry_id": str(entry_id),
            "actor_id": str(user_id),
            "from_version": record.current_version,
            "to_version": to_version,
        },
    )
    return view(await _load(uow, entry_id))


async def retire_entry(
    uow: UnitOfWork,
    actor: Principal,
    entry_id: UUID,
    request: RetireRequest,
    if_match: str | None,
) -> CatalogueEntry:
    user_id = _writer(actor, Action.CATALOGUE_ENTRY_RETIRE)
    reason = _invalid(request.reason, rules.retire_reason)
    expected = _expected(if_match)
    record = await _load(uow, entry_id)
    if record.row_version != expected:
        raise _stale()
    if record.status == Status.RETIRED:
        return view(record)
    if (
        await repo.bump(
            uow,
            entry_id,
            expected_row_version=expected,
            status=Status.RETIRED.value,
            retired_reason=reason,
        )
        is None
    ):
        raise _stale()
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeCatalogueEntryRetired(kind=record.kind, version=record.current_version),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=entry_id,
        subject_version=record.current_version,
    )
    _log.info(
        "knowledge.catalogue_entry_retired",
        extra={"entry_id": str(entry_id), "actor_id": str(user_id)},
    )
    return view(await _load(uow, entry_id))


async def reactivate_entry(
    uow: UnitOfWork, actor: Principal, entry_id: UUID, if_match: str | None
) -> CatalogueEntry:
    user_id = _writer(actor, Action.CATALOGUE_ENTRY_REACTIVATE)
    expected = _expected(if_match)
    record = await _load(uow, entry_id)
    kind = Kind(record.kind)
    await repo.lock_kind(uow, kind.value)
    record = await _load(uow, entry_id)
    if record.row_version != expected:
        raise _stale()
    if record.status == Status.ACTIVE:
        return view(record)
    await _check_duplicate(uow, kind, code=record.code, name=record.name, ignore=entry_id)
    if (
        await repo.bump(
            uow,
            entry_id,
            expected_row_version=expected,
            status=Status.ACTIVE.value,
            clear_reason=True,
        )
        is None
    ):
        raise _stale()
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeCatalogueEntryReactivated(kind=kind.value, version=record.current_version),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=entry_id,
        subject_version=record.current_version,
    )
    _log.info(
        "knowledge.catalogue_entry_reactivated",
        extra={"entry_id": str(entry_id), "actor_id": str(user_id)},
    )
    return view(await _load(uow, entry_id))


# --- for other modules (no authorization: callers decide what they may show) ----------------


async def get_catalogue_entry(
    uow: UnitOfWork, entry_id: UUID, version: int | None = None
) -> CatalogueEntry | None:
    """The entry at `version` (the current one when None), or None if there is none. A
    retired entry still resolves, with `retired` true."""
    record = await repo.get_entry(uow, entry_id, version=version)
    return None if record is None else view(record)


async def list_catalogue(
    uow: UnitOfWork, kind: Kind | None = None, include_retired: bool = False
) -> list[CatalogueEntry]:
    records = await repo.list_entries(
        uow, kind=None if kind is None else kind.value, include_retired=include_retired
    )
    return [view(r) for r in records]


async def validate_catalogue_ref(uow: UnitOfWork, entry_id: UUID) -> bool:
    """True only for an existing, active entry: the check for choosing an entry for a new
    tag or line."""
    record = await repo.get_entry(uow, entry_id)
    return record is not None and record.status == Status.ACTIVE
