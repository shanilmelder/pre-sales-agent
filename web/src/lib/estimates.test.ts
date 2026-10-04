import { describe, expect, it } from "vitest";

import {
  acceptAllLabel,
  acceptedLabel,
  COLUMNS,
  convertedLabel,
  isProposing,
  registerSummary,
  staleMessage,
  draftFailure,
  hours,
  isDrafting,
  requirementCount,
  roleMixLabel,
  ROLES,
  sectionLabel,
  SECTIONS,
  uncoveredLabel,
  versionLabel,
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
    expect(COLUMNS).toEqual([
      "Line",
      "Covers",
      "Role mix (%)",
      "Effort (h)",
      "Contingency (h)",
      "Total (h)",
    ]);
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
    expect(uncoveredLabel(1)).toBe("1 Requirement not covered");
    expect(uncoveredLabel(3)).toBe("3 Requirements not covered");
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
  });

  it("says who accepted and when, in UTC", () => {
    expect(
      acceptedLabel({
        accepted_by: { id: "u", name: "[NAME]" },
        accepted_at: "2026-10-05T23:30:00Z",
      }),
    ).toBe("Accepted by [NAME], 5 Oct 2026");
    expect(acceptedLabel({ accepted_by: null, accepted_at: null })).toBe(
      "Accepted by someone",
    );
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
