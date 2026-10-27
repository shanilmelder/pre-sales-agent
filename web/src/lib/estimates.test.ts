import { describe, expect, it } from "vitest";

import {
  defaultDiffTarget,
  deltaText,
  diffTargets,
  diffToggleLabel,
  comparingAnnouncement,
  lineDelta,
  lineDeltas,
  lineTraceHref,
  parseDiffParam,
  withDiffParam,
} from "./estimates";
import { comparison } from "@/test/lineage-fixtures";

import {
  acceptAllLabel,
  acceptedLabel,
  approvedOn,
  baselineNote,
  baselineTag,
  parseVersionParam,
  switcherVersions,
  versionHref,
  assumptionKindLabel,
  carriedLabel,
  COLUMNS,
  convertedLabel,
  isProposing,
  registerSummary,
  staleMessage,
  draftFailure,
  footerRoleLabel,
  fromRunLabel,
  hours,
  isDrafting,
  isSent,
  lifecycleSteps,
  lineHeading,
  registerStatus,
  requirementCount,
  roleMixLabel,
  roleShares,
  ROLES,
  sectionLabel,
  SECTIONS,
  sourceLabel,
  uncoveredBanner,
  versionLabel,
  versionNote,
  versionTag,
  type SectionName,
  type VersionListItem,
} from "./estimates";

describe("the Baseline and the version switcher (Story 9.7)", () => {
  const item = (version: number, isBaseline = false): VersionListItem => ({
    id: `v${version}`,
    version,
    status: isBaseline ? "approved" : "superseded",
    is_baseline: isBaseline,
    created_by_name: null,
    created_at: "2026-10-20T09:00:00Z",
    reason: null,
  });

  it("every step is passed for the Baseline, with its note", () => {
    expect(lifecycleSteps("approved", true).map((s) => s.state)).toEqual([
      "passed",
      "passed",
      "passed",
      "passed",
    ]);
    expect(baselineNote(2)).toBe(
      "v2 is the Baseline. A Baseline is replaced only by a newer approved version, and editing it creates a new version.",
    );
    expect(baselineTag(4)).toBe("Baseline v4");
    expect(approvedOn("2026-10-21T09:00:00Z")).toBe("Approved 21 Oct 2026");
    expect(approvedOn(null)).toBe("Approved");
  });

  it("the switcher shows the Baseline then the two newest, without repeating one", () => {
    expect(switcherVersions([item(2, true), item(5), item(4), item(3)]).map((v) => v.version))
      .toEqual([2, 5, 4]);
    expect(switcherVersions([item(5, true), item(5 - 1)]).map((v) => v.version)).toEqual([5, 4]);
    expect(switcherVersions([item(3), item(2), item(1)]).map((v) => v.version)).toEqual([3, 2]);
    expect(switcherVersions([])).toEqual([]);
    // The selected version joins when it isn't one of them.
    expect(switcherVersions([item(4, true), item(5), item(3), item(1)], 1).map((v) => v.version))
      .toEqual([4, 5, 1]);
    expect(switcherVersions([item(4, true), item(5)], 5).map((v) => v.version)).toEqual([4, 5]);
  });

  it("?version= is a positive whole number", () => {
    expect(parseVersionParam("3")).toBe(3);
    expect(parseVersionParam(["12", "4"])).toBe(12);
    for (const bad of ["0", "-1", "1.5", "x", "", undefined, null, "01"])
      expect(parseVersionParam(bad)).toBeNull();
    expect(versionHref("o", 2)).toBe("/opportunities/o/estimate?version=2");
    expect(versionHref("o", null)).toBe("/opportunities/o/estimate");
  });
});

