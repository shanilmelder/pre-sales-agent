// Review Request and review panel fixtures (Stories 9.1 and 9.3). Placeholders only.
import type { Assessment } from "@/lib/assessments";
import type { EstimateVersion } from "@/lib/estimates";
import type { RecordedDecision, ReviewDecision, ReviewPanel, ReviewRequest } from "@/lib/reviews";

export const REVIEW_OPP = "00000000-0000-7000-8000-000000000001";
export const REVIEW_ID = "00000000-0000-7000-8000-0000000000c1";
export const ANA = { id: "00000000-0000-7000-8000-0000000000a1", name: "Ana Reviewer" };
export const CY = { id: "00000000-0000-7000-8000-0000000000a3", name: "Cy Reviewer" };
export const OWNER = { id: "00000000-0000-7000-8000-0000000000f1", name: "Owner Person" };

export function reviewRequest(overrides: Partial<ReviewRequest> = {}): ReviewRequest {
  return {
    id: REVIEW_ID,
    review_type: "engineering",
    target: {
      kind: "estimate_version",
      id: "00000000-0000-7000-8000-0000000000e3",
      version: 3,
      label: "Estimate v3",
    },
    estimate_version_id: "00000000-0000-7000-8000-0000000000e3",
    estimate_version: 3,
    reviewer: ANA,
    requested_by: OWNER,
    message: "Please check the integration hours.",
    status: "pending",
    cancel_reason: null,
    row_version: 1,
    created_at: "2026-10-24T09:00:00Z",
    updated_at: "2026-10-24T09:00:00Z",
    can_cancel: false,
    latest_decision: null,
    ...overrides,
  };
}

export function reviewDecision(overrides: Partial<ReviewDecision> = {}): ReviewDecision {
  return {
    id: "00000000-0000-7000-8000-0000000000d1",
    decision: "evidence_requested",
    label: "Evidence requested",
    reason: "[REASON]",
    decided_by: ANA,
    escalated_to: null,
    target_version: 3,
    decided_at: "2026-10-25T10:02:00Z",
    ...overrides,
  };
}

export function reviewedVersion(overrides: Partial<EstimateVersion> = {}): EstimateVersion {
  const totals = {
    effort_hours: 52,
    contingency_hours: 4,
    total_hours: 56,
    role_hours: { engineer: 40, project_manager: 8, qa: 8 },
  };
  return {
    id: "00000000-0000-7000-8000-0000000000e3",
    version: 3,
    status: "in_review",
    template_version: "demo-1",
    roles: ["engineer", "project_manager", "qa"],
    uncovered_count: 0,
    dropped_count: 0,
    row_version: 2,
    created_at: "2026-10-23T09:00:00Z",
    sections: [
      {
        section: "functional",
        lines: [
          {
            id: "00000000-0000-7000-8000-000000000111",
            position: 1,
            section: "functional",
            title: "[LINE 1]",
            basis: "[BASIS]",
            role_mix: { engineer: 80, project_manager: 10, qa: 10 },
            effort_hours: 52,
            contingency_hours: 4,
            total_hours: 56,
            role_hours: { engineer: 40, project_manager: 8, qa: 8 },
            requirements: [],
            row_version: 1,
            edited: false,
            edited_by_name: null,
            edited_at: null,
            edit_reason: null,
            edit_carried_from_version: null,
            conflicts: [],
          },
        ],
        subtotal: totals,
      },
    ],
    totals,
    proposal_status: "succeeded",
    assumptions: {
      conditions: [],
      contingencies: [
        {
          id: "00000000-0000-7000-8000-0000000000b1",
          position: 1,
          kind: "contingency",
          wording: "[CONTINGENCY]",
          amount_hours: 4,
          line: null,
          origin_kind: "gap",
          origin: {
            id: "00000000-0000-7000-8000-0000000000b2",
            title: "[GAP]",
            category: "integration_details",
            impact: "high",
            why_it_matters: "[WHY]",
            status: "converted",
          },
          origin_superseded: false,
          origin_is_unknown: false,
          accepted_by: null,
          accepted_at: null,
          row_version: 1,
          carried_from_version: null,
        },
      ],
      contingency_hours: 4,
    },
    counts: { total: 1, accepted: 0, not_accepted: 1 },
    unconverted_gaps: [],
    unallocated_contingency_hours: 4,
    risks: [],
    uncarried_edit_count: 0,
    uncarried_edits_from_version: null,
    source: "assessments",
    source_run: 2,
    submitted_at: "2026-10-23T10:00:00Z",
    ...overrides,
  };
}

export function reviewedAssessment(): Assessment {
  return {
    id: "00000000-0000-7000-8000-0000000005a2",
    agent: "security_agent",
    version: 2,
    status: "current",
    run_id: "00000000-0000-7000-8000-000000000099",
    config_version_id: "00000000-0000-7000-8000-0000000000c9",
    recommendation: "proceed",
    confidence: "high",
    confidence_basis: "[BASIS]",
    dropped_count: 0,
    created_at: "2026-10-22T09:00:00Z",
    counts: { critical: 0, high: 1, medium: 0, low: 0 },
    findings: [
      {
        id: "00000000-0000-7000-8000-0000000000f9",
        position: 1,
        kind: "risk",
        severity: "high",
        title: "[FINDING]",
        detail: "[DETAIL]",
        requirements: [
          { id: "00000000-0000-7000-8000-0000000000e9", version: 1, label: "R4", excerpt: "[R4]" },
        ],
        injection_suspected: false,
      },
    ],
    effort: [],
    total_hours: 0,
  };
}

export function reviewPanel(overrides: Partial<ReviewPanel> = {}): ReviewPanel {
  return {
    request: reviewRequest(),
    opportunity_title: "[OPPORTUNITY]",
    decisions: [],
    version_status: "in_review",
    superseded_by: null,
    can_decide: true,
    can_approve: true,
    approve_blocked_reason: null,
    escalation_candidates: [CY],
    estimate: reviewedVersion(),
    diff: {
      version: 3,
      previous_version: 2,
      first: false,
      lines: [
        {
          change: "changed",
          section: "functional",
          title: "[LINE 1]",
          before_hours: 44,
          after_hours: 56,
          delta_hours: 12,
        },
      ],
      total_before: 44,
      total_after: 56,
      total_delta: 12,
    },
    assessment: null,
    ...overrides,
  };
}

export function recorded(
  decision: Partial<ReviewDecision>,
  request: Partial<ReviewRequest>,
  versionStatus = "in_review",
): RecordedDecision {
  const made = reviewDecision(decision);
  return {
    decision: made,
    request: reviewRequest({ row_version: 2, latest_decision: made, ...request }),
    version_status: versionStatus,
  };
}
