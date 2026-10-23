import { describe, expect, it } from "vitest";

import {
  acceptAllLabel,
  acceptedLabel,
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
} from "./estimates";

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
      { label: "Baseline", state: "upcoming" },
      { label: "Superseded", state: "upcoming" },
    ]);
    expect(lifecycleSteps("superseded").map((s) => s.state)).toEqual([
      "passed",
      "upcoming",
      "current",
    ]);
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