describe("estimate helpers", () => {
  it("lists the template's sections, roles and columns in order", () => {
    expect(SECTIONS.map((s) => s.value)).toEqual([
      "functional",
      "integration",
      "data",
      "security",
      "non_functional",
      "commercial",
    ]);
    expect(ROLES.map((r) => r.value)).toEqual([
      "engineer",
      "project_manager",
      "qa",
    ]);
    expect(COLUMNS).toEqual(["Line", "Covers", "Role mix", "Effort h", "Cont. h", "Total h"]);
    expect(sectionLabel("non_functional")).toBe("Non-functional");
    expect(sectionLabel("future" as SectionName)).toBe("future");
  });

  it("formats hours, role mixes, versions and counts", () => {
    expect(hours(10)).toBe("10.0");
    expect(hours(3.3)).toBe("3.3");
    expect(hours(2000)).toBe("2000.0");
    expect(roleMixLabel({ engineer: 60, project_manager: 20, qa: 20 })).toBe(
      "E 60 · PM 20 · QA 20",
    );
    expect(versionLabel({ status: "draft", version: 2 })).toBe("Draft v2");
    expect(versionLabel({ status: "superseded", version: 1 })).toBe(
      "Superseded v1",
    );
    expect(requirementCount(1)).toBe("1 Requirement");
    expect(uncoveredBanner(1)).toBe("1 Requirement not covered by an Estimate line.");
    expect(uncoveredBanner(2)).toBe("2 Requirements not covered by an Estimate line.");
  });

  it("names the version, its source and its lifecycle", () => {
    const draft = { status: "draft", version: 3, source: "assessments", source_run: 2 } as const;
    expect(versionTag(draft)).toBe("v3 · Draft");
    expect(versionTag({ status: "superseded", version: 1 })).toBe("v1 · Superseded");
    expect(fromRunLabel(draft)).toBe("From Assessments (run 2)");
    expect(fromRunLabel({ source_run: null })).toBeNull();
    expect(sourceLabel(draft)).toBe("Assessments (run 2)");
    expect(sourceLabel({ source: "assessments", source_run: null })).toBe("Assessments");
    expect(sourceLabel({ source: "model", source_run: null })).toBe("a model draft");
    expect(versionNote(draft)).toBe(
      "v3 is a draft built from Assessments (run 2). Each edit needs a reason and is traced.",
    );
    expect(versionNote({ ...draft, status: "superseded" })).toBe(
      "v3 is superseded and read only.",
    );
    expect(lifecycleSteps("draft")).toEqual([
      { label: "Draft", state: "current" },
      { label: "In review", state: "upcoming" },
      { label: "Approved", state: "upcoming" },
      { label: "Baseline", state: "upcoming" },
    ]);
    // A superseded version: Draft passed, nothing current (the pill says Superseded).
    expect(lifecycleSteps("superseded").map((s) => s.state)).toEqual([
      "passed",
      "upcoming",
      "upcoming",
      "upcoming",
    ]);
    // Story 9.1: In review is current while a Review Request is pending.
    expect(lifecycleSteps("in_review").map((s) => s.state)).toEqual([
      "passed",
      "current",
      "upcoming",
      "upcoming",
    ]);
    expect(lifecycleSteps("submitted").map((s) => s.state)).toEqual([
      "passed",
      "upcoming",
      "upcoming",
      "upcoming",
    ]);
    expect(versionTag({ status: "in_review", version: 3 })).toBe("v3 · In review");
    expect(versionNote({ ...draft, status: "in_review" })).toBe("v3 is in review and read only.");
    // Story 9.3: Approved is current, with In review passed; a rejected version has no step.
    expect(lifecycleSteps("approved").map((s) => s.state)).toEqual([
      "passed",
      "passed",
      "current",
      "upcoming",
    ]);
    expect(lifecycleSteps("rejected").map((s) => s.state)).toEqual([
      "passed",
      "upcoming",
      "upcoming",
      "upcoming",
    ]);
    expect(versionTag({ status: "approved", version: 3 })).toBe("v3 · Approved");
    expect(versionTag({ status: "rejected", version: 3 })).toBe("v3 · Rejected");
    expect(versionNote({ ...draft, status: "approved" })).toBe(
      "v3 is approved by every reviewer and read only.",
    );
    expect(isSent("approved") && isSent("rejected") && !isSent("superseded")).toBe(true);
  });

  it("splits a role mix into bar shares and labels the role totals", () => {
    expect(
      roleShares({ engineer: 60, project_manager: 20, qa: 20 }).map((r) => [r.short, r.percent]),
    ).toEqual([
      ["E", 60],
      ["PM", 20],
      ["QA", 20],
    ]);
    expect(
      roleShares({ engineer: 0, project_manager: 0, qa: 0 }).map((r) => r.percent),
    ).toEqual([0, 0, 0]);
    const totals = { role_hours: { engineer: 24.5, project_manager: 8.2, qa: 8.3 } };
    expect(footerRoleLabel(totals)).toBe("Engineer 24.5 h · PM 8.2 h · QA 8.3 h");
    expect(
      footerRoleLabel({ role_hours: { engineer: 10, project_manager: 2, qa: 0 } }),
    ).toBe("Engineer 10.0 h · PM 2.0 h");
    expect(lineHeading({ section: "integration", position: 2 })).toBe("Integration · line 2");
  });

  it("says why a draft failed", () => {
    expect(draftFailure("model_unavailable")).toBe(
      "Estimate draft failed: the model service couldn't be reached",
    );
    expect(draftFailure("output_invalid")).toBe(
      "Estimate draft failed: the model's answer couldn't be used",
    );
    expect(draftFailure(null)).toBe(
      "Estimate draft failed: something went wrong",
    );
  });

  it("is drafting only while queued or running", () => {
    expect(isDrafting({ status: "queued", error_code: null })).toBe(true);
    expect(isDrafting({ status: "running", error_code: null })).toBe(true);
    expect(isDrafting({ status: "succeeded", error_code: null })).toBe(false);
    expect(isDrafting(null)).toBe(false);
  });
});

