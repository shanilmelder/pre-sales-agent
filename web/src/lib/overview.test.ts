import { describe, expect, it } from "vitest";

import type { AssessmentsView } from "./assessments";
import type { ConflictsView } from "./conflicts";
import type { Assumption, EstimateView } from "./estimates";
import type { Gap, GapList } from "./gaps";
import {
  actorInitials,
  attentionIncomplete,
  attentionItems,
  awaitingLabel,
  conflictCounts,
  conflictsBlockSubmit,
  couldNotLoad,
  cutAttention,
  dueLabel,
  estimateKpiLabel,
  estimatePending,
  gapCounts,
  impactLabel,
  isStepStatus,
  itemCountLabel,
  latestDecision,
  moreLabel,
  parsedLabel,
  pipelineProgress,
  pipelineSteps,
  requirementCounts,
  roleHoursLabel,
  sourceCounts,
  sourceRunLabel,
  stepsBlockedLabel,
  stepsCompleteLabel,
  tasksCompleteLabel,
  unacceptedAssumptions,
  waitingRunItems,
  type OverviewReads,
} from "./overview";
import type { RedTeamView } from "./red-team";
import type { Requirement, RequirementList } from "./requirements";
import type { Source } from "./sources";
import type { Blocker, SubmissionBlockersView } from "./submission";

let n = 0;
const uid = () => `00000000-0000-7000-8000-${String(++n).padStart(12, "0")}`;

function finding(
  severity: "critical" | "high" | "medium" | "low",
  title: string,
) {
  return { id: uid(), position: 1, severity, title } as never;
}

function redTeam(findings: unknown[]): RedTeamView {
  return {
    review: { findings, counts: { critical: 0, high: 0, medium: 0, low: 0 } },
    run: null,
    can_start: false,
  } as unknown as RedTeamView;
}

function assessments(
  security: unknown[] = [],
  engineering: unknown[] = [],
): AssessmentsView {
  return {
    run: null,
    can_start: false,
    assessments: [
      { agent: "engineering_agent", assessment: { findings: engineering } },
      { agent: "pm_agent", assessment: null },
      { agent: "security_agent", assessment: { findings: security } },
    ],
  } as unknown as AssessmentsView;
}

function gap(
  title: string,
  impact: "high" | "medium" | "low",
  status = "open",
): Gap {
  return { id: uid(), title, impact, status } as unknown as Gap;
}

function gaps(
  items: Gap[],
  detection: GapList["detection"] = { status: "succeeded", error_code: null },
) {
  return {
    items,
    detection,
    can_start_detection: false,
    can_edit_questions: false,
  } as GapList;
}

function assumption(
  wording: string,
  amount: number | null,
  accepted = false,
): Assumption {
  return {
    id: uid(),
    wording,
    amount_hours: amount,
    accepted_at: accepted ? "2026-10-05T09:00:00Z" : null,
  } as unknown as Assumption;
}

function estimate(
  conditions: Assumption[],
  contingencies: Assumption[] = [],
): EstimateView {
  return {
    version: {
      assumptions: { conditions, contingencies, contingency_hours: 0 },
    },
  } as unknown as EstimateView;
}

describe("escalated Conflicts (Story 6.3)", () => {
  it("lists each escalated Conflict naming the reviewer, linking to the Conflicts tab", () => {
    const conflicts = {
      conflicts: [
        {
          id: "c1",
          type: "effort",
          status: "escalated",
          requirement: { label: "R2" },
          escalated_to: { id: "u1", name: "Sam" },
        },
        { id: "c2", type: "scope", status: "open", requirement: null, escalated_to: null },
        {
          id: "c3",
          type: "assumption",
          status: "escalated",
          requirement: null,
          escalated_to: { id: "u2", name: "Kim" },
        },
      ],
      open_count: 3,
      reviewers: [],
    } as unknown as ConflictsView;
    const items = attentionItems({
      redTeam: redTeam([finding("critical", "ERP fields"), finding("high", "No SSO")]),
      assessments: null,
      gaps: null,
      estimate: null,
      conflicts,
    });
    expect(items.map((i) => [i.kind, i.label, i.tab])).toEqual([
      ["critical-finding", "Red Team: ERP fields", "assessments"],
      ["high-finding", "Red Team: No SSO", "assessments"],
      ["escalated-conflict", "Effort Conflict on R2 escalated to Sam", "conflicts"],
      ["escalated-conflict", "Assumption Conflict escalated to Kim", "conflicts"],
    ]);
  });
});

