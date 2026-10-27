"""Authorization policy (AD-15): which permissions, and which relations to a resource, grant
which actions. Pure, no I/O.

Three kinds of grant, any of which allows an action:

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
  Team Review, export the Estimate, edit its lines, resolve or escalate a Conflict,
  resolve a run's decision, resolve or override a Finding, or send or cancel a Review
  Request).
  Story 9.1: a reviewer collaborator (`Resource.reviewer_ids`, granted while one of their
  Review Requests is pending) gets only `REVIEWER_GRANTS`: reading, never a write.
  Roles add up, so someone who also holds a role that isn't excluded keeps the grant.
- **Any-role grants**: `ANY_ROLE_GRANTS` are allowed to every user holding at least one
  role (e.g. searching the Knowledge Base, Story 3.3), with no permission or relation.
  A principal with no role holds none of them.

Story 9.7: `HUMAN_ONLY_ACTIONS` (setting the Baseline) are denied to every principal that isn't
a person, whatever its grants.

Story 10.1: `RELATION_REQUIRED_ROLES` narrows an owner or member grant to principals holding
one of the listed roles (Actuals: delivery managers only). Everyone else who can read the
Opportunity sees Actuals read only.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
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
    reviewer_ids: frozenset[UUID] = frozenset()
    """Story 9.1: users the Opportunity is shared with read only, as reviewers."""


OPPORTUNITY_RESOURCE = "opportunities.opportunity"
"""The resource type the owner/member rules (`OWNER_GRANTS`, `MEMBER_GRANTS`) apply to."""
KNOWLEDGE_SOURCE_RESOURCE = "knowledge.source"
"""The resource type whose owner gets `KNOWLEDGE_SOURCE_OWNER_GRANTS` (Story 3.2)."""

RELATION_EXCLUDED_ROLES: Mapping[Action, frozenset[Role]] = MappingProxyType(
    {
        Action.REQUIREMENT_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_DETECTION_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_QUESTION_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.GAP_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_DRAFT_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSUMPTION_ACCEPT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSUMPTION_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.RISK_CREATE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.RISK_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.RED_TEAM_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ASSESSMENT_START: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_EXPORT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_LINE_EDIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_VERSION_SUBMIT: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CONFLICT_RESOLVE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CONFLICT_ESCALATE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.DECISION_RESOLVE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.FINDING_RESOLVE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.FINDING_OVERRIDE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.REVIEW_REQUEST_CREATE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.REVIEW_REQUEST_CANCEL: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.REVIEW_REQUEST_DECIDE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.REVIEW_REQUEST_REPLY: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_VERSION_CREATE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.ESTIMATE_BASELINE_SET: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CHALLENGE_RAISE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CHALLENGE_CONFIRM: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.CHALLENGE_DECLINE: frozenset({Role.SALES_REPRESENTATIVE}),
        Action.OUTCOME_RECORD: frozenset({Role.SALES_REPRESENTATIVE}),
    }
)
"""Per action, the roles that don't earn its owner or member grant on their own."""