describe("Assumptions Register helpers", () => {
  it("summarises the counts and labels Accept all", () => {
    expect(registerSummary({ total: 7, accepted: 6, not_accepted: 1 })).toBe(
      "7 · 6 accepted · 1 not accepted",
    );
    expect(acceptAllLabel(3)).toBe("Accept all (3)");
    expect(registerStatus({ not_accepted: 2 })).toEqual({
      tone: "blocker",
      label: "2 not accepted block submit",
    });
    expect(registerStatus({ not_accepted: 0 })).toEqual({
      tone: "resolved",
      label: "All accepted",
    });
    expect(assumptionKindLabel("condition")).toBe("Condition");
    expect(assumptionKindLabel("contingency")).toBe("Contingency");
  });

  it("says who accepted and when, in UTC", () => {
    expect(
      acceptedLabel({
        accepted_by: { id: "u", name: "[NAME]" },
        accepted_at: "2026-10-05T23:30:00Z",
      }),
    ).toBe("Accepted by [NAME] · 5 Oct 2026");
    expect(acceptedLabel({ accepted_by: null, accepted_at: null })).toBe(
      "Accepted by someone",
    );
  });

  it("says which version a carried Assumption came from", () => {
    expect(carriedLabel({ carried_from_version: 1 })).toBe("Carried from v1");
    expect(carriedLabel({ carried_from_version: null })).toBeNull();
  });

  it("names a 412's changer, or someone else", () => {
    expect(staleMessage("[OTHER]")).toBe(
      "Changed by [OTHER] since you opened it.",
    );
    expect(staleMessage(null)).toBe(
      "Changed by someone else since you opened it.",
    );
  });

  it("labels converted Gaps and tells when proposals are in progress", () => {
    expect(convertedLabel("condition")).toBe("Converted to Condition");
    expect(convertedLabel("contingency")).toBe("Converted to Contingency");
    expect(isProposing({ proposal_status: "queued" })).toBe(true);
    expect(isProposing({ proposal_status: "running" })).toBe(true);
    expect(isProposing({ proposal_status: "succeeded" })).toBe(false);
    expect(isProposing({ proposal_status: null })).toBe(false);
    expect(isProposing(null)).toBe(false);
  });
});

describe("lineage and compare helpers (Story 9.9)", () => {
  const item = (version: number, isBaseline = false) => ({ version, is_baseline: isBaseline });

  it("a delta reads +x.x h, −x.x h (a minus sign) or no change", () => {
    expect(deltaText(4)).toBe("+4.0 h");
    expect(deltaText(-2.5)).toBe("−2.5 h");
    expect(deltaText(0.04)).toBe("no change");
    expect(deltaText(0)).toBe("no change");
  });

  it("the default target is the Baseline when the shown version is later, else the one before", () => {
    expect(defaultDiffTarget([item(2, true), item(3), item(1)], 3)).toBe(2);
    expect(defaultDiffTarget([item(4, true), item(5), item(3), item(2)], 3)).toBe(2);
    expect(defaultDiffTarget([item(2, true), item(3), item(1)], 2)).toBe(1);
    expect(defaultDiffTarget([item(3), item(2), item(1)], 3)).toBe(2);
    expect(defaultDiffTarget([item(1)], 1)).toBeNull();
    expect(diffTargets([item(2, true), item(3), item(1)], 3).map((v) => v.version)).toEqual([2, 1]);
  });

  it("labels, the URL parameter and the trace link", () => {
    expect(diffToggleLabel(2)).toBe("Diff vs v2");
    expect(comparingAnnouncement(3, 2)).toBe("Comparing v3 with v2");
    expect(parseDiffParam("?diff=2&version=3")).toBe(2);
    expect(parseDiffParam("?diff=0")).toBeNull();
    expect(parseDiffParam("?diff=x")).toBeNull();
    expect(withDiffParam("http://h/o/1/estimate?version=3", 2)).toBe("/o/1/estimate?version=3&diff=2");
    expect(withDiffParam("http://h/o/1/estimate?diff=2", null)).toBe("/o/1/estimate");
    expect(lineTraceHref("o1", "l1")).toBe(
      "/opportunities/o1/trace?subject=estimates.estimate_line&subject_id=l1",
    );
  });

  it("line deltas match the shown line by section and title, removed ones left out", () => {
    const deltas = lineDeltas(comparison());
    expect(lineDelta(deltas, { section: "integration", title: " [line 2] " })?.delta_hours).toBe(-4);
    expect(lineDelta(deltas, { section: "functional", title: "[OLD LINE]" })).toBeNull();
    expect(lineDelta(deltas, { section: "functional", title: "[LINE 1]" })).toBeNull();
  });
});
