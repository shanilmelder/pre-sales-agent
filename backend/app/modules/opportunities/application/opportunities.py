"""Opportunity commands and queries (Stories 1.7 and 1.8).

Every command follows the AD-3 path inside the caller's Unit of Work: authorize, domain
rules, `row_version` (`If-Match`), write, then trace. Access goes through `identity`'s
policy with a `Resource` carrying the owner and collaborator ids:

- reading: the owner, collaborators, and roles that grant `opportunities.opportunity.read`;
  anyone else gets the same 404 `not_found` as for an id that doesn't exist;
- managing collaborators and editing the title and target proposal date: the owner only
  (403 `forbidden` for other readers).

Adding a collaborator who already is one, removing one who isn't, or an edit that changes
no field, is a no-op that writes nothing and appends no event.

Story 9.1: `grant_reviewer_access` and `revoke_reviewer_access` (for `reviews`, in the
caller's Unit of Work, no authorization) share the Opportunity read only with a requested
reviewer and stop sharing it once they have no pending Review Request left. A reviewer is
listed under `reviewers`; the owner can't remove them, and adding them as a collaborator
makes them a full one (whom revoking no longer removes). Trace payloads and logs carry
ids only, never customer content.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal, Resource
from app.modules.opportunities.adapters import repository
from app.modules.opportunities.adapters.repository import OpportunityRecord, Where
from app.modules.opportunities.application.models import (
    EstimateSummary,
    NewOpportunity,
    Opportunity,
    OpportunityChanges,
    OpportunityFacets,
    OpportunityFilters,
    OpportunityPage,
    OpportunitySummary,
    UserRef,
)
from app.modules.opportunities.domain.opportunity import (
    SUBJECT_TYPE,
    Outcome,
    check_target_date,
    retention_until,
)
from app.platform import trace
from app.platform.actor import Actor
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
_SYSTEM_REVIEWS = Actor(type="system", id="reviews.review_request")
"""The default actor of a reviewer's access change (callers pass the person)."""


def _not_found() -> NotFoundError:
    # One body for "doesn't exist" and "you may not see it", so nothing leaks.
    return NotFoundError(NOT_FOUND_DETAIL)


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Opportunity was changed by someone else since you opened it. Reload and try again."
    )


def _resource(record: OpportunityRecord, members: list[UUID], reviewers: list[UUID]) -> Resource:
    return Resource(
        type=SUBJECT_TYPE,
        id=record.id,
        owner_id=record.owner_id,
        member_ids=frozenset(members),
        reviewer_ids=frozenset(reviewers),
    )


async def _load_readable(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> tuple[OpportunityRecord, list[UUID], Resource]:
    record = await repository.get(uow, opportunity_id)
    if record is None:
        raise _not_found()
    members = await repository.collaborator_ids(uow, opportunity_id)
    reviewers = await repository.collaborator_ids(uow, opportunity_id, role=repository.REVIEWER)
    resource = _resource(record, members, reviewers)
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
    reviewers = sorted(resource.reviewer_ids, key=str)
    wanted = {record.owner_id, *members, *reviewers, *([changer] if changer else [])}
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
        reviewers=sorted(
            (_ref(reviewer, names) for reviewer in reviewers),
            key=lambda ref: (ref.name.casefold(), ref.id),
        ),
        row_version=record.row_version,
        created_at=record.created_at,
        last_changed_by=names.get(changer) if changer else None,
        can_manage_collaborators=identity.can(actor, Action.COLLABORATOR_ADD, resource)
        and identity.can(actor, Action.COLLABORATOR_REMOVE, resource),
        can_edit=identity.can(actor, Action.OPPORTUNITY_UPDATE, resource),
        can_add_sources=identity.can(actor, Action.SOURCE_ADD, resource),
        outcome=record.outcome,
        outcome_recorded_at=record.outcome_recorded_at,
        contract_end_date=record.contract_end_date,
        retention_until=retention_until(
            record.outcome, record.outcome_recorded_at, record.contract_end_date
        ),
        can_record_outcome=record.outcome is None
        and identity.can(actor, Action.OUTCOME_RECORD, resource),
        can_change_contract_end=record.outcome is Outcome.WON
        and identity.can(actor, Action.CONTRACT_END_DATE_UPDATE, resource),
        can_reopen_outcome=record.outcome is not None
        and identity.can(actor, Action.OUTCOME_REOPEN, resource),
    )


# --- queries --------------------------------------------------------------------------------


