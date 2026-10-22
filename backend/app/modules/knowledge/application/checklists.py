"""Checklist commands and queries (Story 3.4).

Writes follow the AD-3 path in the caller's Unit of Work: `identity.authorize` (the
`knowledge.checklist.*` actions: engineering, PM and security reviewers and platform
administrators, on every Checklist), field rules, the `If-Match` check (428 without, 412 when
stale; nothing is overwritten), then the write. Publish and Retire also append a trace event
with no Opportunity (`knowledge.checklist.published` / `.retired`); creating a Checklist and
starting or saving a draft are not traced. Reads need only a role.

- `create_checklist`: a name and a domain; it starts with an empty draft and no version.
- `open_draft`: start a draft from the latest published version, items keeping their ids
  (409 when a draft already exists).
- `save_draft`: replace the whole draft (each blur in the editor). A new item gets a UUIDv7.
- `publish_checklist`: the draft becomes the next immutable version with its items; the
  header's published name, domain and scope follow it, and the draft is cleared. Until then
  the earlier version stays in use. Needs a scope entry and an item (422 otherwise).
- `retire_checklist`: with a reason; final in this story. The draft is discarded and the
  versions stay readable.

`find_applicable_checklists` (for Gap detection) returns the latest published version of
every active Checklist whose published scope shares a product, the industry or an
Integration Type with what is asked. Trace payloads and logs hold ids and counts only.
"""

from collections.abc import Callable, Iterable
from typing import Any
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.knowledge.adapters import checklist_repository as repo
from app.modules.knowledge.adapters.checklist_repository import ChecklistRecord, ItemRecord
from app.modules.knowledge.adapters.source_repository import entry_kinds
from app.modules.knowledge.application.catalogue import list_catalogue, validate_catalogue_ref
from app.modules.knowledge.application.checklist_models import (
    AffectedArea,
    ApplicableChecklist,
    ApplicableItem,
    Checklist,
    ChecklistDraft,
    ChecklistItem,
    ChecklistList,
    ChecklistVersion,
    ChecklistVersionList,
    ChecklistVersionSummary,
    DraftInput,
    NewChecklist,
    RetireChecklist,
)
from app.modules.knowledge.application.models import CatalogueEntry
from app.modules.knowledge.application.source_models import IntegrationTypeTag, KnowledgeUserRef
from app.modules.knowledge.domain import checklists as rules
from app.modules.knowledge.domain.catalogue import Kind
from app.modules.knowledge.domain.checklists import Domain, Impact, ItemKind, Status
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ChecklistDraftExistsError,
    ChecklistNoDraftError,
    ChecklistRetiredError,
    ForbiddenError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import KnowledgeChecklistPublished, KnowledgeChecklistRetired
from app.platform.uow import UnitOfWork

MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Checklist with this id."
VERSION_NOT_FOUND_DETAIL = "No such version of this Checklist."
RETIRED_DETAIL = "A retired Checklist can't be changed."
DRAFT_EXISTS_DETAIL = "This Checklist already has a draft."
NO_DRAFT_DETAIL = "This Checklist has no draft. Start one with Edit."
UNKNOWN_USER = "Unknown user"
_log = get_logger(__name__)

type Entries = dict[UUID, CatalogueEntry]


# --- helpers --------------------------------------------------------------------------------


def _require_role(actor: Principal) -> None:
    if not actor.roles:
        raise ForbiddenError("You are not allowed to perform this action.")


def _writer(actor: Principal, action: Action) -> UUID:
    identity.authorize(actor, action)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants these actions to users only
        raise ForbiddenError("Only people can change Checklists.")
    return user_id


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Checklist was changed by someone else since you opened it. Reload and try again."
    )


