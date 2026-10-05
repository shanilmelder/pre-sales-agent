"""Authorization policy (AD-15): which roles, and which relations to a resource, grant
which actions. Pure, no I/O.

Two kinds of grant, either of which allows an action:

- **Role grants** (`POLICY`): a role allows the action on every resource of its kind.
- **Resource-scoped grants**: the principal's relation to the resource. The resource's
  owner gets `OWNER_GRANTS`, its members (e.g. Opportunity collaborators) `MEMBER_GRANTS`.
  The caller loads `owner_id` and `member_ids` into the `Resource` before asking.
  `RELATION_EXCLUDED_ROLES` withholds a relation grant from a principal whose roles are all
  excluded for that action (FR-64: sales representatives on an Opportunity can't edit its
  Requirements, start Gap detection, draft an Estimate, accept an Assumption, start a Red
  Team Review or export the Estimate). Roles add up, so someone who also holds a role that
  isn't excluded keeps the grant.
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
        # The owner and collaborators add Sources, whatever their role (so sales
        # representatives on the Opportunity can); no role grants it on its own.
        Action.SOURCE_ADD: frozenset(),
        # Starting (retrying) Requirement extraction follows adding Sources: the owner and
        # collaborators, whatever their role.
        Action.EXTRACTION_START: frozenset(),
        # Editing and confirming Requirements: the owner and collaborators, except sales
        # representatives (`RELATION_EXCLUDED_ROLES`); no role grants it on its own.
        Action.REQUIREMENT_EDIT: frozenset(),
        # Starting (retrying) Gap detection (Story 4.3): like editing Requirements, the owner
        # and collaborators except sales representatives.
        Action.GAP_DETECTION_START: frozenset(),
        # Editing and approving Clarification Questions (Story 4.5): the owner and
        # collaborators except sales representatives.
        Action.GAP_QUESTION_EDIT: frozenset(),
        # Starting (retrying) an Estimate draft (Story 8.1): the owner and collaborators
        # except sales representatives.
        Action.ESTIMATE_DRAFT_START: frozenset(),
        # Accepting an Assumption (Story 8.4): the owner and collaborators except sales
        # representatives; always as themselves.
        Action.ASSUMPTION_ACCEPT: frozenset(),
        # Starting (retrying) a Red Team Review (Story 6.5): the owner and collaborators
        # except sales representatives.
        Action.RED_TEAM_START: frozenset(),
        # Starting an assessment run, or retrying one of its tasks (Epic 5 slice 5A): the
        # owner and collaborators except sales representatives.
        Action.ASSESSMENT_START: frozenset(),
        # Exporting the Estimate (Story 8.8): the owner and collaborators except sales
        # representatives.
        Action.ESTIMATE_EXPORT: frozenset(),
    }
)

RELATION_EXCLUDED_ROLES: Mapping[Action, frozenset[Role]] = MappingProxyType(
    {
        Action.REQUIREMENT_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_DETECTION_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_QUESTION_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_DRAFT_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSUMPTION_ACCEPT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.RED_TEAM_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSESSMENT_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_EXPORT: frozenset({Role.SALES_REPRESENTATIVE}),
    }
)
"""Per action, the roles that don't earn its owner or member grant on their own."""

OWNER_GRANTS: frozenset[Action] = frozenset(
    {
        Action.OPPORTUNITY_READ,
        Action.OPPORTUNITY_UPDATE,
        Action.COLLABORATOR_ADD,
        Action.COLLABORATOR_REMOVE,
        Action.SOURCE_ADD,
        Action.EXTRACTION_START,
        Action.REQUIREMENT_EDIT,
        Action.GAP_DETECTION_START,
        Action.GAP_QUESTION_EDIT,
        Action.ESTIMATE_DRAFT_START,
        Action.ASSUMPTION_ACCEPT,
        Action.RED_TEAM_START,
        Action.ASSESSMENT_START,
        Action.ESTIMATE_EXPORT,
    }
)
MEMBER_GRANTS: frozenset[Action] = frozenset(
    {
        Action.OPPORTUNITY_READ,
        Action.SOURCE_ADD,
        Action.EXTRACTION_START,
        Action.REQUIREMENT_EDIT,
        Action.GAP_DETECTION_START,
        Action.GAP_QUESTION_EDIT,
        Action.ESTIMATE_DRAFT_START,
        Action.ASSUMPTION_ACCEPT,
        Action.RED_TEAM_START,
        Action.ASSESSMENT_START,
        Action.ESTIMATE_EXPORT,
    }
)


def is_allowed(principal: Principal, action: Action, resource: Resource | None = None) -> bool:
    """True if one of the principal's roles grants the action, or the principal is the
    resource's owner or a member and that relation grants it. Relations count only on an
    Opportunity and only for principals holding at least one role (a user whose roles were
    all removed loses access), and not for a principal whose roles are all excluded for the
    action (`RELATION_EXCLUDED_ROLES`). Agent and system actors follow the same rules: with
    no granting role or relation they are denied."""
    if not principal.roles.isdisjoint(POLICY.get(action, frozenset())):
        return True
    if resource is None or resource.type != OPPORTUNITY_RESOURCE or not principal.roles:
        return False
    user_id = principal.user_id
    if user_id is None:
        return False
    if principal.roles <= RELATION_EXCLUDED_ROLES.get(action, frozenset()):
        return False
    if action in OWNER_GRANTS and resource.owner_id is not None and user_id == resource.owner_id:
        return True
    return action in MEMBER_GRANTS and user_id in resource.member_ids
