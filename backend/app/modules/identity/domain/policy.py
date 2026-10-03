"""Authorization policy (AD-15): which roles grant which actions. Pure, no I/O.

Resource-scoped rules (Opportunity owner, collaborators) arrive with Story 1.7 and belong
here too.
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


@dataclass(frozen=True, slots=True)
class Resource:
    """The thing an action targets, for resource-scoped rules (Story 1.7+)."""

    type: str
    id: UUID


POLICY: Mapping[Action, frozenset[Role]] = MappingProxyType(
    {
        Action.USER_LIST: frozenset({Role.PLATFORM_ADMINISTRATOR}),
        Action.USER_ASSIGN_ROLE: frozenset({Role.PLATFORM_ADMINISTRATOR}),
        Action.USER_REMOVE_ROLE: frozenset({Role.PLATFORM_ADMINISTRATOR}),
    }
)


def is_allowed(principal: Principal, action: Action, resource: Resource | None = None) -> bool:
    """True if one of the principal's roles grants the action. Agent and system actors
    follow the same rule: with no granting role they are denied."""
    granting = POLICY.get(action, frozenset())
    return not principal.roles.isdisjoint(granting)