describe("attentionItems", () => {
  it("is empty when nothing needs attention or every read failed", () => {
    expect(
      attentionItems({
        redTeam: null,
        assessments: null,
        gaps: null,
        estimate: null,
      }),
    ).toEqual([]);
    expect(
      attentionItems({
        redTeam: { review: null, run: null, can_start: false, blocking_count: 0 },
        assessments: assessments([finding("medium", "M")]),
        gaps: gaps([gap("Low", "low"), gap("Done", "high", "converted")]),
        estimate: estimate([assumption("Accepted", 8, true)]),
      }),
    ).toEqual([]);
  });

  it("ranks critical first, then high Findings and Gaps, then Assumptions, naming each source", () => {
    const items = attentionItems({
      redTeam: redTeam([
        finding("critical", "ERP fields"),
        finding("low", "Ignored"),
      ]),
      assessments: assessments([finding("high", "No SSO")]),
      gaps: gaps([
        gap("Volumes", "high"),
        gap("Versions", "high"),
        gap("Meh", "medium"),
      ]),
      estimate: estimate(
        [assumption("ERP mapping", 80)],
        [assumption("Customer hosts", null)],
      ),
    });
    expect(items.map((i) => [i.label, i.tab])).toEqual([
      ["Red Team: ERP fields", "assessments"],
      ["Security Agent: No SSO", "assessments"],
      ["Open Gap: Volumes", "gaps"],
      ["Open Gap: Versions", "gaps"],
      ["Unaccepted Assumption: ERP mapping — 80.0 h", "estimate"],
      ["Unaccepted Assumption: Customer hosts", "estimate"],
    ]);
    expect(items.map((i) => i.kind)).toEqual([
      "critical-finding",
      "high-finding",
      "gap",
      "gap",
      "assumption",
      "assumption",
    ]);
  });

  it("puts a critical specialist Finding ahead of a high Red Team one", () => {
    const items = attentionItems({
      redTeam: redTeam([finding("high", "RT high")]),
      assessments: assessments([], [finding("critical", "Eng critical")]),
      gaps: null,
      estimate: null,
    });
    expect(items.map((i) => i.label)).toEqual([
      "Engineering Agent: Eng critical",
      "Red Team: RT high",
    ]);
  });
});

describe("cutAttention", () => {
  it("keeps 8 and says how many more, linking to the tab when every cut item is on it", () => {
    const items = attentionItems({
      redTeam: null,
      assessments: null,
      gaps: gaps(Array.from({ length: 12 }, (_, i) => gap(`G${i}`, "high"))),
      estimate: null,
    });
    expect(cutAttention(items)).toMatchObject({ more: 4, moreTab: "gaps" });
  });

  it("keeps 8 and gives no tab when the cut items span several tabs", () => {
    const items = attentionItems({
      redTeam: null,
      assessments: null,
      gaps: gaps(Array.from({ length: 9 }, (_, i) => gap(`G${i}`, "high"))),
      estimate: estimate([
        assumption("A", 1),
        assumption("B", 2),
        assumption("C", 3),
      ]),
    });
    const cut = cutAttention(items);
    expect(cut.shown).toHaveLength(8);
    expect(cut.more).toBe(4);
    expect(cut.moreTab).toBeNull();
    expect(moreLabel(cut.more)).toBe("+4 more");
    expect(cutAttention(items.slice(0, 3))).toMatchObject({
      more: 0,
      moreTab: null,
    });
  });
});

describe("unacceptedAssumptions", () => {
  it("takes Conditions and Contingencies not yet accepted", () => {
    const view = estimate(
      [assumption("A", 1, true), assumption("B", null)],
      [assumption("C", 4)],
    );
    expect(unacceptedAssumptions(view).map((a) => a.wording)).toEqual([
      "B",
      "C",
    ]);
    expect(unacceptedAssumptions({ version: null } as EstimateView)).toEqual(
      [],
    );
    expect(unacceptedAssumptions(null)).toEqual([]);
  });
});

