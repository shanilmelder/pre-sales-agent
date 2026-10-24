"""The action catalogue (AD-15): every authorizable action, in one place.

Names follow `<module>.<entity>.<verb>` and match the command that performs them. The
Agent Registry reuses these names later. Auth0 RBAC permissions use the same names: a token
whose `permissions` claim holds an action's value is granted that action.

Story 7.4: every action has exactly one permission category (`ACTION_CATEGORIES`): `read`,
`write`, `delete`, `send` or `approve`. An Agent may be granted only `read` actions that are
also ToolGateway tools (the registry rejects anything else with
`registry_permission_forbidden_for_agents`).
"""

import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

_SEGMENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
ACTION_NAME_RE = re.compile(rf"^{_SEGMENT}\.{_SEGMENT}\.{_SEGMENT}$")


class Action(StrEnum):
    USER_LIST = "identity.user.list"
    USER_SEARCH = "identity.user.search"
    OPPORTUNITY_CREATE = "opportunities.opportunity.create"
    OPPORTUNITY_READ = "opportunities.opportunity.read"
    OPPORTUNITY_UPDATE = "opportunities.opportunity.update"
    COLLABORATOR_ADD = "opportunities.collaborator.add"
    COLLABORATOR_REMOVE = "opportunities.collaborator.remove"
    SOURCE_ADD = "intake.source.add"
    EXTRACTION_START = "intake.extraction.start"
    REQUIREMENT_EDIT = "intake.requirement.edit"
    GAP_DETECTION_START = "gaps.detection.start"
    GAP_QUESTION_EDIT = "gaps.clarification_question.edit"
    GAP_EDIT = "gaps.gap.edit"
    GAP_QUESTION_SEND = "gaps.clarification_question.send"
    ESTIMATE_DRAFT_START = "estimates.draft.start"
    ASSUMPTION_ACCEPT = "estimates.assumption.accept"
    ASSUMPTION_EDIT = "estimates.assumption.edit"
    RISK_CREATE = "estimates.risk.create"
    RISK_EDIT = "estimates.risk.edit"
    RED_TEAM_START = "assessments.red_team.start"
    ASSESSMENT_START = "assessments.assessment.start"
    ESTIMATE_EXPORT = "estimates.estimate.export"
    CATALOGUE_ENTRY_CREATE = "knowledge.catalogue_entry.create"
    CATALOGUE_ENTRY_EDIT = "knowledge.catalogue_entry.edit"
    CATALOGUE_ENTRY_RETIRE = "knowledge.catalogue_entry.retire"
    CATALOGUE_ENTRY_REACTIVATE = "knowledge.catalogue_entry.reactivate"
    KNOWLEDGE_SOURCE_REGISTER = "knowledge.source.register"
    KNOWLEDGE_SOURCE_ADD_VERSION = "knowledge.source.add_version"
    KNOWLEDGE_SOURCE_RETAG = "knowledge.source.retag"
    KNOWLEDGE_SOURCE_REVIEW = "knowledge.source.review"
    KNOWLEDGE_SOURCE_RETIRE = "knowledge.source.retire"
    KNOWLEDGE_SOURCE_RETRY_PARSE = "knowledge.source.retry_parse"
    KNOWLEDGE_SOURCE_RETRY_EMBED = "knowledge.source.retry_embed"
    KNOWLEDGE_CHUNK_SEARCH = "knowledge.chunk.search"
    KNOWLEDGE_CHECKLIST_CREATE = "knowledge.checklist.create"
    KNOWLEDGE_CHECKLIST_EDIT = "knowledge.checklist.edit"
    KNOWLEDGE_CHECKLIST_PUBLISH = "knowledge.checklist.publish"
    KNOWLEDGE_CHECKLIST_RETIRE = "knowledge.checklist.retire"
    ESTIMATE_LINE_EDIT = "estimates.estimate_line.edit"
    ESTIMATE_VERSION_SUBMIT = "estimates.estimate_version.submit"
    CONFLICT_RESOLVE = "conflicts.conflict.resolve"
    CONFLICT_ESCALATE = "conflicts.conflict.escalate"
    FINDING_RESOLVE = "assessments.finding.resolve"
    """Story 6.6: supply Evidence for, or mark resolved, a Critic or Red Team Finding (the
    `conflicts.conflict.resolve` rules)."""
    FINDING_OVERRIDE = "assessments.finding.override"
    """Story 6.6: override a Critic or Red Team Finding with a reason (R1: the Opportunity's
    owner, a Head of Delivery, or a security reviewer on a security Finding)."""
    REGISTRY_AGENT_REGISTER = "registry.agent.register"
    REGISTRY_AGENT_CONFIG_CREATE = "registry.agent_config.create"
    REGISTRY_AGENT_SET_STATUS = "registry.agent.set_status"
    DECISION_RESOLVE = "workflows.decision.resolve"
    # Story 5.4: the ToolGateway's READ tools (`app.platform.tool_gateway.catalogue`). Agents
    # hold them through their registry `tool_permissions`; no human role is granted them
    # (`KNOWLEDGE_CHUNK_SEARCH` above is also the human Knowledge search, open to all roles).
    TOOL_REQUIREMENT_LIST = "intake.requirement.list"
    TOOL_PASSAGE_READ = "intake.passage.read"
    TOOL_CHUNK_READ = "knowledge.chunk.read"
    TOOL_CATALOGUE_ENTRY_LIST = "knowledge.catalogue_entry.list"
    TOOL_GAP_LIST = "gaps.gap.list"
    TOOL_RESEARCH_PAGE_FETCH = "knowledge.research_page.fetch"
    TOOL_RUN_ASSESSMENT_READ = "assessments.run.read"
    """Story 6.4: the Critic reads its run's accepted Assessments and Findings."""


