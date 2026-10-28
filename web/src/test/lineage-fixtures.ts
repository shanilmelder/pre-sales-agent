import type {
  AssumptionLineage,
  LineLineage,
  VersionComparison,
} from "@/lib/estimates";

export const LINEAGE_OPP = "00000000-0000-7000-8000-000000000001";
export const LINEAGE_LINE = "00000000-0000-7000-8000-000000000002";
export const REQ_ID = "00000000-0000-7000-8000-0000000000e1";
export const PASSAGE_ID = "00000000-0000-7000-8000-0000000000e9";
const OWNER = { type: "user" as const, id: "00000000-0000-7000-8000-0000000000f1", name: "Owner Person" };

/** A line from an assessment run: R1 cited at v1 (now v2, so superseded), an Engineering
 * Finding and effort entry, a Conflict decision, two edits (the first carried), an approval;
 * no Contingency. */
export function lineLineage(overrides: Partial<LineLineage> = {}): LineLineage {
  const chip = {
    kind: "requirement" as const,
    id: REQ_ID,
    version: 1,
    label: "R1",
    superseded: true,
    passage_id: null,
    excerpt: "[R1 v1 TEXT]",
  };
  return {
    line_id: LINEAGE_LINE,
    title: "[LINE 2]",
    section: "integration",
    version_id: "00000000-0000-7000-8000-0000000000d3",
    version: 3,
    source: "assessments",
    requirements: [
      {
        id: REQ_ID,
        version: 1,
        label: "R1",
        text: "[R1 v1 TEXT]",
        active_version: 2,
        superseded: true,
        evidence: [chip],
      },
    ],
    findings: [
      {
        entry: "finding",
        id: "00000000-0000-7000-8000-0000000000a7",
        agent: "engineering_agent",
        agent_label: "Engineering Agent",
        assessment_id: "00000000-0000-7000-8000-0000000000a6",
        version: 2,
        title: "[FINDING TITLE]",
        detail: "[FINDING DETAIL]",
        severity: "high",
        hours: null,
        status: null,
        created_at: "2026-10-20T09:00:00Z",
        superseded: false,
        evidence: [chip],
      },
      {
        entry: "effort",
        id: "00000000-0000-7000-8000-0000000000a6:R1",
        agent: "engineering_agent",
        agent_label: "Engineering Agent",
        assessment_id: "00000000-0000-7000-8000-0000000000a6",
        version: 2,
        title: "R1 sized at 20 h",
        detail: "[EFFORT BASIS]",
        severity: null,
        hours: 20,
        status: null,
        created_at: "2026-10-20T09:00:00Z",
        superseded: false,
        evidence: [chip],
      },
    ],
    decisions: [
      {
        kind: "conflict_resolved",
        subject_id: "00000000-0000-7000-8000-0000000000c9",
        title: "Conflict resolved: 20 h",
        reason: "[CONFLICT REASON]",
        actor: OWNER,
        at: "2026-10-21T09:00:00Z",
        version: 2,
        superseded: false,
      },
    ],
    assumptions: [],
    edits: [
      {
        line_id: "00000000-0000-7000-8000-0000000000b2",
        version: 2,
        before_hours: 34,
        after_hours: 30,
        reason: "[FIRST EDIT REASON]",
        actor: OWNER,
        at: "2026-10-21T10:00:00Z",
        superseded: true,
      },
      {
        line_id: LINEAGE_LINE,
        version: 3,
        before_hours: 30,
        after_hours: 28,
        reason: "[SECOND EDIT REASON]",
        actor: OWNER,
        at: "2026-10-22T10:00:00Z",
        superseded: false,
      },
    ],
    reviews: [
      {
        kind: "review_decision",
        id: "00000000-0000-7000-8000-0000000000c1",
        label: "Approved",
        target_kind: "estimate_version",
        target_id: "00000000-0000-7000-8000-0000000000d3",
        reason: null,
        actor: { type: "user", id: "00000000-0000-7000-8000-0000000000a1", name: "Ana Reviewer" },
        at: "2026-10-23T09:00:00Z",
        version: 3,
        superseded: false,
      },
    ],
    ...overrides,
  };
}

/** An accepted 8 h Contingency linked to the line. */
export function lineContingency(): LineLineage["assumptions"][number] {
  return {
    id: "00000000-0000-7000-8000-0000000000ac",
    position: 2,
    wording: "[CONTINGENCY WORDING]",
    amount_hours: 8,
    accepted_by_name: "Owner Person",
    accepted_at: "2026-10-20T09:00:00Z",
    version: 3,
    superseded: false,
  };
}