describe("pipeline counts", () => {
  it("counts parsed Sources of total, null before any", () => {
    const source = (status: string | null) =>
      ({
        id: uid(),
        parse: status ? { status, error_code: null } : null,
      }) as unknown as Source;
    expect(sourceCounts([])).toBeNull();
    const counts = sourceCounts([
      source("parsed"),
      source("parsing"),
      source(null),
      source("parsed"),
    ]);
    expect(counts).toEqual({ parsed: 2, failed: 0, total: 4 });
    expect(parsedLabel(counts!)).toBe("2 of 4 parsed");
    const withFailed = sourceCounts([
      source("parsed"),
      source("parsed"),
      source("failed"),
    ]);
    expect(withFailed).toEqual({ parsed: 2, failed: 1, total: 3 });
    expect(parsedLabel(withFailed!)).toBe("2 of 3 parsed, 1 failed");
  });

  it("counts active and confirmed Requirements, null before an extraction", () => {
    const req = (confirmed: boolean) =>
      ({
        id: uid(),
        confirmed_at: confirmed ? "2026-10-05T09:00:00Z" : null,
      }) as unknown as Requirement;
    const list = (
      items: Requirement[],
      extraction: RequirementList["extraction"],
    ) =>
      ({
        items,
        extraction,
        can_start_extraction: false,
        can_edit_requirements: false,
      }) as RequirementList;
    expect(requirementCounts(list([], null))).toBeNull();
    expect(
      requirementCounts(
        list([], { status: "succeeded", error_code: null, source_count: 1 }),
      ),
    ).toEqual({ active: 0, confirmed: 0, unconfirmed: 0 });
    expect(
      requirementCounts(
        list([req(true), req(false), req(true)], {
          status: "succeeded",
          error_code: null,
          source_count: 1,
        }),
      ),
    ).toEqual({ active: 3, confirmed: 2, unconfirmed: 1 });
    expect(awaitingLabel(1)).toBe("1 awaiting confirmation");
  });

  it("shows the extraction's status, not 0, while the first one runs or after it failed", () => {
    const list = (
      items: Requirement[],
      status: "queued" | "running" | "succeeded" | "failed",
    ) =>
      ({
        items,
        extraction: { status, error_code: null, source_count: 1 },
        can_start_extraction: false,
        can_edit_requirements: false,
      }) as RequirementList;
    expect(requirementCounts(list([], "queued"))).toEqual({
      status: "Extracting…",
    });
    expect(requirementCounts(list([], "running"))).toEqual({
      status: "Extracting…",
    });
    expect(requirementCounts(list([], "failed"))).toEqual({ status: "Failed" });
    const req = { id: uid(), classification: "data" } as unknown as Requirement;
    // A re-run with Requirements already there keeps the counts.
    expect(requirementCounts(list([req], "running"))).toMatchObject({
      active: 1,
    });
    expect(isStepStatus({ status: "Failed" })).toBe(true);
    expect(isStepStatus({ active: 0, confirmed: 0, unconfirmed: 0 })).toBe(false);
  });

  it("counts open Gaps by impact, null before a detection", () => {
    expect(gapCounts(gaps([], null))).toBeNull();
    const counts = gapCounts(
      gaps([
        gap("a", "high"),
        gap("b", "low"),
        gap("m", "medium"),
        gap("c", "high", "superseded"),
      ]),
    );
    expect(counts).toEqual({ open: 3, high: 1, medium: 1, low: 1 });
    expect(impactLabel({ high: 2, medium: 1, low: 0 })).toBe("2 High, 1 Medium, 0 Low");
  });

  it("shows the detection's status, not 0, while the first one runs or after it failed", () => {
    expect(gapCounts(gaps([], { status: "queued", error_code: null }))).toEqual(
      {
        status: "Detecting…",
      },
    );
    expect(
      gapCounts(gaps([], { status: "running", error_code: null })),
    ).toEqual({
      status: "Detecting…",
    });
    expect(gapCounts(gaps([], { status: "failed", error_code: null }))).toEqual(
      { status: "Failed" },
    );
    expect(
      gapCounts(gaps([], { status: "succeeded", error_code: null })),
    ).toEqual({ open: 0, high: 0, medium: 0, low: 0 });
    expect(
      gapCounts(
        gaps([gap("a", "high")], { status: "running", error_code: null }),
      ),
    ).toEqual({ open: 1, high: 1, medium: 0, low: 0 });
  });
});

