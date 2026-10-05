import { describe, expect, it } from "vitest";

import {
  approveAllLabel,
  approvedCount,
  approvedLabel,
  categoryLabel,
  detectionFailure,
  gapCount,
  GAP_CATEGORIES,
  impactLabel,
  impactLevel,
  isDetecting,
  questionStatus,
  questionTextProblem,
  questionTopicProblem,
  statusSince,
  toApprove,
  type Gap,
  type GapCategory,
  type Impact,
} from "./gaps";

describe("gaps helpers", () => {
  it("labels every category, and falls back to the value for an unknown one", () => {
    expect(GAP_CATEGORIES.map((c) => c.value)).toEqual([
      "data_volumes",
      "versions_and_platforms",
      "integration_details",
      "security_and_compliance",
      "non_functional",
      "scope_and_ownership",
      "commercial",
      "other",
    ]);
    expect(categoryLabel("integration_details")).toBe("Integration details");
    expect(categoryLabel("future" as GapCategory)).toBe("future");
  });

  it("maps impacts to labels and bar levels", () => {
    expect([impactLabel("high"), impactLevel("high")]).toEqual(["High", 3]);
    expect([impactLabel("medium"), impactLevel("medium")]).toEqual(["Medium", 2]);
    expect([impactLabel("low"), impactLevel("low")]).toEqual(["Low", 1]);
    expect(impactLevel("unknown" as Impact)).toBe(0);
  });

  it("says why a detection failed", () => {
    expect(detectionFailure("model_unavailable")).toBe(
      "Gap detection failed: the model service couldn't be reached",
    );
    expect(detectionFailure(null)).toBe("Gap detection failed: something went wrong");
  });

  it("counts Gaps and knows when a detection is in progress", () => {
    expect(gapCount(1)).toBe("1 Gap");
    expect(gapCount(3)).toBe("3 Gaps");
    expect(isDetecting({ status: "queued", error_code: null })).toBe(true);
    expect(isDetecting({ status: "running", error_code: null })).toBe(true);
    expect(isDetecting({ status: "succeeded", error_code: null })).toBe(false);
    expect(isDetecting(null)).toBe(false);
  });
});

describe("question helpers (Story 4.5)", () => {
  const question = {
    status: "approved" as const,
    status_changed_at: "2026-10-05T11:00:00Z",
    approved_by: { id: "u", name: "Jane Doe" },
    approved_at: "2026-10-05T11:00:00Z",
  };

  it("labels the statuses, with Draft for one this build doesn't know", () => {
    expect(questionStatus("drafted").label).toBe("Draft");
    expect(questionStatus("approved").label).toBe("Approved");
    expect(questionStatus("approved").tone).toBe("text-resolved");
    expect(questionStatus("superseded").label).toBe("Draft");
  });

  it("says who approved and since when", () => {
    expect(approvedLabel(question)).toBe("Approved by Jane Doe, 5 Oct 2026");
    expect(approvedLabel({ approved_by: null, approved_at: null })).toBe("Approved by someone");
    expect(statusSince(question)).toBe("Approved since 5 Oct 2026");
  });

  it("checks text and topic like the API, in code points after trimming", () => {
    expect(questionTextProblem("  ")).toBe("The question can't be blank.");
    expect(questionTextProblem(` ${"x".repeat(1000)} `)).toBeNull();
    expect(questionTextProblem("x".repeat(1001))).toBe(
      "The question can be at most 1,000 characters.",
    );
    expect(questionTopicProblem("")).toBe("The topic can't be blank.");
    expect(questionTopicProblem("😀".repeat(80))).toBeNull();
    expect(questionTopicProblem("t".repeat(81))).toBe("The topic can be at most 80 characters.");
  });

  it("counts the drafted questions of open Gaps for Approve all", () => {
    const base = { status: "open", question: { status: "drafted" } };
    const items = [
      base,
      { ...base, question: { status: "approved" } },
      { ...base, status: "converted" },
      { ...base, question: null },
      base,
    ] as unknown as Gap[];
    expect(toApprove(items)).toHaveLength(2);
    expect(approveAllLabel(2)).toBe("Approve all (2)");
    expect(approvedCount(1)).toBe("1 question approved");
    expect(approvedCount(3)).toBe("3 questions approved");
  });
});
