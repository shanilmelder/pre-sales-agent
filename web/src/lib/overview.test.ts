import { describe, expect, it } from "vitest";

import type { AssessmentsView } from "./assessments";
import type { Assumption, EstimateView } from "./estimates";
import type { Gap, GapList } from "./gaps";
import {
  attentionItems,
  byTypeLabel,
  couldNotLoad,
  criticalHighLabel,
  cutAttention,
  gapCounts,
  isStepStatus,
  itemCountLabel,
  moreLabel,
  noAssessmentYet,
  parsedLabel,
  requirementCounts,
  sourceCounts,
  unacceptedAssumptions,
} from "./overview";
import type { RedTeamView } from "./red-team";
import type { Requirement, RequirementList } from "./requirements";
import type { Source } from "./sources";

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
        redTeam: { review: null, run: null, can_start: false },
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

  it("counts active Requirements by type, null before an extraction", () => {
    const req = (classification: string) =>
      ({ id: uid(), classification }) as unknown as Requirement;
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
    ).toEqual({ active: 0, byType: [] });
    const counts = requirementCounts(
      list([req("integration"), req("functional"), req("functional")], {
        status: "succeeded",
        error_code: null,
        source_count: 1,
      }),
    );
    if (counts === null || isStepStatus(counts))
      throw new Error("expected counts");
    expect(counts.active).toBe(3);
    expect(byTypeLabel(counts.byType)).toBe("2 Functional · 1 Integration");
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
    expect(isStepStatus({ active: 0, byType: [] })).toBe(false);
  });

  it("counts open Gaps and the high-impact ones, null before a detection", () => {
    expect(gapCounts(gaps([], null))).toBeNull();
    expect(
      gapCounts(
        gaps([
          gap("a", "high"),
          gap("b", "low"),
          gap("c", "high", "superseded"),
        ]),
      ),
    ).toEqual({ open: 2, high: 1 });
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
    ).toEqual({
      open: 0,
      high: 0,
    });
    expect(
      gapCounts(
        gaps([gap("a", "high")], { status: "running", error_code: null }),
      ),
    ).toEqual({
      open: 1,
      high: 1,
    });
  });
});

describe("assessments card helpers", () => {
  it("knows when there is nothing to show yet", () => {
    const none = {
      run: null,
      can_start: false,
      assessments: [{ agent: "pm_agent", assessment: null }],
    } as unknown as AssessmentsView;
    const noReview: RedTeamView = { review: null, run: null, can_start: false };
    expect(noAssessmentYet(none, noReview)).toBe(true);
    expect(
      noAssessmentYet(
        { ...none, run: { status: "running" } } as AssessmentsView,
        noReview,
      ),
    ).toBe(false);
    expect(noAssessmentYet(none, redTeam([]))).toBe(false);
    expect(itemCountLabel(1)).toBe("1 item");
    expect(itemCountLabel(5)).toBe("5 items");
    expect(criticalHighLabel({ critical: 1, high: 2 })).toBe(
      "1 critical · 2 high",
    );
    expect(couldNotLoad("The Estimate")).toBe(
      "The Estimate could not be loaded. Try again in a moment.",
    );
  });
});