describe("labels", () => {
  it("names counts, failures and the Estimate tile", () => {
    expect(itemCountLabel(1)).toBe("1 item");
    expect(itemCountLabel(5)).toBe("5 items");
    expect(couldNotLoad("The Estimate")).toBe(
      "The Estimate could not be loaded. Try again in a moment.",
    );
    expect(roleHoursLabel({ engineer: 225.4, project_manager: 52.6, qa: 0 })).toBe(
      "Engineer 225.4 h · PM 52.6 h",
    );
    expect(roleHoursLabel({ engineer: 10, project_manager: 5, qa: 2 })).toBe(
      "Engineer 10.0 h · PM 5.0 h · QA 2.0 h",
    );
    expect(sourceRunLabel(2)).toBe("From Assessments run 2");
    expect(estimateKpiLabel({ version: 3, status: "draft" })).toBe("Estimate · v3 draft");
    expect(estimateKpiLabel({ version: 3, status: "submitted" })).toBe("Estimate · v3 submitted");
    expect(estimateKpiLabel({ version: 3, status: "in_review" })).toBe("Estimate · v3 in review");
    expect(estimateKpiLabel({ version: 2, status: "superseded" })).toBe(
      "Estimate · v2 superseded",
    );
    expect(estimateKpiLabel(null)).toBe("Estimate");
    expect(
      estimatePending({ version: null, draft: { status: "running" } } as unknown as EstimateView),
    ).toBe("Drafting Estimate");
    expect(estimatePending({ version: null, draft: null } as unknown as EstimateView)).toBe(
      "No Estimate yet.",
    );
    expect(tasksCompleteLabel(1, 3)).toBe("1 of 3 tasks complete");
    expect(actorInitials("Sam Delivery")).toBe("SD");
    expect(actorInitials("Red Team Agent")).toBe("RA");
    expect(actorInitials("system")).toBe("S");
    expect(actorInitials("  ")).toBe("?");
  });

  it("counts the proposal due date in days, overdue in the past", () => {
    expect(dueLabel(11)).toEqual({ text: "Proposal due in 11 days", overdue: false });
    expect(dueLabel(1)).toEqual({ text: "Proposal due in 1 day", overdue: false });
    expect(dueLabel(0)).toEqual({ text: "Proposal due today", overdue: false });
    expect(dueLabel(-3)).toEqual({ text: "Overdue by 3 days", overdue: true });
    expect(dueLabel(Number.NaN)).toBeNull();
  });
});

const EMPTY: OverviewReads = {
  sources: [],
  requirements: {
    items: [],
    extraction: null,
    can_start_extraction: false,
    can_edit_requirements: false,
  } as unknown as RequirementList,
  gaps: gaps([], null),
  estimate: { version: null, draft: null } as unknown as EstimateView,
  assessments: {
    run: null,
    can_start: false,
    assessments: [{ agent: "engineering_agent", assessment: null }],
  } as unknown as AssessmentsView,
  redTeam: { review: null, run: null, can_start: false, blocking_count: 0 },
  trace: [],
  conflicts: { conflicts: [], open_count: 0, reviewers: [] },
};

function conflictsOf(...statuses: string[]): ConflictsView {
  return {
    conflicts: statuses.map((status) => ({ id: uid(), status })),
    open_count: 0,
    reviewers: [],
  } as unknown as ConflictsView;
}