class PermissionCategory(StrEnum):
    """What an action does (Story 7.4). Agents may only ever hold `read`."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    SEND = "send"
    APPROVE = "approve"


_R, _W, _D, _S, _A = (
    PermissionCategory.READ,
    PermissionCategory.WRITE,
    PermissionCategory.DELETE,
    PermissionCategory.SEND,
    PermissionCategory.APPROVE,
)

ACTION_CATEGORIES: Mapping[Action, PermissionCategory] = MappingProxyType(
    {
        Action.USER_LIST: _R,
        Action.USER_SEARCH: _R,
        Action.OPPORTUNITY_CREATE: _W,
        Action.OPPORTUNITY_READ: _R,
        Action.OPPORTUNITY_UPDATE: _W,
        Action.COLLABORATOR_ADD: _W,
        Action.COLLABORATOR_REMOVE: _D,
        Action.SOURCE_ADD: _W,
        Action.EXTRACTION_START: _W,
        Action.REQUIREMENT_EDIT: _W,
        Action.GAP_DETECTION_START: _W,
        Action.GAP_QUESTION_EDIT: _W,
        Action.GAP_EDIT: _W,
        Action.GAP_QUESTION_SEND: _S,
        Action.ESTIMATE_DRAFT_START: _W,
        Action.ASSUMPTION_ACCEPT: _A,
        Action.ASSUMPTION_EDIT: _W,
        Action.RISK_CREATE: _W,
        Action.RISK_EDIT: _W,
        Action.RED_TEAM_START: _W,
        Action.ASSESSMENT_START: _W,
        Action.ESTIMATE_EXPORT: _R,
        Action.CATALOGUE_ENTRY_CREATE: _W,
        Action.CATALOGUE_ENTRY_EDIT: _W,
        Action.CATALOGUE_ENTRY_RETIRE: _D,
        Action.CATALOGUE_ENTRY_REACTIVATE: _W,
        Action.KNOWLEDGE_SOURCE_REGISTER: _W,
        Action.KNOWLEDGE_SOURCE_ADD_VERSION: _W,
        Action.KNOWLEDGE_SOURCE_RETAG: _W,
        Action.KNOWLEDGE_SOURCE_REVIEW: _A,
        Action.KNOWLEDGE_SOURCE_RETIRE: _D,
        Action.KNOWLEDGE_SOURCE_RETRY_PARSE: _W,
        Action.KNOWLEDGE_SOURCE_RETRY_EMBED: _W,
        Action.KNOWLEDGE_CHUNK_SEARCH: _R,
        Action.KNOWLEDGE_CHECKLIST_CREATE: _W,
        Action.KNOWLEDGE_CHECKLIST_EDIT: _W,
        Action.KNOWLEDGE_CHECKLIST_PUBLISH: _A,
        Action.KNOWLEDGE_CHECKLIST_RETIRE: _D,
        Action.ESTIMATE_LINE_EDIT: _W,
        Action.ESTIMATE_VERSION_SUBMIT: _A,
        Action.CONFLICT_RESOLVE: _W,
        Action.CONFLICT_ESCALATE: _S,
        Action.FINDING_RESOLVE: _W,
        Action.FINDING_OVERRIDE: _A,
        Action.REGISTRY_AGENT_REGISTER: _W,
        Action.REGISTRY_AGENT_CONFIG_CREATE: _W,
        Action.REGISTRY_AGENT_SET_STATUS: _W,
        Action.DECISION_RESOLVE: _A,
        Action.TOOL_REQUIREMENT_LIST: _R,
        Action.TOOL_PASSAGE_READ: _R,
        Action.TOOL_CHUNK_READ: _R,
        Action.TOOL_CATALOGUE_ENTRY_LIST: _R,
        Action.TOOL_GAP_LIST: _R,
        Action.TOOL_RESEARCH_PAGE_FETCH: _R,
        Action.TOOL_RUN_ASSESSMENT_READ: _R,
    }
)
"""One category per action; a test fails when an `Action` has none."""


def action_category(name: str) -> PermissionCategory | None:
    """The category of the action named `name`; None when no action has that name."""
    try:
        return ACTION_CATEGORIES.get(Action(name))
    except ValueError:
        return None