def _expected(if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        # The stored version can't be this large, or bumping it would overflow int4.
        raise _stale()
    return expected


def _invalid[T, V](value: V, check: Callable[[V], T]) -> T:
    """Run a field rule; a rule's `ValueError` is a 422 whose detail is the sentence to show."""
    try:
        return check(value)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from None


async def _load(uow: UnitOfWork, checklist_id: UUID) -> ChecklistRecord:
    record = await repo.get_checklist(uow, checklist_id)
    if record is None:
        raise NotFoundError(NOT_FOUND_DETAIL)
    return record


async def _current(uow: UnitOfWork, checklist_id: UUID, expected: int) -> ChecklistRecord:
    """The Checklist at the expected row version and active: 404, 412, then 409."""
    record = await _load(uow, checklist_id)
    if record.row_version != expected:
        raise _stale()
    if record.status == Status.RETIRED:
        raise ChecklistRetiredError(RETIRED_DETAIL)
    return record


def _uuid(raw: str | None, message: str) -> UUID | None:
    if raw is None:
        return None
    try:
        return UUID(raw)
    except ValueError:
        raise UnprocessableError(message) from None


async def _entries(uow: UnitOfWork) -> Entries:
    """Every catalogue entry, retired ones too: existing references keep resolving."""
    return {UUID(e.id): e for e in await list_catalogue(uow, None, include_retired=True)}


def _tag(entry: CatalogueEntry) -> IntegrationTypeTag:
    return IntegrationTypeTag(id=entry.id, code=entry.code, name=entry.name, retired=entry.retired)


def _tags(ids: Iterable[UUID], entries: Entries) -> list[IntegrationTypeTag]:
    tags = [_tag(entries[i]) for i in ids if i in entries]
    tags.sort(key=lambda t: t.name.casefold())
    return tags


def _area(entry_id: UUID | None, entries: Entries) -> AffectedArea | None:
    entry = None if entry_id is None else entries.get(entry_id)
    if entry is None:
        return None
    return AffectedArea(
        id=entry.id, kind=entry.kind, code=entry.code, name=entry.name, retired=entry.retired
    )


def _item_view(item: ItemRecord, entries: Entries) -> ChecklistItem:
    return ChecklistItem(
        id=str(item.item_id),
        kind=ItemKind(item.kind),
        text=item.text,
        why_it_matters=item.why_it_matters,
        affected_area=_area(item.affected_entry_id, entries),
        impact=Impact(item.impact),
        mandatory=item.mandatory,
    )


def _draft_items(draft: dict[str, Any]) -> list[ItemRecord]:
    return [
        ItemRecord(
            item_id=UUID(raw["id"]),
            ordinal=ordinal,
            kind=raw["kind"],
            text=raw["text"],
            why_it_matters=raw["why_it_matters"],
            affected_entry_id=None
            if raw.get("affected_entry_id") is None
            else UUID(raw["affected_entry_id"]),
            impact=raw["impact"],
            mandatory=bool(raw["mandatory"]),
        )
        for ordinal, raw in enumerate(draft.get("items", []))
    ]


def _draft_tag_ids(draft: dict[str, Any]) -> list[UUID]:
    return [UUID(i) for i in draft.get("integration_type_ids", [])]


def _problem(draft: dict[str, Any]) -> str | None:
    return rules.publish_problem(
        products=list(draft.get("products", [])),
        industry=draft.get("industry"),
        integration_type_ids=_draft_tag_ids(draft),
        items=[
            rules.DraftItem(id=i.item_id, text=i.text, why_it_matters=i.why_it_matters)
            for i in _draft_items(draft)
        ],
    )


def _draft_view(draft: dict[str, Any], entries: Entries) -> ChecklistDraft:
    problem = _problem(draft)
    return ChecklistDraft(
        name=draft["name"],
        domain=Domain(draft["domain"]),
        products=list(draft.get("products", [])),
        industry=draft.get("industry"),
        integration_types=_tags(_draft_tag_ids(draft), entries),
        items=[_item_view(i, entries) for i in _draft_items(draft)],
        publishable=problem is None,
        publish_problem=problem,
    )


def _ref(user_id: UUID, names: dict[UUID, str]) -> KnowledgeUserRef:
    return KnowledgeUserRef(id=str(user_id), name=names.get(user_id, UNKNOWN_USER))


async def _views(uow: UnitOfWork, records: list[ChecklistRecord]) -> list[Checklist]:
    entries = await _entries(uow)
    names = await identity.user_names(uow, {r.created_by for r in records})
    tags = await repo.tags_for(uow, [r.id for r in records])
    items = await repo.items_of(
        uow, [(r.id, r.current_version) for r in records if r.current_version is not None]
    )
    views: list[Checklist] = []
    for r in records:
        current = [] if r.current_version is None else items.get((r.id, r.current_version), [])
        views.append(
            Checklist(
                id=str(r.id),
                name=r.name,
                domain=Domain(r.domain),
                products=r.products,
                industry=r.industry,
                integration_types=_tags(tags.get(r.id, []), entries),
                status=Status(r.status),
                retired=r.status == Status.RETIRED,
                retired_reason=r.retired_reason,
                current_version=r.current_version,
                item_count=len(current),
                mandatory_count=sum(1 for i in current if i.mandatory),
                items=[_item_view(i, entries) for i in current],
                draft=None if r.draft is None else _draft_view(r.draft, entries),
                created_by=_ref(r.created_by, names),
                created_at=r.created_at,
                row_version=r.row_version,
            )
        )
    return views


async def _view(uow: UnitOfWork, checklist_id: UUID) -> Checklist:
    (view,) = await _views(uow, [await _load(uow, checklist_id)])
    return view


async def _check_tags(uow: UnitOfWork, ids: list[UUID], already: set[UUID]) -> None:
    """Each tag is an active Integration Type, or one the draft already had (an existing
    reference keeps resolving even once retired). 422 otherwise."""
    kinds = await entry_kinds(uow, ids)
    for entry_id in ids:
        if kinds.get(entry_id) != Kind.INTEGRATION_TYPE.value:
            raise UnprocessableError(rules.RETIRED_TAG_MESSAGE)
        if entry_id not in already and not await validate_catalogue_ref(uow, entry_id):
            raise UnprocessableError(rules.RETIRED_TAG_MESSAGE)


async def _check_areas(
    uow: UnitOfWork, items: list[tuple[UUID, UUID | None]], already: dict[UUID, UUID | None]
) -> None:
    """Each item's affected area is an active Integration Type or Work Package, or the one the
    item already had. `items`: `(item id, area id)`."""
    ids = [a for _, a in items if a is not None]
    kinds = await entry_kinds(uow, ids)
    for item_id, area in items:
        if area is None:
            continue
        if kinds.get(area) not in {Kind.INTEGRATION_TYPE.value, Kind.WORK_PACKAGE.value}:
            raise UnprocessableError(rules.RETIRED_AREA_MESSAGE)
        if already.get(item_id) != area and not await validate_catalogue_ref(uow, area):
            raise UnprocessableError(rules.RETIRED_AREA_MESSAGE)


def _empty_draft(name: str, domain: Domain) -> dict[str, Any]:
    return {
        "name": name,
        "domain": domain.value,
        "products": [],
        "industry": None,
        "integration_type_ids": [],
        "items": [],
    }


def _item_json(item: ItemRecord) -> dict[str, Any]:
    return {
        "id": str(item.item_id),
        "kind": item.kind,
        "text": item.text,
        "why_it_matters": item.why_it_matters,
        "affected_entry_id": None
        if item.affected_entry_id is None
        else str(item.affected_entry_id),
        "impact": item.impact,
        "mandatory": item.mandatory,
    }


# --- queries --------------------------------------------------------------------------------


async def list_checklists(
    uow: UnitOfWork, actor: Principal, *, include_retired: bool
) -> ChecklistList:
    """Checklists by name. Any user with a role."""
    _require_role(actor)
    records = await repo.list_checklists(uow, include_retired=include_retired)
    return ChecklistList(items=await _views(uow, records))


async def read_checklist(uow: UnitOfWork, actor: Principal, checklist_id: UUID) -> Checklist:
    _require_role(actor)
    return await _view(uow, checklist_id)


async def read_checklist_versions(
    uow: UnitOfWork, actor: Principal, checklist_id: UUID
) -> ChecklistVersionList:
    """The published versions, newest first, with publisher, date and counts."""
    _require_role(actor)
    await _load(uow, checklist_id)
    versions = await repo.list_versions(uow, checklist_id)
    counts = await repo.item_counts(uow, checklist_id)
    names = await identity.user_names(uow, {v.published_by for v in versions})
    return ChecklistVersionList(
        items=[
            ChecklistVersionSummary(
                version=v.version,
                name=v.name,
                published_by=_ref(v.published_by, names),
                published_at=v.published_at,
                item_count=counts.get(v.version, (0, 0))[0],
                mandatory_count=counts.get(v.version, (0, 0))[1],
            )
            for v in versions
        ]
    )


async def read_checklist_version(
    uow: UnitOfWork, actor: Principal, checklist_id: UUID, version: int
) -> ChecklistVersion:
    """One published version as it was published, read-only."""
    _require_role(actor)
    await _load(uow, checklist_id)
    record = await repo.get_version(uow, checklist_id, version)
    if record is None:
        raise NotFoundError(VERSION_NOT_FOUND_DETAIL)
    entries = await _entries(uow)
    items = (await repo.items_of(uow, [(checklist_id, version)]))[(checklist_id, version)]
    names = await identity.user_names(uow, {record.published_by})
    scope = record.scope
    return ChecklistVersion(
        checklist_id=str(checklist_id),
        version=record.version,
        name=record.name,
        domain=Domain(record.domain),
        products=list(scope.get("products", [])),
        industry=scope.get("industry"),
        integration_types=_tags((UUID(i) for i in scope.get("integration_type_ids", [])), entries),
        items=[_item_view(i, entries) for i in items],
        published_by=_ref(record.published_by, names),
        published_at=record.published_at,
    )


# --- writes ---------------------------------------------------------------------------------


async def create_checklist(uow: UnitOfWork, actor: Principal, new: NewChecklist) -> Checklist:
    """A new Checklist with an empty draft and no version yet."""
    user_id = _writer(actor, Action.KNOWLEDGE_CHECKLIST_CREATE)
    name = _invalid(new.name, rules.checklist_name)
    checklist_id = new_id()
    await repo.insert_checklist(
        uow,
        checklist_id=checklist_id,
        name=name,
        domain=new.domain.value,
        draft=_empty_draft(name, new.domain),
        created_by=user_id,
    )
    _log.info(
        "knowledge.checklist_created",
        extra={"checklist_id": str(checklist_id), "actor_id": str(user_id)},
    )
    return await _view(uow, checklist_id)


async def open_draft(
    uow: UnitOfWork, actor: Principal, checklist_id: UUID, if_match: str | None
) -> Checklist:
    """Start a draft from the latest published version; its items keep their ids."""
    _writer(actor, Action.KNOWLEDGE_CHECKLIST_EDIT)
    expected = _expected(if_match)
    record = await _current(uow, checklist_id, expected)
    if record.draft is not None or record.current_version is None:
        raise ChecklistDraftExistsError(DRAFT_EXISTS_DETAIL)
    version = await repo.get_version(uow, checklist_id, record.current_version)
    if version is None:  # pragma: no cover - current_version comes from the versions table
        raise NotFoundError(VERSION_NOT_FOUND_DETAIL)
    items = (await repo.items_of(uow, [(checklist_id, version.version)]))[
        (checklist_id, version.version)
    ]
    draft = {
        "name": version.name,
        "domain": version.domain,
        "products": list(version.scope.get("products", [])),
        "industry": version.scope.get("industry"),
        "integration_type_ids": list(version.scope.get("integration_type_ids", [])),
        "items": [_item_json(i) for i in items],
    }
    if await repo.bump(uow, checklist_id, expected_row_version=expected, draft=draft) is None:
        raise _stale()
    return await _view(uow, checklist_id)


async def save_draft(
    uow: UnitOfWork,
    actor: Principal,
    checklist_id: UUID,
    body: DraftInput,
    if_match: str | None,
) -> Checklist:
    """Replace the whole draft. A stale `If-Match` is 412 and overwrites nothing."""
    _writer(actor, Action.KNOWLEDGE_CHECKLIST_EDIT)
    name = _invalid(body.name, rules.checklist_name)
    products = _invalid(body.products, rules.normalize_products)
    industry = _invalid(body.industry, rules.normalize_industry)
    raw_tags = [_uuid(t, rules.RETIRED_TAG_MESSAGE) for t in body.integration_type_ids]
    tag_ids = _invalid([t for t in raw_tags if t is not None], rules.distinct_tags)
    if len(body.items) > rules.ITEMS_MAX:
        raise UnprocessableError(rules.TOO_MANY_ITEMS_MESSAGE)
    given_ids = [_uuid(i.id, rules.UNKNOWN_ITEM_MESSAGE) for i in body.items]
    areas = [_uuid(i.affected_entry_id, rules.RETIRED_AREA_MESSAGE) for i in body.items]
    texts = [_invalid(i.text, rules.item_text) for i in body.items]
    whys = [_invalid(i.why_it_matters, rules.why_it_matters) for i in body.items]

    expected = _expected(if_match)
    record = await _current(uow, checklist_id, expected)
    if record.draft is None:
        raise ChecklistNoDraftError(NO_DRAFT_DETAIL)
    stored = _draft_items(record.draft)
    known = {i.item_id for i in stored} | await repo.published_item_ids(uow, checklist_id)
    _invalid(given_ids, lambda ids: rules.check_item_ids(ids, known))
    await _check_tags(uow, tag_ids, set(_draft_tag_ids(record.draft)))
    item_ids = [i if i is not None else new_id() for i in given_ids]
    await _check_areas(
        uow,
        list(zip(item_ids, areas, strict=True)),
        {i.item_id: i.affected_entry_id for i in stored},
    )
    draft = {
        "name": name,
        "domain": body.domain.value,
        "products": products,
        "industry": industry,
        "integration_type_ids": [str(t) for t in tag_ids],
        "items": [
            {
                "id": str(item_id),
                "kind": item.kind.value,
                "text": text,
                "why_it_matters": why,
                "affected_entry_id": None if area is None else str(area),
                "impact": item.impact.value,
                "mandatory": item.mandatory,
            }
            for item_id, item, text, why, area in zip(
                item_ids, body.items, texts, whys, areas, strict=True
            )
        ],
    }
    if await repo.bump(uow, checklist_id, expected_row_version=expected, draft=draft) is None:
        raise _stale()
    return await _view(uow, checklist_id)


async def publish_checklist(
    uow: UnitOfWork, actor: Principal, checklist_id: UUID, if_match: str | None
) -> Checklist:
    """The draft becomes the next version; the header's published scope follows it."""
    user_id = _writer(actor, Action.KNOWLEDGE_CHECKLIST_PUBLISH)
    expected = _expected(if_match)
    record = await _current(uow, checklist_id, expected)
    draft = record.draft
    if draft is None:
        raise ChecklistNoDraftError(NO_DRAFT_DETAIL)
    problem = _problem(draft)
    if problem is not None:
        raise UnprocessableError(problem)
    items = _draft_items(draft)
    tag_ids = _draft_tag_ids(draft)
    products = list(draft.get("products", []))
    industry = draft.get("industry")
    if (
        await repo.bump(
            uow,
            checklist_id,
            expected_row_version=expected,
            draft=None,
            name=draft["name"],
            domain=draft["domain"],
            products=products,
            industry=industry,
        )
        is None
    ):
        raise _stale()
    version = await repo.next_version(uow, checklist_id)
    await repo.insert_version(
        uow,
        checklist_id=checklist_id,
        version=version,
        name=draft["name"],
        domain=draft["domain"],
        scope={
            "products": products,
            "industry": industry,
            "integration_type_ids": [str(t) for t in tag_ids],
        },
        published_by=user_id,
        items=items,
    )
    await repo.set_tags(uow, checklist_id, tag_ids)
    mandatory = sum(1 for i in items if i.mandatory)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeChecklistPublished(
            version=version, item_count=len(items), mandatory_count=mandatory
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=checklist_id,
        subject_version=version,
    )
    _log.info(
        "knowledge.checklist_published",
        extra={
            "checklist_id": str(checklist_id),
            "actor_id": str(user_id),
            "version": version,
            "item_count": len(items),
        },
    )
    return await _view(uow, checklist_id)


async def retire_checklist(
    uow: UnitOfWork,
    actor: Principal,
    checklist_id: UUID,
    request: RetireChecklist,
    if_match: str | None,
) -> Checklist:
    """Retire with a reason, discarding the draft. Earlier versions stay readable."""
    user_id = _writer(actor, Action.KNOWLEDGE_CHECKLIST_RETIRE)
    reason = _invalid(request.reason, rules.retire_reason)
    expected = _expected(if_match)
    record = await _current(uow, checklist_id, expected)
    if (
        await repo.bump(
            uow,
            checklist_id,
            expected_row_version=expected,
            draft=None,
            retire_with_reason=reason,
        )
        is None
    ):
        raise _stale()
    await trace.append(
        uow,
        actor=actor.actor,
        payload=KnowledgeChecklistRetired(
            version=record.current_version, discarded_draft=record.draft is not None
        ),
        subject_type=rules.SUBJECT_TYPE,
        subject_id=checklist_id,
        subject_version=record.current_version,
    )
    _log.info(
        "knowledge.checklist_retired",
        extra={"checklist_id": str(checklist_id), "actor_id": str(user_id)},
    )
    return await _view(uow, checklist_id)


# --- for other modules (no authorization: callers decide what they may show) ----------------


async def find_applicable_checklists(
    uow: UnitOfWork,
    *,
    products: Iterable[str],
    industry: str | None,
    integration_type_ids: Iterable[UUID],
) -> list[ApplicableChecklist]:
    """The latest published version of every active Checklist whose published scope shares
    a product, the industry or an Integration Type with what is asked (names trimmed and
    compared ignoring case), by name. Retired and never-published Checklists never apply;
    a draft is ignored until it is published."""
    want_products = {rules.match_key(p) for p in products if p.strip()}
    want_industry = rules.match_key(industry) if industry and industry.strip() else None
    want_types = set(integration_type_ids)
    records = await repo.published_active(uow)
    tags = await repo.tags_for(uow, [r.id for r in records])
    matching = [
        r
        for r in records
        if rules.scope_matches(
            products=r.products,
            industry=r.industry,
            integration_type_ids=tags.get(r.id, []),
            want_products=want_products,
            want_industry=want_industry,
            want_types=want_types,
        )
    ]
    matching.sort(key=lambda r: (r.name.casefold(), r.id))
    pairs = [(r.id, r.current_version) for r in matching if r.current_version is not None]
    items = await repo.items_of(uow, pairs)
    return [
        ApplicableChecklist(
            checklist_id=str(checklist_id),
            version=version,
            name=r.name,
            domain=Domain(r.domain),
            items=[
                ApplicableItem(
                    item_id=str(i.item_id),
                    kind=ItemKind(i.kind),
                    text=i.text,
                    why_it_matters=i.why_it_matters,
                    affected_entry_id=None
                    if i.affected_entry_id is None
                    else str(i.affected_entry_id),
                    impact=Impact(i.impact),
                    mandatory=i.mandatory,
                )
                for i in items[(checklist_id, version)]
            ],
        )
        for r, (checklist_id, version) in zip(matching, pairs, strict=True)
    ]