ACTUALS_ACTIONS: frozenset[Action] = frozenset(
    {Action.ACTUAL_RECORD, Action.ACTUAL_CORRECT, Action.DELIVERY_CLOSE, Action.ACTUAL_IMPORT}
)
RELATION_REQUIRED_ROLES: Mapping[Action, frozenset[Role]] = MappingProxyType(
    {action: frozenset({Role.DELIVERY_MANAGER}) for action in ACTUALS_ACTIONS}
)
"""Story 10.1: per action, the roles a principal must hold (one of) to earn its owner or
member grant."""

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
        Action.GAP_EDIT,
        Action.GAP_QUESTION_SEND,
        Action.ESTIMATE_DRAFT_START,
        Action.ASSUMPTION_ACCEPT,
        Action.ASSUMPTION_EDIT,
        Action.RISK_CREATE,
        Action.RISK_EDIT,
        Action.RED_TEAM_START,
        Action.ASSESSMENT_START,
        Action.ESTIMATE_EXPORT,
        Action.ESTIMATE_LINE_EDIT,
        Action.ESTIMATE_VERSION_SUBMIT,
        Action.CONFLICT_RESOLVE,
        Action.CONFLICT_ESCALATE,
        Action.DECISION_RESOLVE,
        Action.FINDING_RESOLVE,
        Action.FINDING_OVERRIDE,
        Action.REVIEW_REQUEST_CREATE,
        Action.REVIEW_REQUEST_CANCEL,
        # Story 9.3: only the request's current reviewer, checked by `reviews` (an owner may
        # be named reviewer when they did not author the version).
        Action.REVIEW_REQUEST_DECIDE,
        # Story 9.4: the owner may reply on any request, and start a new version.
        Action.REVIEW_REQUEST_REPLY,
        Action.ESTIMATE_VERSION_CREATE,
        # Story 9.7: people only (`HUMAN_ONLY_ACTIONS`).
        Action.ESTIMATE_BASELINE_SET,
        # Story 9.5: Challenges; confirming and declining are the owner's alone.
        Action.CHALLENGE_RAISE,
        Action.CHALLENGE_CONFIRM,
        Action.CHALLENGE_DECLINE,
        # Story 10.1: delivery managers only (`RELATION_REQUIRED_ROLES`), people only.
        *ACTUALS_ACTIONS,
        # Story 10.5: closing as lost or marking won is the owner's (and, by permission, a
        # Head of Delivery's); people only. Collaborators may not.
        Action.OUTCOME_RECORD,
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
        Action.GAP_EDIT,
        Action.GAP_QUESTION_SEND,
        Action.ESTIMATE_DRAFT_START,
        Action.ASSUMPTION_ACCEPT,
        Action.ASSUMPTION_EDIT,
        Action.RISK_CREATE,
        Action.RISK_EDIT,
        Action.RED_TEAM_START,
        Action.ASSESSMENT_START,
        Action.ESTIMATE_EXPORT,
        Action.ESTIMATE_LINE_EDIT,
        Action.ESTIMATE_VERSION_SUBMIT,
        Action.CONFLICT_RESOLVE,
        Action.CONFLICT_ESCALATE,
        Action.DECISION_RESOLVE,
        Action.FINDING_RESOLVE,
        Action.REVIEW_REQUEST_CREATE,
        # Only the request's sender, checked by `reviews` (the owner may cancel any).
        Action.REVIEW_REQUEST_CANCEL,
        # Story 9.3: only the request's current reviewer, checked by `reviews`.
        Action.REVIEW_REQUEST_DECIDE,
        # Story 9.4: only the request's sender, checked by `reviews`.
        Action.REVIEW_REQUEST_REPLY,
        Action.ESTIMATE_VERSION_CREATE,
        Action.ESTIMATE_BASELINE_SET,
        *ACTUALS_ACTIONS,
    }
)
REVIEWER_GRANTS: frozenset[Action] = frozenset(
    {Action.OPPORTUNITY_READ, Action.REVIEW_REQUEST_DECIDE, Action.CHALLENGE_RAISE}
)
"""Story 9.1: what a reviewer collaborator may do on the Opportunity: read it, (Story 9.3)
record a decision on their own pending Review Request (`reviews` checks it is theirs) and
(Story 9.5) raise a Challenge while one of their requests is pending (`reviews` checks it),
nothing more."""


KNOWLEDGE_SOURCE_OWNER_GRANTS: frozenset[Action] = frozenset(
    {
        Action.KNOWLEDGE_SOURCE_ADD_VERSION,
        Action.KNOWLEDGE_SOURCE_RETAG,
        Action.KNOWLEDGE_SOURCE_REVIEW,
        Action.KNOWLEDGE_SOURCE_RETIRE,
        Action.KNOWLEDGE_SOURCE_RETRY_PARSE,
        Action.KNOWLEDGE_SOURCE_RETRY_EMBED,
    }
)
"""What the owner of a Knowledge Source may do to it, whatever their role, as long as they
hold one. Registering has no Source yet, so it is granted by role only."""


ANY_ROLE_GRANTS: frozenset[Action] = frozenset(
    {Action.KNOWLEDGE_CHUNK_SEARCH, Action.NOTIFICATION_READ}
)
"""What every principal holding at least one role may do (reads open to all roles; Story
9.2: one's own Inbox, which only ever holds the caller's items)."""