function midWay(): OverviewReads {
  const source = { id: uid(), parse: { status: "parsed", error_code: null } } as unknown as Source;
  const req = (confirmed: boolean) =>
    ({
      id: uid(),
      confirmed_at: confirmed ? "2026-10-05T09:00:00Z" : null,
    }) as unknown as Requirement;
  return {
    ...EMPTY,
    sources: Array.from({ length: 6 }, () => source),
    requirements: {
      items: [...Array.from({ length: 9 }, () => req(true)), req(false), req(false), req(false)],
      extraction: { status: "succeeded", error_code: null, source_count: 6 },
    } as unknown as RequirementList,
    gaps: gaps([gap("a", "high"), gap("b", "high"), gap("c", "medium")]),
    assessments: {
      ...EMPTY.assessments,
      run: { status: "running", tasks: [] },
    } as unknown as AssessmentsView,
    conflicts: conflictsOf("open", "escalated", "resolved"),
    estimate: {
      version: {
        version: 3,
        uncovered_count: 1,
        counts: { total: 3, accepted: 1, not_accepted: 2 },
        assumptions: { conditions: [], contingencies: [] },
      },
      draft: null,
    } as unknown as EstimateView,
  };
}

type Kind = Blocker["kind"];

function blocker(kind: Kind): Blocker {
  const id = uid();
  return { kind, subject_id: id, title: `${kind} ${id}`, detail: "", href: `/x#${kind}-${id}` };
}

function blockersView(
  kinds: Kind[],
  {
    status = "draft",
    noVersion = false,
    toBaseline = [],
  }: {
    status?: NonNullable<SubmissionBlockersView["version"]>["status"];
    noVersion?: boolean;
    toBaseline?: Blocker[];
  } = {},
): SubmissionBlockersView {
  return {
    to_submit: kinds.map(blocker),
    to_baseline: toBaseline,
    version: noVersion
      ? null
      : {
          id: uid(),
          version: 3,
          status,
          row_version: 1,
          created_at: "2026-10-04T10:00:00Z",
          submitted_at: status === "draft" ? null : "2026-10-14T09:00:00Z",
        },
    can_submit: true,
    is_baseline: false,
    can_set_baseline: false,
  };
}

/** The mockup: 3 Gap, 2 Conflict and 2 Assumption blockers, a cancelled run, a draft. */
const MOCKUP_BLOCKERS: Kind[] = [
  "gap",
  "gap",
  "gap",
  "conflict",
  "conflict",
  "assumption",
  "assumption",
];

function mockup(): OverviewReads {
  return {
    ...midWay(),
    assessments: {
      ...EMPTY.assessments,
      run: { status: "cancelled", tasks: [] },
    } as unknown as AssessmentsView,
  };
}

const acceptedEstimate = {
  version: {
    version: 3,
    uncovered_count: 0,
    counts: { total: 1, accepted: 1, not_accepted: 0 },
  },
  draft: null,
} as unknown as EstimateView;

