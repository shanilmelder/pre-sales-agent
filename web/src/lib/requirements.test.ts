import { describe, expect, it } from "vitest";

import {
  CLASSIFICATIONS,
  extractionFailure,
  groupRequirements,
  isExtracting,
  noneFound,
  requirementCount,
  type Classification,
  type Requirement,
} from "./requirements";

function requirement(n: number, classification: Classification): Requirement {
  return {
    id: `r${n}`,
    text: `Requirement ${n}`,
    classification,
    origin: "extracted",
    locked_by_human: false,
    version: 1,
    row_version: 1,
    created_at: "2026-10-04T13:05:00Z",
    evidence: [],
  };
}

describe("groupRequirements", () => {
  it("groups in the fixed classification order, keeps order inside a group, hides empty groups", () => {
    const groups = groupRequirements([
      requirement(1, "commercial"),
      requirement(2, "functional"),
      requirement(3, "security"),
      requirement(4, "functional"),
    ]);
    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ["Functional", ["r2", "r4"]],
      ["Security", ["r3"]],
      ["Commercial", ["r1"]],
    ]);
  });

  it("lists the six classifications in the tab's order", () => {
    expect(CLASSIFICATIONS.map((c) => c.label)).toEqual([
      "Functional",
      "Integration",
      "Data",
      "Security",
      "Non-functional",
      "Commercial",
    ]);
  });

  it("puts an unknown classification last under its own name", () => {
    const odd = { ...requirement(9, "data"), classification: "legal" as Classification };
    const groups = groupRequirements([odd, requirement(1, "data")]);
    expect(groups.map((g) => g.label)).toEqual(["Data", "legal"]);
  });

  it("is empty for no Requirements", () => {
    expect(groupRequirements([])).toEqual([]);
  });
});

describe("extraction state", () => {
  it.each([
    ["model_unavailable", "Extraction failed: the model service couldn't be reached"],
    ["model_timeout", "Extraction failed: the model took too long to answer"],
    ["output_invalid", "Extraction failed: the model's answer couldn't be used"],
    ["input_too_large", "Extraction failed: the Sources are too long to process in one go"],
  ] as const)("%s reads %s", (code, sentence) => {
    expect(extractionFailure(code)).toBe(sentence);
  });

  it("has a general reason for an unknown code", () => {
    expect(extractionFailure(null)).toBe("Extraction failed: something went wrong");
  });

  it("is extracting while queued or running only", () => {
    const at = (status: "queued" | "running" | "succeeded" | "failed") => ({
      status,
      error_code: null,
      source_count: null,
    });
    expect(isExtracting(at("queued"))).toBe(true);
    expect(isExtracting(at("running"))).toBe(true);
    expect(isExtracting(at("succeeded"))).toBe(false);
    expect(isExtracting(at("failed"))).toBe(false);
    expect(isExtracting(null)).toBe(false);
  });
});

describe("counts", () => {
  it("pluralises Requirements and Sources", () => {
    expect(requirementCount(0)).toBe("0 Requirements");
    expect(requirementCount(1)).toBe("1 Requirement");
    expect(requirementCount(3)).toBe("3 Requirements");
    expect(noneFound(1)).toBe("No Requirements were found in 1 Source.");
    expect(noneFound(3)).toBe("No Requirements were found in 3 Sources.");
    expect(noneFound(null)).toBe("No Requirements were found in 0 Sources.");
  });
});