/** An Assumption converted from an answered Gap and accepted. */
export function assumptionLineage(overrides: Partial<AssumptionLineage> = {}): AssumptionLineage {
  return {
    assumption_id: "00000000-0000-7000-8000-0000000000aa",
    version_id: "00000000-0000-7000-8000-0000000000d3",
    version: 3,
    kind: "condition",
    position: 2,
    wording: "[WORDING]",
    steps: [
      {
        kind: "gap",
        id: "00000000-0000-7000-8000-0000000000e0",
        title: "[GAP TITLE]",
        detail: "[WHY IT MATTERS]",
        actor: { type: "agent", id: "clarification_agent@1.0.0", name: "Clarification Agent", version: "1.0.0" },
        at: "2026-10-18T09:00:00Z",
        version: 1,
        superseded: false,
        evidence: [],
        passage: null,
      },
      {
        kind: "question",
        id: "00000000-0000-7000-8000-0000000000e2",
        title: "[QUESTION TEXT]",
        detail: "answered",
        actor: OWNER,
        at: "2026-10-18T10:00:00Z",
        version: 3,
        superseded: false,
        evidence: [],
        passage: null,
      },
      {
        kind: "answer",
        id: PASSAGE_ID,
        title: "S2 · answer.txt",
        detail: "Answered on 2026-10-19",
        actor: OWNER,
        at: null,
        version: 1,
        superseded: false,
        evidence: [
          {
            kind: "source_document",
            id: "00000000-0000-7000-8000-0000000000e8",
            version: 1,
            label: "S2 · answer.txt",
            superseded: false,
            passage_id: PASSAGE_ID,
            excerpt: "[ANSWER EXCERPT]",
          },
        ],
        passage: {
          passage_id: PASSAGE_ID,
          source_id: "00000000-0000-7000-8000-0000000000e8",
          source_version: 1,
          filename: "answer.txt",
          label: "S2 · answer.txt",
          excerpt: "[ANSWER EXCERPT]",
        },
      },
      {
        kind: "conversion",
        id: "00000000-0000-7000-8000-0000000000e3",
        title: "Converted to a Condition",
        detail: null,
        actor: OWNER,
        at: "2026-10-20T09:00:00Z",
        version: 2,
        superseded: false,
        evidence: [],
        passage: null,
      },
      {
        kind: "acceptance",
        id: "00000000-0000-7000-8000-0000000000aa",
        title: "Accepted",
        detail: null,
        actor: OWNER,
        at: "2026-10-20T09:00:00Z",
        version: 3,
        superseded: false,
        evidence: [],
        passage: null,
      },
    ],
    ...overrides,
  };
}

/** Story 10.4: an `actual` step, a delivery manager's final Actual naming the Assumption as
 * failed. */
export function actualStep(
  overrides: Partial<AssumptionLineage["steps"][number]> = {},
): AssumptionLineage["steps"][number] {
  return {
    kind: "actual",
    id: "00000000-0000-7000-8000-0000000000c9",
    title: "L2 · Final Actual · 48.0 h",
    detail: "Integration complexity",
    actor: { type: "user", id: "00000000-0000-7000-8000-0000000000u9", name: "Dana Delivery" },
    at: "2026-10-26T09:00:00Z",
    version: 1,
    superseded: false,
    evidence: [],
    passage: null,
    actual: {
      actual_id: "00000000-0000-7000-8000-0000000000c9",
      version: 1,
      corrected: false,
      line_id: "00000000-0000-7000-8000-0000000000d2",
      line_label: "L2",
      line_title: "[LINE 2]",
      kind: "final",
      effort_hours: 48,
      variance_cause: "integration_complexity",
      cause_label: "Integration complexity",
    },
    ...overrides,
  };
}

/** v3 against v2: [LINE 2] down 4 h, [LINE 3] added, [OLD LINE] removed; an Assumption
 * reworded, a Risk added; one line edit and a version created in between. */
export function comparison(overrides: Partial<VersionComparison> = {}): VersionComparison {
  return {
    from_version: 2,
    from_version_id: "00000000-0000-7000-8000-0000000000d2",
    to_version: 3,
    to_version_id: "00000000-0000-7000-8000-0000000000d3",
    lines: [
      {
        change: "removed",
        section: "functional",
        title: "[OLD LINE]",
        before_hours: 5,
        after_hours: null,
        delta_hours: -5,
      },
      {
        change: "changed",
        section: "integration",
        title: "[LINE 2]",
        before_hours: 14,
        after_hours: 10,
        delta_hours: -4,
      },
      {
        change: "added",
        section: "integration",
        title: "[LINE 3]",
        before_hours: null,
        after_hours: 6.5,
        delta_hours: 6.5,
      },
    ],
    total_before: 43.5,
    total_after: 41,
    total_delta: -2.5,
    assumptions: [
      {
        change: "changed",
        id: "00000000-0000-7000-8000-0000000000aa",
        text: "[NEW WORDING]",
        before: "Condition · [OLD WORDING]",
        after: "Condition · [NEW WORDING]",
      },
    ],
    risks: [
      {
        change: "added",
        id: "00000000-0000-7000-8000-0000000000ab",
        text: "[RISK]",
        before: null,
        after: "medium likelihood · medium impact · [RISK]",
      },
    ],
    why: [
      {
        id: "00000000-0000-7000-8000-0000000000f7",
        event_type: "estimates.estimate_line.edited",
        label: "Estimate line edited",
        actor: OWNER,
        occurred_at: "2026-10-22T10:00:00Z",
        reason: "[WHY REASON]",
        subject: { type: "estimates.estimate_line", id: LINEAGE_LINE, version: 2 },
      },
      {
        id: "00000000-0000-7000-8000-0000000000f8",
        event_type: "estimates.estimate_version.created",
        label: "Estimate version created",
        actor: { type: "system", id: "estimates.build_from_assessments", name: "System" },
        occurred_at: "2026-10-23T10:00:00Z",
        reason: null,
        subject: { type: "estimates.estimate_version", id: "00000000-0000-7000-8000-0000000000d3", version: 1 },
      },
    ],
    ...overrides,
  };
}
