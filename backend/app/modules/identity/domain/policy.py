"""Authorization policy (AD-15): which permissions, and which relations to a resource, grant
which actions. Pure, no I/O.

Two kinds of grant, either of which allows an action:

- **Permission grants**: Auth0 RBAC assigns permissions to roles, and the access token's
  `permissions` claim carries them. Each permission name equals an `Action` value; holding
  it allows the action on every resource of its kind. Which role holds which permission is
  configured in Auth0 (README "Auth0 setup"), not here.
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
    """identity's actor: a platform `Actor` plus the roles and permissions its access token
    carries. Both are read from the token on every request, so a change in Auth0 takes
    effect when the user's next token is issued."""

    actor: Actor
    roles: frozenset[Role] = frozenset()
    permissions: frozenset[Action] = frozenset()

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
        Action.ESTIMATE_LINE_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
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
        Action.ESTIMATE_LINE_EDIT,
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
        Action.ESTIMATE_LINE_EDIT,
    }
)


def is_allowed(principal: Principal, action: Action, resource: Resource | None = None) -> bool:
    """True if the principal holds the action as a permission, or the principal is the
    resource's owner or a member and that relation grants it. Relations count only on an
    Opportunity and only for principals holding at least one role (a user whose roles were
    all removed loses access), and not for a principal whose roles are all excluded for the
    action (`RELATION_EXCLUDED_ROLES`). Agent and system actors follow the same rules: with
    no granting permission or relation they are denied."""
    if action in principal.permissions:
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
