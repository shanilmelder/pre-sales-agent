"""estimates' public API. Other modules import estimates only from here."""

from uuid import UUID

from app.modules.estimates.application import draft
from app.modules.estimates.application.blockers import (
    get_submission_blockers,
    submission_blocker_counts,
)
from app.modules.estimates.application.compare import compare_versions, version_detail
from app.modules.estimates.application.estimates import (
    accept_all_assumptions,
    accept_assumption,
    create_risk,
    current_estimates,
    edit_assumption,
    edit_line,
    edit_risk,
    get_estimate,
    start_draft,
    submission_blockers_view,
)
from app.modules.estimates.application.export import ExportFile, export_estimate
from app.modules.estimates.application.export_content import ExportFormat
from app.modules.estimates.application.from_assessments import build_from_assessments
from app.modules.estimates.application.line_edits import apply_decision, lock_for_decision
from app.modules.estimates.application.line_refs import (
    LineRef,
    VersionLines,
    current_version_lines,
    version_lines,
)
from app.modules.estimates.application.models import (
    AcceptAllResult,
    Assumption,
    AssumptionChanges,
    AssumptionCounts,
    AssumptionGroups,
    AssumptionLine,
    Blocker,
    CurrentEstimate,
    EstimateDraft,
    EstimateLine,
    EstimateLineChanges,
    EstimateSection,
    EstimateVersion,
    EstimateView,
    LineConflict,
    LineDiff,
    LineRequirement,
    OriginGap,
    Risk,
    RiskChanges,
    RiskCreate,
    RoleHours,
    RoleMix,
    SubmissionBlockers,
    SubmissionBlockersView,
    SubmissionVersion,
    SubmittedVersion,
    Totals,
    UnconvertedGap,
    VersionDiff,
)
from app.modules.estimates.application.review_status import (
    ReviewableVersion,
    current_reviewable_version,
    mark_approved,
    mark_in_review,
    mark_rejected,
    mark_submitted_from_review,
    reviewable_version,
)
from app.modules.estimates.application.review_status import (
    lock_opportunity as lock_for_review,
)
from app.modules.estimates.application.submit import submit_version
from app.modules.estimates.domain.estimates import REVIEWABLE, VersionStatus
from app.modules.estimates.domain.from_assessments import AgentSizing, SizingRow
from app.platform.uow import UnitOfWork


async def enqueue_draft(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a model Estimate draft of the Opportunity in the caller's Unit of Work.
    Coalesces with a draft that is queued and not yet started; returns the draft's id.
    Story 8.3: Gap detection no longer calls it; the Estimate is built from the Assessments
    (`build_from_assessments`)."""
    return await draft.enqueue_draft(uow, opportunity_id)


__all__ = [
    "REVIEWABLE",
    "AcceptAllResult",
    "AgentSizing",
    "Assumption",
    "AssumptionChanges",
    "AssumptionCounts",
    "AssumptionGroups",
    "AssumptionLine",
    "Blocker",
    "CurrentEstimate",
    "EstimateDraft",
    "EstimateLine",
    "EstimateLineChanges",
    "EstimateSection",
    "EstimateVersion",
    "EstimateView",
    "ExportFile",
    "ExportFormat",
    "LineConflict",
    "LineDiff",
    "LineRef",
    "LineRequirement",
    "OriginGap",
    "ReviewableVersion",
    "Risk",
    "RiskChanges",
    "RiskCreate",
    "RoleHours",
    "RoleMix",
    "SizingRow",
    "SubmissionBlockers",
    "SubmissionBlockersView",
    "SubmissionVersion",
    "SubmittedVersion",
    "Totals",
    "UnconvertedGap",
    "VersionDiff",
    "VersionLines",
    "VersionStatus",
    "accept_all_assumptions",
    "accept_assumption",
    "apply_decision",
    "build_from_assessments",
    "compare_versions",
    "create_risk",
    "current_estimates",
    "current_reviewable_version",
    "current_version_lines",
    "edit_assumption",
    "edit_line",
    "edit_risk",
    "enqueue_draft",
    "export_estimate",
    "get_estimate",
    "get_submission_blockers",
    "lock_for_decision",
    "lock_for_review",
    "mark_approved",
    "mark_in_review",
    "mark_rejected",
    "mark_submitted_from_review",
    "reviewable_version",
    "start_draft",
    "submission_blocker_counts",
    "submission_blockers_view",
    "submit_version",
    "version_detail",
    "version_lines",
]