describe("pipelineSteps (Story 8.9)", () => {
  it("a new Opportunity has eight pending steps, each with its tab", () => {
    const steps = pipelineSteps(EMPTY, blockersView([], { noVersion: true }));
    expect(steps.map((s) => [s.title, s.tab])).toEqual([
      ["Sources added", "sources"],
      ["Requirements extracted", "requirements"],
      ["Requirements confirmed", "requirements"],
      ["Gaps answered", "gaps"],
      ["Assessments run", "assessments"],
      ["Conflicts resolved", "conflicts"],
      ["Estimate accepted", "estimate"],
      ["Review and Baseline", "estimate"],
    ]);
    expect(steps.every((s) => s.state === "pending")).toBe(true);
    expect(steps[7].sub).toBe("Starts when blockers clear");
    expect(pipelineProgress(steps)).toEqual({ done: 0, inProgress: 0, blocked: 0, total: 8 });
  });

  it("the mockup: Blocked exactly where the view has items, a cancelled run in progress", () => {
    const steps = pipelineSteps(mockup(), blockersView(MOCKUP_BLOCKERS));
    expect(steps.map((s) => [s.state, s.sub])).toEqual([
      ["complete", "6 of 6 parsed"],
      ["complete", "12 Requirements"],
      ["in-progress", "9 of 12"],
      ["blocked", "3 open, 2 High"],
      ["in-progress", "Cancelled — completed results kept"],
      ["blocked", "2 open"],
      ["blocked", "2 Assumptions not accepted"],
      ["pending", "Starts when blockers clear"],
    ]);
    const progress = pipelineProgress(steps);
    expect(progress).toEqual({ done: 2, inProgress: 2, blocked: 3, total: 8 });
    expect(stepsCompleteLabel(progress.done, progress.total)).toBe("2 of 8 steps complete");
    expect(stepsBlockedLabel(progress.blocked)).toBe("3 steps blocked");
    expect(stepsBlockedLabel(1)).toBe("1 step blocked");
  });

  it("open Gaps without gap blocker items are not Blocked (the view decides)", () => {
    const steps = pipelineSteps(mockup(), blockersView(["conflict"]));
    expect(steps[3]).toMatchObject({ state: "complete", sub: "No Gaps block submission" });
    expect(steps.filter((s) => s.state === "blocked").map((s) => s.key)).toEqual(["conflicts"]);
  });

  it("live clear: no conflict items completes the step even while the read is stale", () => {
    const data = { ...mockup(), conflicts: conflictsOf("open") };
    expect(pipelineSteps(data, blockersView(["conflict"]))[5].state).toBe("blocked");
    expect(pipelineSteps(data, blockersView([]))[5]).toMatchObject({
      state: "complete",
      sub: "No Conflicts block submission",
    });
  });

  it("critical Findings block Assessments run; uncovered Requirements block the Estimate", () => {
    const steps = pipelineSteps(
      { ...mockup(), estimate: acceptedEstimate },
      blockersView(["finding", "finding", "uncovered_requirement"]),
    );
    expect(steps[4]).toMatchObject({ state: "blocked", sub: "2 critical Findings" });
    expect(steps[6]).toMatchObject({ state: "blocked", sub: "1 Requirement not covered" });
    // Assumptions come first in the Estimate step's sub-line.
    const both = pipelineSteps(mockup(), blockersView(["uncovered_requirement", "assumption"]));
    expect(both[6]).toMatchObject({ state: "blocked", sub: "1 Assumption not accepted" });
  });

  it("Requirements confirmed is never Blocked", () => {
    const kinds: Kind[] = ["gap", "assumption", "conflict", "finding", "uncovered_requirement"];
    const steps = pipelineSteps(mockup(), blockersView(kinds));
    expect(steps[2].state).toBe("in-progress");
  });

  it("ready: steps 4–7 Complete and Review waits for the submission", () => {
    const data: OverviewReads = {
      ...mockup(),
      gaps: gaps([gap("a", "high", "converted")]),
      assessments: {
        ...EMPTY.assessments,
        run: { status: "succeeded", tasks: [] },
      } as unknown as AssessmentsView,
      conflicts: conflictsOf("resolved"),
      estimate: acceptedEstimate,
    };
    const steps = pipelineSteps(data, blockersView([]));
    expect(steps.slice(3, 7).map((s) => s.state)).toEqual([
      "complete",
      "complete",
      "complete",
      "complete",
    ]);
    expect(steps[3].sub).toBe("No open Gaps");
    expect(steps[5].sub).toBe("No open Conflicts");
    expect(steps[6].sub).toBe("Estimate v3, every Assumption accepted");
    expect(steps[7]).toMatchObject({ state: "pending", sub: "Starts after you submit" });
  });

  it("Review and Baseline: submitted, in review, and never Complete", () => {
    const submitted = pipelineSteps(mockup(), blockersView([], { status: "submitted" }));
    expect(submitted[7]).toMatchObject({ state: "pending", sub: "No Review Request sent yet" });
    const requests = [blocker("review_request"), blocker("review_request")];
    const inReview = pipelineSteps(
      mockup(),
      blockersView([], { status: "in_review", toBaseline: requests }),
    );
    expect(inReview[7]).toMatchObject({ state: "in-progress", sub: "2 Review Requests pending" });
    const pendingOnly = pipelineSteps(
      mockup(),
      blockersView([], { status: "submitted", toBaseline: [requests[0]!] }),
    );
    expect(pendingOnly[7]).toMatchObject({ state: "in-progress", sub: "1 Review Request pending" });
    const noRequests = pipelineSteps(mockup(), blockersView([], { status: "in_review" }));
    expect(noRequests[7]).toMatchObject({ state: "in-progress", sub: "In review" });
    const approved = pipelineSteps(mockup(), blockersView([], { status: "approved" }));
    expect(approved[7]).toMatchObject({
      state: "in-progress",
      sub: "Approved, Baseline not set yet",
    });
    const rejected = pipelineSteps(
      mockup(),
      blockersView([], { status: "rejected", toBaseline: [requests[0]!] }),
    );
    expect(rejected[7]).toMatchObject({ state: "in-progress", sub: "Rejected in review" });
    const all = [submitted, inReview, pendingOnly, noRequests, approved, rejected].map(
      (s) => s[7].state,
    );
    expect(all).not.toContain("complete");
    // Story 9.7: Complete once the version is the Baseline.
    const baselined = pipelineSteps(mockup(), {
      ...blockersView([], { status: "approved" }),
      is_baseline: true,
    });
    expect(baselined[7]).toMatchObject({ state: "complete", sub: "Baseline set on v3" });
  });

  it("a failed blockers read makes steps 4–8 Pending and says so", () => {
    const steps = pipelineSteps(mockup(), null);
    const message = "The submission blockers could not be loaded. Try again in a moment.";
    expect(steps.slice(3).map((s) => [s.state, s.sub])).toEqual(
      Array.from({ length: 5 }, () => ["pending", message]),
    );
    expect(steps.slice(0, 3).map((s) => s.state)).toEqual(["complete", "complete", "in-progress"]);
    expect(steps.some((s) => s.state === "blocked")).toBe(false);
  });

  it("a failed read makes its step Pending and says so", () => {
    const view = blockersView([]);
    const steps = pipelineSteps({ ...mockup(), gaps: null, conflicts: null }, view);
    expect(steps[3]).toMatchObject({
      state: "pending",
      sub: "Open Gaps could not be loaded. Try again in a moment.",
    });
    expect(steps[5]).toMatchObject({
      state: "pending",
      sub: "The Conflicts could not be loaded. Try again in a moment.",
    });
    const noReads = pipelineSteps({ ...mockup(), sources: null, requirements: null }, view);
    expect(noReads.slice(0, 3).map((s) => s.state)).toEqual(["pending", "pending", "pending"]);
    expect(noReads[0].sub).toBe("Sources could not be loaded. Try again in a moment.");
    expect(noReads[1].sub).toBe("Requirements could not be loaded. Try again in a moment.");
  });

  it("failures are In progress with the failure as the sub-line, never Blocked", () => {
    const failedSource = {
      id: uid(),
      parse: { status: "failed", error_code: "x" },
    } as unknown as Source;
    const data: OverviewReads = {
      ...mockup(),
      sources: [...(mockup().sources ?? []), failedSource],
      requirements: {
        items: [],
        extraction: { status: "failed", error_code: "x", source_count: 1 },
      } as unknown as RequirementList,
      gaps: gaps([], { status: "failed", error_code: null }),
      assessments: {
        ...EMPTY.assessments,
        run: { status: "waiting_for_human", tasks: [] },
      } as unknown as AssessmentsView,
      estimate: { version: null, draft: { status: "failed" } } as unknown as EstimateView,
    };
    const steps = pipelineSteps(data, blockersView([], { noVersion: true }));
    expect(steps.map((s) => [s.state, s.sub]).slice(0, 7)).toEqual([
      ["in-progress", "6 of 7 parsed, 1 failed"],
      ["in-progress", "Extraction failed"],
      ["pending", "Nothing to confirm yet"],
      ["in-progress", "Gap detection failed"],
      ["in-progress", "Waiting for you"],
      ["complete", "No Conflicts block submission"],
      ["in-progress", "Drafting failed"],
    ]);
  });

  it("waits on Conflicts while the Assessment run is still running and none exist", () => {
    const steps = pipelineSteps({ ...midWay(), conflicts: conflictsOf() }, blockersView([]));
    expect(steps[5]).toMatchObject({ state: "in-progress", sub: "Waiting for the Assessments" });
  });

  it("the Conflicts KPI blocks submit only with conflict items", () => {
    expect(conflictsBlockSubmit(blockersView(["conflict"]))).toBe(true);
    expect(conflictsBlockSubmit(blockersView(["gap"]))).toBe(false);
    expect(conflictsBlockSubmit(null)).toBe(false);
  });
});

