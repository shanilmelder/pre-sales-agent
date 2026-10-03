"""opportunities' public API. Other modules import opportunities only from here."""

from app.modules.opportunities.application.models import (
    NewOpportunity,
    Opportunity,
    OpportunityPage,
    OpportunitySummary,
    UserRef,
)
from app.modules.opportunities.application.opportunities import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE,
    MAX_PAGE_SIZE,
    NOT_FOUND_DETAIL,
    add_collaborator,
    create,
    get,
    list_all,
    list_mine,
    remove_collaborator,
)
from app.modules.opportunities.domain.opportunity import OpportunityStatus, derived_status

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE",
    "MAX_PAGE_SIZE",
    "NOT_FOUND_DETAIL",
    "NewOpportunity",
    "Opportunity",
    "OpportunityPage",
    "OpportunityStatus",
    "OpportunitySummary",
    "UserRef",
    "add_collaborator",
    "create",
    "derived_status",
    "get",
    "list_all",
    "list_mine",
    "remove_collaborator",
]