async def get(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> Opportunity:
    record, members, resource = await _load_readable(uow, actor, opportunity_id)
    return await _detail(uow, actor, record, members, resource)


@dataclass(frozen=True, slots=True)
class OpportunityScope:
    """What decides which Checklists apply to an Opportunity (Story 4.2)."""

    products: tuple[str, ...]
    industry: str | None


async def opportunity_scope(uow: UnitOfWork, opportunity_id: UUID) -> OpportunityScope | None:
    """The Opportunity's products and industry, or None if it doesn't exist. No
    authorization: for jobs acting on the Opportunity (Gap detection), not the API."""
    record = await repository.get(uow, opportunity_id)
    if record is None:
        return None
    return OpportunityScope(products=tuple(record.products), industry=record.industry or None)


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
    # Imported here: gaps, conflicts and estimates import opportunities' public API.
    from app.modules.conflicts.application import public as conflicts
    from app.modules.estimates.application import public as estimates
    from app.modules.gaps.application import public as gaps

    ids = [r.id for r in records]
    names = await identity.user_names(uow, {r.owner_id for r in records})
    # One batched read per module, whatever the page size.
    open_gaps = await gaps.open_gap_counts(uow, ids)
    open_conflicts = await conflicts.open_conflict_counts(uow, ids)
    current = await estimates.current_estimates(uow, ids)
    blockers = await estimates.submission_blocker_counts(uow, ids)
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
                open_gaps=open_gaps.get(r.id, 0),
                open_conflicts=open_conflicts.get(r.id, 0),
                blocker_count=blockers.get(r.id, 0),
                estimate=None
                if (e := current.get(r.id)) is None
                else EstimateSummary(
                    version=e.version,
                    status=e.status.value,
                    total_hours=e.total_hours,
                    is_baseline=e.is_baseline,
                ),
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


@dataclass(frozen=True, slots=True)
class ReadableOpportunities:
    """Which Opportunities the caller can read (Story 10.3: Reports filter their rows by it
    before aggregating). `everything`: all of them; otherwise exactly `ids`."""

    everything: bool
    ids: frozenset[UUID] = frozenset()

    def includes(self, opportunity_id: UUID) -> bool:
        return self.everything or opportunity_id in self.ids


async def readable_opportunities(uow: UnitOfWork, actor: Principal) -> ReadableOpportunities:
    """The Opportunities the caller can read: the same set as `list_all` (every one with
    `opportunities.opportunity.read`, else those they own or collaborate on, none without a
    role)."""
    sees_any, where = _visibility(actor, everything=identity.can(actor, Action.OPPORTUNITY_READ))
    if not sees_any:
        return ReadableOpportunities(everything=False)
    if where is None:
        return ReadableOpportunities(everything=True)
    return ReadableOpportunities(everything=False, ids=await repository.ids_matching(uow, where))


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


async def create(
    uow: UnitOfWork, actor: Principal, new: NewOpportunity, *, from_import: bool = False
) -> Opportunity:
    """Create an Opportunity owned by the caller (`presales_engineer` only). `from_import`:
    started from an Opportunity import (`application.imports`), recorded on the trace
    event; the import itself is checked and consumed by the caller."""
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
        payload=OpportunitiesOpportunityCreated(from_import=from_import),
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

    if not removing and user_id not in await identity.user_names(uow, [user_id]):
        raise InvalidCollaboratorError("Only users who have signed in can be collaborators.")

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


async def opportunity_titles(
    uow: UnitOfWork, opportunity_ids: set[UUID] | frozenset[UUID] | list[UUID]
) -> dict[UUID, str]:
    """Story 9.2: `{id: title}` for the Opportunities that exist, for Inbox summaries and
    rows. No authorization: callers decide what they may show."""
    return await repository.titles(uow, sorted(set(opportunity_ids)))


async def opportunity_owner(uow: UnitOfWork, opportunity_id: UUID) -> UUID | None:
    """Story 9.2: the Opportunity's owner (the recipient of a system-queued run's Inbox
    items), or None when unknown. No authorization."""
    return (await repository.owners(uow, [opportunity_id])).get(opportunity_id)


# --- reviewer collaboration (Story 9.1) -----------------------------------------------------


async def grant_reviewer_access(
    uow: UnitOfWork, opportunity_id: UUID, user_id: UUID, *, actor: Actor = _SYSTEM_REVIEWS
) -> bool:
    """Share the Opportunity read only with `user_id` as a reviewer, unless they are its
    owner or already share it. True if this call added them (traced
    `opportunities.collaborator.added` with role `reviewer`, as `actor`: the person whose
    command it follows from). No authorization: `reviews` calls it in its own command's Unit
    of Work."""
    record = await repository.get(uow, opportunity_id)
    if record is None:
        raise _not_found()
    if user_id == record.owner_id or not await repository.add_reviewer(
        uow, opportunity_id, user_id
    ):
        return False
    await trace.append(
        uow,
        actor=actor,
        payload=OpportunitiesCollaboratorAdded(user_id=str(user_id), role="reviewer"),
        subject_type=SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
        subject_version=record.row_version,
    )
    return True


async def revoke_reviewer_access(
    uow: UnitOfWork,
    opportunity_id: UUID,
    user_id: UUID,
    *,
    has_pending: bool,
    actor: Actor = _SYSTEM_REVIEWS,
) -> bool:
    """Stop sharing the Opportunity with the reviewer `user_id` when `has_pending` (the
    caller's answer: whether they still have a pending Review Request on it) is false. Only a
    `reviewer` row is removed, never a collaborator's. True if this call removed it (traced
    `opportunities.collaborator.removed` with role `reviewer`). No authorization."""
    if has_pending:
        return False
    record = await repository.get(uow, opportunity_id)
    if record is None or not await repository.remove_collaborator(
        uow, opportunity_id, user_id, role=repository.REVIEWER
    ):
        return False
    await trace.append(
        uow,
        actor=actor,
        payload=OpportunitiesCollaboratorRemoved(user_id=str(user_id), role="reviewer"),
        subject_type=SUBJECT_TYPE,
        subject_id=opportunity_id,
        opportunity_id=opportunity_id,
        subject_version=record.row_version,
    )
    return True