describe("conflictCounts and attentionIncomplete", () => {
  it("counts unresolved and escalated Conflicts", () => {
    expect(conflictCounts(conflictsOf("open", "negotiating", "escalated", "resolved"))).toEqual({
      unresolved: 3,
      escalated: 1,
    });
  });

  it("is incomplete when a read the list draws on failed", () => {
    expect(attentionIncomplete(EMPTY)).toBe(false);
    expect(attentionIncomplete({ ...EMPTY, conflicts: null })).toBe(true);
    expect(attentionIncomplete({ ...EMPTY, estimate: null })).toBe(true);
    expect(attentionIncomplete({ ...EMPTY, redTeam: null })).toBe(true);
    expect(attentionIncomplete({ ...EMPTY, assessments: null })).toBe(true);
  });
});

describe("latestDecision", () => {
  it("takes the newest Assessment and its most severe Finding", () => {
    const view = {
      run: null,
      can_start: false,
      assessments: [
        {
          agent: "engineering_agent",
          assessment: { created_at: "2026-10-05T09:00:00Z", findings: [] },
        },
        {
          agent: "security_agent",
          assessment: {
            created_at: "2026-10-05T10:00:00Z",
            findings: [
              { position: 1, severity: "medium", title: "M" },
              { position: 2, severity: "high", title: "H1" },
              { position: 3, severity: "high", title: "H2" },
            ],
          },
        },
      ],
    } as unknown as AssessmentsView;
    const latest = latestDecision(view);
    expect(latest?.assessment.created_at).toBe("2026-10-05T10:00:00Z");
    expect(latest?.finding?.title).toBe("H1");
  });

  it("is null without an Assessment; the Finding is null without Findings", () => {
    expect(latestDecision(null)).toBeNull();
    expect(latestDecision(EMPTY.assessments)).toBeNull();
    const one = {
      ...EMPTY.assessments,
      assessments: [{ agent: "pm_agent", assessment: { created_at: "x", findings: [] } }],
    } as unknown as AssessmentsView;
    expect(latestDecision(one)?.finding).toBeNull();
  });
});

