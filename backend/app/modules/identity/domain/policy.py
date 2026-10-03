"""Authorization policy (AD-15): which roles, and which relations to a resource, grant
which actions. Pure, no I/O.

Two kinds of grant, either of which allows an action:

- **Role grants** (`POLICY`): a role allows the action on every resource of its kind.
- **Resource-scoped grants**: the principal's relation to the resource. The resource's
  owner gets `OWNER_GRANTS`, its members (e.g. Opportunity collaborators) `MEMBER_GRANTS`.
  The caller loads `owner_id` and `member_ids` into the `Resource` before asking.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from app.modules.identity.actions import Action
from app.modules.identity.domain.roles import Role
from app.platform.actor import Actor


@dataclass(frozen=True, slots=True)
class Principal:
    """identity's actor: a platform `Actor` plus the roles loaded for it at the edge.

    Roles are loaded per request, so role changes take effect on the next request."""

    actor: Actor
    roles: frozenset[Role] = frozenset()

    @property
    def user_id(self) -> UUID | None:
        """The platform user id behind a `user` actor; None for agents, systems and ids
        that are not UUIDs."""
        if self.actor.type != "user":
            return None
        try:
            return UUID(self.actor.id)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class Resource:
    """The thing an action targets. `owner_id` and `member_ids` feed the resource-scoped
    rules; leave them empty for resources without owners or members."""

    type: str
    id: UUID
    owner_id: UUID | None = None
    member_ids: frozenset[UUID] = frozenset()


OPPORTUNITY_RESOURCE = "opportunities.opportunity"
"""The only resource type the owner/member rules apply to."""

POLICY: Mapping[Action, frozenset[Role]] = MappingProxyType(
    {
        Action.USER_LIST: frozenset({Role.PLATFORM_ADMINISTRATOR}),
        Action.USER_ASSIGN_ROLE: frozenset({Role.PLATFORM_ADMINISTRATOR}),
        Action.USER_REMOVE_ROLE: frozenset({Role.PLATFORM_ADMINISTRATOR}),
        # Presales engineers look people up to pick collaborators.
        Action.USER_SEARCH: frozenset({Role.PRESALES_ENGINEER}),
        Action.OPPORTUNITY_CREATE: frozenset({Role.PRESALES_ENGINEER}),
        Action.OPPORTUNITY_READ: frozenset({Role.HEAD_OF_DELIVERY, Role.PLATFORM_ADMINISTRATOR}),
        # Only the owner edits the Opportunity or manages collaborators: no role grants it.
        Action.OPPORTUNITY_UPDATE: frozenset(),
        Action.COLLABORATOR_ADD: frozenset(),
        Action.COLLABORATOR_REMOVE: frozenset(),
    }
)

OWNER_GRANTS: frozenset[Action] = frozenset(
    {
        Action.OPPORTUNITY_READ,
        Action.OPPORTUNITY_UPDATE,
        Action.COLLABORATOR_ADD,
        Action.COLLABORATOR_REMOVE,
    }
)
MEMBER_GRANTS: frozenset[Action] = frozenset({Action.OPPORTUNITY_READ})


def is_allowed(principal: Principal, action: Action, resource: Resource | None = None) -> bool:
    """True if one of the principal's roles grants the action, or the principal is the
    resource's owner or a member and that relation grants it. Relations count only on an
    Opportunity and only for principals holding at least one role (a user whose roles were
    all removed loses access). Agent and system actors follow the same rules: with no
    granting role or relation they are denied."""
    if not principal.roles.isdisjoint(POLICY.get(action, frozenset())):
        return True
    if resource is None or resource.type != OPPORTUNITY_RESOURCE or not principal.roles:
        return False
    user_id = principal.user_id
    if user_id is None:
        return False
    if action in OWNER_GRANTS and resource.owner_id is not None and user_id == resource.owner_id:
        return True
    return action in MEMBER_GRANTS and user_id in resource.member_ids
