"""The action catalogue (AD-15): every authorizable action, in one place.

Names follow `<module>.<entity>.<verb>` and match the command that performs them. The
Agent Registry reuses these names later.
"""

import re
from enum import StrEnum

_SEGMENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
ACTION_NAME_RE = re.compile(rf"^{_SEGMENT}\.{_SEGMENT}\.{_SEGMENT}$")


class Action(StrEnum):
    USER_LIST = "identity.user.list"
    USER_ASSIGN_ROLE = "identity.user.assign_role"
    USER_REMOVE_ROLE = "identity.user.remove_role"
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
    ESTIMATE_DRAFT_START = "estimates.draft.start"
    ASSUMPTION_ACCEPT = "estimates.assumption.accept"
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