describe("a run waiting for a person (Story 5.5)", () => {
  const waiting = {
    run: {
      id: "r",
      status: "waiting_for_human",
      created_at: "2026-10-23T09:00:00Z",
      queued_at: "2026-10-23T09:00:00Z",
      finished_at: null,
      tasks: [],
      plan_version: 1,
      plan_versions: [],
      decisions: [
        {
          id: "d1",
          kind: "plan_escalation",
          agent: "security_agent",
          agent_name: "Security Agent",
          agent_active: false,
          status: "open",
          choice: null,
          row_version: 1,
          created_at: "2026-10-23T09:01:00Z",
          resolved_by: null,
          resolved_at: null,
        },
      ],
    },
    assessments: [],
    can_start: true,
    can_resolve: true,
    can_challenge: false,
  } satisfies AssessmentsView;

  it("is a Needs you row ranked with escalated Conflicts, linking to the Assessments tab", () => {
    expect(waitingRunItems(waiting)).toEqual([
      {
        key: "decision:d1",
        kind: "waiting-run",
        label: "Security assessment not planned: Security Agent is disabled",
        tab: "assessments",
      },
    ]);
    const items = attentionItems({
      redTeam: null,
      assessments: waiting,
      gaps: null,
      estimate: null,
    });
    expect(items.map((i) => i.kind)).toEqual(["waiting-run"]);
  });

  it("is nothing once the run no longer waits", () => {
    expect(waitingRunItems({ ...waiting, run: { ...waiting.run, status: "queued" } })).toEqual([]);
    expect(waitingRunItems(null)).toEqual([]);
  });
});
