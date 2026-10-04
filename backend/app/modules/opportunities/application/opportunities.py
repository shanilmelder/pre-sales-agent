"""Opportunity commands and queries (Stories 1.7 and 1.8).

Every command follows the AD-3 path inside the caller's Unit of Work: authorize, domain
rules, `row_version` (`If-Match`), write, then trace. Access goes through `identity`'s
policy with a `Resource` carrying the owner and collaborator ids:

- reading: the owner, collaborators, and roles that grant `opportunities.opportunity.read`;
  anyone else gets the same 404 `not_found` as for an id that doesn't exist;
- managing collaborators and editing the title and target proposal date: the owner only
  (403 `forbidden` for other readers).

Adding a collaborator who already is one, removing one who isn't, or an edit that changes
no field, is a no-op that writes nothing and appends no event. Trace payloads and logs carry
ids only, never customer content.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.opportunities.adapters import repository
from app.modules.opportunities.adapters.repository import OpportunityRecord, Where
from app.modules.opportunities.application.models import (
    NewOpportunity,
    Opportunity,
    OpportunityChanges,
    OpportunityFacets,
    OpportunityFilters,
    OpportunityPage,
    OpportunitySummary,
    UserRef,
)
from app.modules.opportunities.domain.opportunity import SUBJECT_TYPE, check_target_date
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    ForbiddenError,
    InvalidCollaboratorError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    OpportunitiesCollaboratorAdded,
    OpportunitiesCollaboratorRemoved,
    OpportunitiesOpportunityCreated,
    OpportunitiesOpportunityUpdated,
)
from app.platform.uow import UnitOfWork

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_PAGE = 1_000_000
MAX_ROW_VERSION = 2**31 - 1
NOT_FOUND_DETAIL = "No Opportunity with this id."
UNKNOWN_USER = "Unknown user"
PAST_DATE_DETAIL = "The target proposal date can't be in the past."
_log = get_logger(__name__)


def _not_found() -> NotFoundError:
    # One body for "doesn't exist" and "you may not see it", so nothing leaks.
    return NotFoundError(NOT_FOUND_DETAIL)


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Opportunity was changed by someone else since you opened it. Reload and try again."
    )


def _resource(record: OpportunityRecord, members: list[UUID]) -> Resource:
    return Resource(
        type=SUBJECT_TYPE, id=record.id, owner_id=record.owner_id, member_ids=frozenset(members)
    )


async def _load_readable(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> tuple[OpportunityRecord, list[UUID], Resource]:
    record = await repository.get(uow, opportunity_id)
    if record is None:
        raise _not_found()
    members = await repository.collaborator_ids(uow, opportunity_id)
    resource = _resource(record, members)
    if not identity.can(actor, Action.OPPORTUNITY_READ, resource):
        raise _not_found()
    return record, members, resource


def _ref(user_id: UUID, names: dict[UUID, str]) -> UserRef:
    return UserRef(id=str(user_id), name=names.get(user_id, UNKNOWN_USER))


async def _detail(
    uow: UnitOfWork,
    actor: Principal,
    record: OpportunityRecord,
    members: list[UUID],
    resource: Resource,
) -> Opportunity:
    changer = await repository.last_changer_id(uow, record.id)
    wanted = {record.owner_id, *members, *([changer] if changer else [])}
    names = await identity.user_names(uow, wanted)
    return Opportunity(
        id=str(record.id),
        title=record.title,
        customer_name=record.customer_name,
        products=record.products,
        industry=record.industry,
        target_proposal_date=record.target_proposal_date,
        status=record.status,
        owner=_ref(record.owner_id, names),
        collaborators=[_ref(member, names) for member in members],
        row_version=record.row_version,
        created_at=record.created_at,
        last_changed_by=names.get(changer) if changer else None,
        can_manage_collaborators=identity.can(actor, Action.COLLABORATOR_ADD, resource)
        and identity.can(actor, Action.COLLABORATOR_REMOVE, resource),
        can_edit=identity.can(actor, Action.OPPORTUNITY_UPDATE, resource),
        can_add_sources=identity.can(actor, Action.SOURCE_ADD, resource),
    )


# --- queries --------------------------------------------------------------------------------


async def get(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> Opportunity:
    record, members, resource = await _load_readable(uow, actor, opportunity_id)
    return await _detail(uow, actor, record, members, resource)


async def readable_resource(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> Resource:
    """The Opportunity as an authorization `Resource` (its owner and collaborators), for
    other modules that act on things inside it. Raises the same 404 `not_found` as `get`
    when it doesn't exist or the caller may not read it."""
    _, _, resource = await _load_readable(uow, actor, opportunity_id)
    return resource


