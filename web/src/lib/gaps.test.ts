import { describe, expect, it } from "vitest";

import {
  checklistChipLabel,
  coverageBanner,
  coverageHref,
  untaggedBanner,
  untaggedHref,
  areaFilterOptions,
  approveAllLabel,
  approvedCount,
  approvedLabel,
  categoryLabel,
  copiedCount,
  detectionFailure,
  filterGaps,
  gapCount,
  gapsSummary,
  GAP_CATEGORIES,
  hasGapFilters,
  impactTone,
  NO_GAP_FILTERS,
  QUESTION_FILTER_OPTIONS,
  questionFlow,
  impactLabel,
  impactLevel,
  isDetecting,
  isSent,
  localToday,
  markAllSentLabel,
  markSelectedSentLabel,
  QUESTION_EXPORT_FORMATS,
  questionsExportFailureReason,
  questionsExportUrl,
  questionStatus,
  questionTextProblem,
  questionTopicProblem,
  sentCount,
  sentLabel,
  sentOnProblem,
  statusSince,
  toApprove,
  toSend,
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

describe("sending helpers (Story 4.6)", () => {
  it("labels Sent (primary) and No answer (gap amber); both count as sent", () => {
    expect(questionStatus("sent")).toMatchObject({ label: "Sent", tone: "text-primary" });
    expect(questionStatus("unanswered")).toMatchObject({ label: "No answer", tone: "text-gap" });
    expect([isSent("sent"), isSent("unanswered"), isSent("approved")]).toEqual([
      true,
      true,
      false,
    ]);
  });

  it("says when and by whom a question was sent", () => {
    expect(sentLabel({ sent_on: "2026-10-14", sent_by: { id: "u", name: "Rep Person" } })).toBe(
      "Sent 14 Oct 2026 by Rep Person",
    );
    expect(sentLabel({ sent_on: null, sent_by: null })).toBe("Sent by someone");
  });

  it("lists the approved questions of open Gaps as what is sent", () => {
    const base = { status: "open", question: { status: "approved" } };
    const items = [
      base,
      { ...base, question: { status: "drafted" } },
      { ...base, question: { status: "sent" } },
      { ...base, status: "converted" },
    ] as unknown as Gap[];
    expect(toSend(items)).toHaveLength(1);
    expect(markAllSentLabel(3)).toBe("Mark all sent (3)");
    expect(markSelectedSentLabel(2)).toBe("Mark 2 selected sent");
    expect(sentCount(1)).toBe("1 question marked sent");
    expect(copiedCount(3)).toBe("3 questions copied");
  });

  it("checks the date sent: required, not in the future", () => {
    expect(localToday(new Date(2026, 9, 4))).toBe("2026-10-04");
    expect(sentOnProblem("2026-10-14", "2026-10-14")).toBeNull();
    expect(sentOnProblem("2026-10-15", "2026-10-14")).toBe("The date sent can't be in the future.");
    expect(sentOnProblem("", "2026-10-14")).toBe("Give the date the questions were sent.");
  });

  it("names the export formats, its route and its failures", () => {
    expect(QUESTION_EXPORT_FORMATS.map((f) => f.label)).toEqual([
      "Copy",
      "Word (.docx)",
      "Email draft (.eml)",
    ]);
    expect(questionsExportUrl("o 1", "eml")).toBe("/api/opportunities/o%201/questions-export?format=eml");
    expect(questionsExportFailureReason(409)).toBe("there are no approved questions to export");
    expect(questionsExportFailureReason(null)).toBe("the export service couldn't be reached");
  });
});

describe("Gaps tab redesign helpers", () => {
  const items = [
    { status: "open", impact: "high", category: "data_volumes", question: { status: "drafted" } },
    { status: "open", impact: "medium", category: "commercial", question: { status: "approved" } },
    { status: "open", impact: "low", category: "data_volumes", question: { status: "sent" } },
    { status: "dismissed", impact: "high", category: "other", question: { status: "drafted" } },
    { status: "answered", impact: "low", category: "commercial", question: null },
  ] as unknown as Gap[];

  it("summarises the list, appending how many show while filtering", () => {
    expect(gapsSummary(items)).toBe("5 total · 3 open · ranked by impact");
    expect(gapsSummary(items, 1)).toBe("5 total · 3 open · ranked by impact · showing 1");
  });

  it("tones impacts: High blocker, Medium gap, Low neutral", () => {
    expect(["high", "medium", "low"].map((i) => impactTone(i as Impact))).toEqual([
      "text-blocker",
      "text-gap",
      "text-neutral",
    ]);
  });

  it("says where the question is in its flow", () => {
    expect(questionFlow("drafted")).toBe("Draft, then Approved, Sent and Answered.");
    expect(questionFlow("approved")).toBe(
      "Approved. Export it, send it to the customer, then mark it sent.",
    );
    expect(questionFlow("sent")).toBe("Sent. Record the customer answer to close this Gap.");
    expect(questionFlow("unanswered")).toBe(questionFlow("sent"));
    expect(questionFlow("answered")).toBe("Answered. Related Requirements have proposed updates.");
    expect(questionFlow("dismissed")).toBe("Dismissed with a reason.");
    expect(questionFlow("superseded" as never)).toBeNull();
  });

  it("filters with AND, keeping the order; no filter keeps every Gap", () => {
    expect(hasGapFilters(NO_GAP_FILTERS)).toBe(false);
    expect(filterGaps(items, NO_GAP_FILTERS)).toEqual(items);
    expect(filterGaps(items, { ...NO_GAP_FILTERS, impact: "high" })).toEqual([items[0], items[3]]);
    const both = { impact: "high", category: "data_volumes", question: null } as const;
    expect(hasGapFilters(both)).toBe(true);
    expect(filterGaps(items, both)).toEqual([items[0]]);
    expect(filterGaps(items, { ...NO_GAP_FILTERS, question: "sent" })).toEqual([items[2]]);
    // A Gap whose question the viewer can't see matches no question status.
    expect(filterGaps(items, { ...NO_GAP_FILTERS, question: "answered" })).toEqual([]);
  });

  it("offers the areas present, in the categories' order, and the question statuses", () => {
    expect(areaFilterOptions(items).map((o) => o.label)).toEqual([
      "Data volumes",
      "Commercial",
      "Other",
    ]);
    expect(
      areaFilterOptions([{ category: "brand_new" as GapCategory }]).map((o) => o.label),
    ).toEqual(["brand_new"]);
    expect(QUESTION_FILTER_OPTIONS.map((o) => o.label)).toEqual([
      "Draft",
      "Approved",
      "Sent",
      "No answer",
      "Answered",
    ]);
  });
});

describe("the Gaps tab context copy (Story 4.1)", () => {
  it("labels a Checklist chip with its version", () => {
    expect(checklistChipLabel({ name: "Security baseline", version: 3 })).toBe(
      "Security baseline · v3",
    );
  });

  it("uses has for one untagged Requirement and have for more", () => {
    expect(untaggedBanner(1)).toBe(
      "1 integration Requirement has no Integration Type — Checklists may not apply",
    );
    expect(untaggedBanner(3)).toBe(
      "3 integration Requirements have no Integration Type — Checklists may not apply",
    );
    expect(untaggedHref("o 1")).toBe("/opportunities/o%201/requirements?untagged=integration");
  });

  it("joins the uncovered parts, leaving out zero ones, or is null with none", () => {
    const type = { id: "t1", name: "EDI" };
    expect(coverageBanner({ products: [], integration_types: [] })).toBeNull();
    expect(coverageBanner({ products: ["A"], integration_types: [type, type] })).toBe(
      "No documentation for 2 integration types and 1 product in scope — Gap detection may be " +
        "incomplete",
    );
    expect(coverageBanner({ products: ["A", "B"], integration_types: [] })).toBe(
      "No documentation for 2 products in scope — Gap detection may be incomplete",
    );
    expect(coverageHref({ products: ["A&B"], integration_types: [type] })).toBe(
      "/knowledge?integration_type=t1",
    );
    expect(coverageHref({ products: ["A&B"], integration_types: [] })).toBe(
      "/knowledge?product=A%26B",
    );
  });
});
