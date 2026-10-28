"""estimates' public API. Other modules import estimates only from here. Story 9.4:
`create_version` (a person's **New version** from a rejected or approved version). Story 9.7:
`set_baseline`, `version_approvers` and `list_versions`. Story 9.9: `get_line_lineage`,
`get_assumption_lineage` and `compare_any`. Story 10.1: `current_baseline_ref`, `version_lines`
and `version_assumptions`, for Actuals. Story 10.4: `assumption_details` (a failed Assumption's
number, hours, acceptance and Evidence) and `LineageEvidence`, for the Actuals Inspector."""

from uuid import UUID

from app.modules.estimates.application import draft
from app.modules.estimates.application.baseline import (
    current_baseline_ref,
    set_baseline,
    version_approvers,
    version_gate,
)
from app.modules.estimates.application.blockers import (
    get_submission_blockers,
    submission_blocker_counts,
)
from app.modules.estimates.application.compare import (
    compare_any,
    compare_versions,
    version_detail,
)
from app.modules.estimates.application.estimates import (
    accept_all_assumptions,
    accept_assumption,
    create_risk,
    current_estimates,
    edit_assumption,
    edit_line,
    edit_risk,
    get_estimate,
    list_versions,
    start_draft,
    submission_blockers_view,
)
from app.modules.estimates.application.export import ExportFile, export_estimate
from app.modules.estimates.application.export_content import ExportFormat
from app.modules.estimates.application.from_assessments import build_from_assessments
from app.modules.estimates.application.line_edits import apply_decision, lock_for_decision
from app.modules.estimates.application.line_refs import (
    AssumptionRef,
    LineRef,
    VersionLines,
    current_version_lines,
    version_assumptions,
    version_lines,
)
from app.modules.estimates.application.lineage import (
    AssumptionDetail,
    assumption_details,
    get_assumption_lineage,
    get_line_lineage,
)
from app.modules.estimates.application.models import (
    AcceptAllResult,
    Assumption,
    AssumptionChanges,
    AssumptionCounts,
    AssumptionGroups,
    AssumptionLine,
    AssumptionLineage,
    BaselineApproval,
    BaselineRef,
    BaselineSet,
    Blocker,
    CreatedVersion,
    CurrentEstimate,
    EstimateDraft,
    EstimateLine,
    EstimateLineChanges,
    EstimateSection,
    EstimateVersion,
    EstimateView,
    LineageEvidence,
    LineConflict,
    LineDiff,
    LineLineage,
    LineRequirement,
    NewVersionCreate,
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
    VersionComparison,
    VersionDiff,
    VersionGate,
    VersionListItem,
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
from app.modules.estimates.application.submit import submit_version
from app.modules.estimates.application.versions import create_version
from app.modules.estimates.domain.estimates import DECIDED, REVIEWABLE, VersionStatus
from app.modules.estimates.domain.from_assessments import AgentSizing, SizingRow
from app.platform.uow import UnitOfWork


async def enqueue_draft(uow: UnitOfWork, opportunity_id: UUID) -> UUID:
    """Queue a model Estimate draft of the Opportunity in the caller's Unit of Work.
    Coalesces with a draft that is queued and not yet started; returns the draft's id.
    Story 8.3: Gap detection no longer calls it; the Estimate is built from the Assessments
    (`build_from_assessments`)."""
    return await draft.enqueue_draft(uow, opportunity_id)


__all__ = [
    "DECIDED",
    "REVIEWABLE",
    "AcceptAllResult",
    "AgentSizing",
    "Assumption",
    "AssumptionChanges",
    "AssumptionCounts",
    "AssumptionDetail",
    "AssumptionGroups",
    "AssumptionLine",
    "AssumptionLineage",
    "AssumptionRef",
    "BaselineApproval",
    "BaselineRef",
    "BaselineSet",
    "Blocker",
    "CreatedVersion",
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
    "LineLineage",
    "LineRef",
    "LineRequirement",
    "LineageEvidence",
    "NewVersionCreate",
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
    "VersionComparison",
    "VersionDiff",
    "VersionGate",
    "VersionLines",
    "VersionListItem",
    "VersionStatus",
    "accept_all_assumptions",
    "accept_assumption",
    "apply_decision",
    "assumption_details",
    "build_from_assessments",
    "compare_any",
    "compare_versions",
    "create_risk",
    "create_version",
    "current_baseline_ref",
    "current_estimates",
    "current_reviewable_version",
    "current_version_lines",
    "edit_assumption",
    "edit_line",
    "edit_risk",
    "enqueue_draft",
    "export_estimate",
    "get_assumption_lineage",
    "get_estimate",
    "get_line_lineage",
    "get_submission_blockers",
    "list_versions",
    "lock_for_decision",
    "mark_approved",
    "mark_in_review",
    "mark_rejected",
    "mark_submitted_from_review",
    "reviewable_version",
    "set_baseline",
    "start_draft",
    "submission_blocker_counts",
    "submission_blockers_view",
    "submit_version",
    "version_approvers",
    "version_assumptions",
    "version_detail",
    "version_gate",
    "version_lines",
]