def _visibility(actor: Principal, *, everything: bool) -> tuple[bool, Where | None]:
    """Whether the caller can read any Opportunity, and the filter for the ones they can
    (None: every one)."""
    if everything:
        return True, None
    user_id = actor.user_id
    # Owner and member access needs at least one role (the policy's rule), so a user whose
    # roles were all removed sees nothing.
    if user_id is None or not actor.roles:
        return False, None
    return True, repository.involving(user_id)


async def _page(
    uow: UnitOfWork,
    actor: Principal,
    *,
    everything: bool,
    page: int,
    page_size: int,
    filters: OpportunityFilters | None = None,
) -> OpportunityPage:
    sees_any, where = _visibility(actor, everything=everything)
    if not sees_any:
        return OpportunityPage(items=[], page=page, page_size=page_size, total=0)
    if filters is not None:
        # Filters only narrow: they are ANDed onto the visibility filter.
        where = repository.matching(
            where,
            status=filters.status,
            owner_id=filters.owner_id,
            product=filters.product,
            date_from=filters.date_from,
            date_to=filters.date_to,
        )
    records, total = await repository.list_page(
        uow, where, offset=(page - 1) * page_size, limit=page_size
    )
    names = await identity.user_names(uow, {r.owner_id for r in records})
    return OpportunityPage(
        items=[
            OpportunitySummary(
                id=str(r.id),
                title=r.title,
                customer_name=r.customer_name,
                status=r.status,
                owner=_ref(r.owner_id, names),
                target_proposal_date=r.target_proposal_date,
                created_at=r.created_at,
            )
            for r in records
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


async def list_mine(
    uow: UnitOfWork, actor: Principal, *, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
) -> OpportunityPage:
    """Opportunities the caller owns or collaborates on (readable by definition)."""
    return await _page(uow, actor, everything=False, page=page, page_size=page_size)


async def list_all(
    uow: UnitOfWork,
    actor: Principal,
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    filters: OpportunityFilters | None = None,
) -> OpportunityPage:
    """Every Opportunity the caller can read: all of them when a role grants reading every
    Opportunity, otherwise the ones they own or collaborate on. `filters` narrow that set
    and never widen it."""
    everything = identity.can(actor, Action.OPPORTUNITY_READ)
    return await _page(
        uow, actor, everything=everything, page=page, page_size=page_size, filters=filters
    )


async def facets(uow: UnitOfWork, actor: Principal) -> OpportunityFacets:
    """The owners and products across the Opportunities the caller can read (the same set
    as `list_all`), for the All Opportunities filters. Owners are sorted by name and
    products by name, both ignoring case."""
    sees_any, where = _visibility(actor, everything=identity.can(actor, Action.OPPORTUNITY_READ))
    if not sees_any:
        return OpportunityFacets(owners=[], products=[])
    owner_ids, products = await repository.facets(uow, where)
    names = await identity.user_names(uow, set(owner_ids))
    owners = sorted(
        (_ref(owner_id, names) for owner_id in owner_ids),
        key=lambda ref: (ref.name.casefold(), ref.id),
    )
    return OpportunityFacets(owners=owners, products=products)


# --- commands -------------------------------------------------------------------------------


async def create(uow: UnitOfWork, actor: Principal, new: NewOpportunity) -> Opportunity:
    """Create an Opportunity owned by the caller (`presales_engineer` only)."""
    identity.authorize(actor, Action.OPPORTUNITY_CREATE)
    owner_id = actor.user_id
    if owner_id is None:
        raise ForbiddenError("Only a signed-in user can own an Opportunity.")
    opportunity_id = new_id()
    await repository.insert_opportunity(
        uow,
        opportunity_id=opportunity_id,
        owner_id=owner_id,
        title=new.title or new.customer_name,
        customer_name=new.customer_name,
        products=new.products,
        industry=new.industry,
        target_proposal_date=new.target_proposal_date,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=OpportunitiesOpportunityCreated(),
        subject_type=SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
        subject_version=1,
    )
    _log.info(
        "opportunities.opportunity_created",
        extra={"opportunity_id": str(opportunity_id), "actor_id": actor.actor.id},
    )
    return await get(uow, actor, opportunity_id)


async def update(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    changes: OpportunityChanges,
    if_match: str | None,
) -> Opportunity:
    """Edit the title and/or target proposal date. Owner only. `if_match` is the raw
    `If-Match` header (428/412).

    A blank title falls back to the customer name. The date may not be in the past (UTC),
    checked only when it differs from the stored one, so an already-past date can be resent
    unchanged. When nothing actually changes nothing is written or traced (a stale
    `If-Match` is still 412); otherwise the version is bumped once and one
    `opportunities.opportunity.updated` event names the changed fields."""
    record, members, resource = await _load_readable(uow, actor, opportunity_id)
    identity.authorize(actor, Action.OPPORTUNITY_UPDATE, resource)

    changed: list[Literal["title", "target_proposal_date"]] = []
    title: str | None = None
    if changes.title is not None:
        title = changes.title or record.customer_name
        if title != record.title:
            changed.append("title")
    target_date = changes.target_proposal_date
    if target_date is not None and target_date != record.target_proposal_date:
        try:
            check_target_date(target_date, today=datetime.now(UTC).date())
        except ValueError:
            raise UnprocessableError(PAST_DATE_DETAIL) from None
        changed.append("target_proposal_date")

    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        # The stored version can't be this large, or bumping it would overflow int4.
        raise _stale()

    if not changed:
        # Nothing to change, but a stale view must still be told to reload.
        if record.row_version != expected:
            raise _stale()
        return await _detail(uow, actor, record, members, resource)

    new_version = await repository.bump_row_version(uow, opportunity_id, expected)
    if new_version is None:
        raise _stale()
    await repository.update_fields(
        uow,
        opportunity_id,
        title=title if "title" in changed else None,
        target_proposal_date=target_date if "target_proposal_date" in changed else None,
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=OpportunitiesOpportunityUpdated(fields=changed),
        subject_type=SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
        subject_version=new_version,
    )
    _log.info(
        "opportunities.opportunity_updated",
        extra={
            "opportunity_id": str(opportunity_id),
            "actor_id": actor.actor.id,
            "fields": list(changed),
        },
    )
    return await get(uow, actor, opportunity_id)


async def add_collaborator(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, user_id: UUID, if_match: str | None
) -> Opportunity:
    """Share the Opportunity with `user_id`, who must hold at least one role. Owner only.
    `if_match` is the raw `If-Match` header (428/412)."""
    return await _change_member(uow, actor, opportunity_id, user_id, if_match, removing=False)


async def remove_collaborator(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, user_id: UUID, if_match: str | None
) -> Opportunity:
    """Stop sharing the Opportunity with `user_id`. Owner only; applies on their next
    request."""
    return await _change_member(uow, actor, opportunity_id, user_id, if_match, removing=True)


async def _change_member(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    user_id: UUID,
    if_match: str | None,
    *,
    removing: bool,
) -> Opportunity:
    record, members, resource = await _load_readable(uow, actor, opportunity_id)
    identity.authorize(
        actor, Action.COLLABORATOR_REMOVE if removing else Action.COLLABORATOR_ADD, resource
    )
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION:
        # The stored version can't be this large, or bumping it would overflow int4.
        raise _stale()

    if user_id == record.owner_id:
        raise InvalidCollaboratorError(
            "The owner can't be removed."
            if removing
            else "The owner can't be added as a collaborator."
        )

    if (user_id in members) != removing:
        # Nothing to change, but a stale view must still be told to reload.
        if record.row_version != expected:
            raise _stale()
        return await _detail(uow, actor, record, members, resource)

    if not removing and user_id not in await identity.user_names(
        uow, [user_id], with_roles_only=True
    ):
        raise InvalidCollaboratorError("Only users who hold a role can be collaborators.")

    new_version = await repository.bump_row_version(uow, opportunity_id, expected)
    if new_version is None:
        raise _stale()
    write = repository.remove_collaborator if removing else repository.add_collaborator
    if not await write(uow, opportunity_id, user_id):
        # Membership changed by a path that did not bump the version: the caller's view is
        # out of date. Raising rolls back the bump.
        raise _stale()

    payload = (OpportunitiesCollaboratorRemoved if removing else OpportunitiesCollaboratorAdded)(
        user_id=str(user_id)
    )
    await trace.append(
        uow,
        actor=actor.actor,
        payload=payload,
        subject_type=SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
        subject_version=new_version,
    )
    _log.info(
        "opportunities.collaborator_removed" if removing else "opportunities.collaborator_added",
        extra={
            "opportunity_id": str(opportunity_id),
            "user_id": str(user_id),
            "actor_id": actor.actor.id,
        },
    )
    return await get(uow, actor, opportunity_id)
