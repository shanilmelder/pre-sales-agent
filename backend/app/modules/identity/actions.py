"""The action catalogue (AD-15): every authorizable action, in one place.

Names follow `<module>.<entity>.<verb>` and match the command that performs them. The
Agent Registry reuses these names later. Auth0 RBAC permissions use the same names: a token
whose `permissions` claim holds an action's value is granted that action.
"""

import re
from enum import StrEnum

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
    REVIEW_REQUEST_CREATE = "reviews.review_request.create"
    """Story 9.1: send Review Requests for a submitted Estimate Version, and list the
    reviewers who could get one (the owner and collaborators, except sales representatives;
    never a reviewer collaborator)."""
    REVIEW_REQUEST_CANCEL = "reviews.review_request.cancel"
    """Story 9.1: cancel a pending Review Request (its sender or the Opportunity's owner)."""
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
