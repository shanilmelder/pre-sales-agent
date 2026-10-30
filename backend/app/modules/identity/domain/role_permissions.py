"""Which permissions each role holds (Story 1.9).

The single source of truth: `scripts.seed_auth0` writes it to an Auth0 tenant, and the API uses
it to derive permissions from a token's roles when the identity provider (Zitadel, say) has no
RBAC permissions of its own (`PSA_AUTH_PERMISSIONS_FROM_ROLES`).
"""

from collections.abc import Mapping

from app.modules.identity.actions import Action
from app.modules.identity.domain.roles import Role

CHECKLIST_AUTHOR: frozenset[Action] = frozenset(
    {
        Action.KNOWLEDGE_CHECKLIST_CREATE,
        Action.KNOWLEDGE_CHECKLIST_EDIT,
        Action.KNOWLEDGE_CHECKLIST_PUBLISH,
        Action.KNOWLEDGE_CHECKLIST_RETIRE,
    }
)
"""Authoring Checklists (Story 3.4): the engineering, PM and security reviewers and platform
administrators, on every Checklist. Reading them needs only a role."""

EVERY_ROLE: frozenset[Action] = frozenset({Action.NOTIFICATION_READ})
"""Held by every role (Story 9.2: one's own Inbox). The API also grants it to any principal
holding a role (`ANY_ROLE_GRANTS`), so a token issued before a re-seed keeps working."""

_ROLE_PERMISSIONS: Mapping[Role, frozenset[Action]] = {
    Role.PLATFORM_ADMINISTRATOR: frozenset(
        {
            Action.USER_LIST,
            Action.OPPORTUNITY_READ,
            # Writing the Integration Type and Work Package catalogue (Story 3.1): platform
            # administrators only. Reading it needs only a role.
            Action.CATALOGUE_ENTRY_CREATE,
            Action.CATALOGUE_ENTRY_EDIT,
            Action.CATALOGUE_ENTRY_RETIRE,
            Action.CATALOGUE_ENTRY_REACTIVATE,
            # Knowledge Sources (Story 3.2): platform administrators on every Source; a
            # Source's owner gets the actions on it through the relation, not a permission.
            Action.KNOWLEDGE_SOURCE_REGISTER,
            Action.KNOWLEDGE_SOURCE_ADD_VERSION,
            Action.KNOWLEDGE_SOURCE_RETAG,
            Action.KNOWLEDGE_SOURCE_REVIEW,
            Action.KNOWLEDGE_SOURCE_RETIRE,
            Action.KNOWLEDGE_SOURCE_RETRY_PARSE,
            Action.KNOWLEDGE_SOURCE_RETRY_EMBED,
            *CHECKLIST_AUTHOR,
            # The Agent Registry (Story 7.1): platform administrators only.
            Action.REGISTRY_AGENT_REGISTER,
            Action.REGISTRY_AGENT_CONFIG_CREATE,
            Action.REGISTRY_AGENT_SET_STATUS,
            # Reports (Story 10.3): platform administrators and the Head of Delivery only.
            Action.REPORTING_REPORT_READ,
            # The Opportunity outcome (Story 10.5): changing a won Opportunity's contract end
            # date and reopening one, with the Head of Delivery.
            Action.CONTRACT_END_DATE_UPDATE,
            Action.OUTCOME_REOPEN,
        }
    ),
    Role.PRESALES_ENGINEER: frozenset({Action.USER_SEARCH, Action.OPPORTUNITY_CREATE}),
    # Overriding a Critic or Red Team Finding (Story 6.6, R1): a Head of Delivery on any
    # overridable Finding, a security reviewer on a security one only (the policy narrows it).
    # The Opportunity outcome (Story 10.5): a Head of Delivery may record it on any
    # Opportunity (owners get it through the relation), change a won one's contract end date
    # and reopen one.
    Role.HEAD_OF_DELIVERY: frozenset(
        {
            Action.OPPORTUNITY_READ,
            Action.FINDING_OVERRIDE,
            Action.REPORTING_REPORT_READ,
            Action.OUTCOME_RECORD,
            Action.CONTRACT_END_DATE_UPDATE,
            Action.OUTCOME_REOPEN,
        }
    ),
    # Actuals (Story 10.1): delivery managers, on the Opportunities they can read (the API
    # checks read access first, and grants owners and collaborators holding the role too).
    Role.DELIVERY_MANAGER: frozenset(
        {
            Action.ACTUAL_RECORD,
            Action.ACTUAL_CORRECT,
            Action.DELIVERY_CLOSE,
            Action.ACTUAL_IMPORT,
        }
    ),
    Role.ENGINEERING_REVIEWER: CHECKLIST_AUTHOR,
    Role.PM_REVIEWER: CHECKLIST_AUTHOR,
    Role.SECURITY_REVIEWER: CHECKLIST_AUTHOR | {Action.FINDING_OVERRIDE},
}

ROLE_PERMISSIONS: Mapping[Role, frozenset[Action]] = {
    role: _ROLE_PERMISSIONS.get(role, frozenset()) | EVERY_ROLE for role in Role
}
"""Which role holds which permission (README "Auth0 setup"). Beyond `EVERY_ROLE`, roles not
listed above hold none: their access comes from being an Opportunity's owner or
collaborator."""

PERMISSIONS: frozenset[Action] = frozenset().union(*ROLE_PERMISSIONS.values())