OUTCOME_ACTIONS: frozenset[Action] = frozenset(
    {Action.OUTCOME_RECORD, Action.CONTRACT_END_DATE_UPDATE, Action.OUTCOME_REOPEN}
)
"""Story 10.5: the Opportunity outcome commands."""

HUMAN_ONLY_ACTIONS: frozenset[Action] = frozenset(
    {Action.ESTIMATE_BASELINE_SET, *ACTUALS_ACTIONS, *OUTCOME_ACTIONS}
)
"""Story 9.7 (and 10.1, Actuals; 10.5, the outcome): actions only a person may take. Any
principal that isn't a `user` actor (an agent or the system) is denied them, whatever
permissions or relations it holds."""


def is_allowed(principal: Principal, action: Action, resource: Resource | None = None) -> bool:
    """True if the principal holds the action as a permission, or the principal is the
    resource's owner or a member and that relation grants it. Relations count only on an
    Opportunity (or, for its owner, a Knowledge Source) and only for principals holding at
    least one role (a user whose roles were all removed loses access), and not for a
    principal whose roles are all excluded for the action (`RELATION_EXCLUDED_ROLES`). Agent
    and system actors follow the same rules: with no granting permission or relation they
    are denied; and they are always denied `HUMAN_ONLY_ACTIONS` (Story 9.7)."""
    if action in HUMAN_ONLY_ACTIONS and principal.actor.type != "user":
        return False
    if action in principal.permissions:
        return True
    if action in ANY_ROLE_GRANTS and principal.roles:
        return True
    if resource is None or not principal.roles:
        return False
    user_id = principal.user_id
    if user_id is None:
        return False
    if resource.type == KNOWLEDGE_SOURCE_RESOURCE:
        return (
            action in KNOWLEDGE_SOURCE_OWNER_GRANTS
            and resource.owner_id is not None
            and user_id == resource.owner_id
        )
    if resource.type != OPPORTUNITY_RESOURCE:
        return False
    if principal.roles <= RELATION_EXCLUDED_ROLES.get(action, frozenset()):
        return False
    required = RELATION_REQUIRED_ROLES.get(action)
    if required is not None and not principal.roles & required:
        return False
    if action in OWNER_GRANTS and resource.owner_id is not None and user_id == resource.owner_id:
        return True
    if action in MEMBER_GRANTS and user_id in resource.member_ids:
        return True
    return action in REVIEWER_GRANTS and user_id in resource.reviewer_ids


class OverrideBasis(StrEnum):
    """Why a person may override a Critic or Red Team Finding (Story 6.6, R1)."""

    OWNER = "owner"
    HEAD_OF_DELIVERY = "head_of_delivery"
    SECURITY_REVIEWER = "security_reviewer"


def override_basis(
    principal: Principal, resource: Resource, *, security_discipline: bool
) -> OverrideBasis | None:
    """The grant that lets the principal override a Finding of the Opportunity, or None
    (R1). The Opportunity's owner (not as a sales representative alone) may override any
    overridable Finding; a holder of `assessments.finding.override` may as a Head of Delivery,
    or as a security reviewer only a security-discipline Finding. Collaborators, sales
    representatives and everyone else may not. Whether the Finding is overridable at all
    (its `policy_ref`) is the caller's check, made first."""
    if principal.user_id is None or not principal.roles:
        return None
    if (
        resource.type == OPPORTUNITY_RESOURCE
        and resource.owner_id is not None
        and principal.user_id == resource.owner_id
        and is_allowed(principal, Action.FINDING_OVERRIDE, resource)
    ):
        return OverrideBasis.OWNER
    if Action.FINDING_OVERRIDE not in principal.permissions:
        return None
    if Role.HEAD_OF_DELIVERY in principal.roles:
        return OverrideBasis.HEAD_OF_DELIVERY
    if Role.SECURITY_REVIEWER in principal.roles and security_discipline:
        return OverrideBasis.SECURITY_REVIEWER
    return None
