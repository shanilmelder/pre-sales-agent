import { describe, expect, it } from "vitest";

import {
  categoryLabel,
  detectionFailure,
  gapCount,
  GAP_CATEGORIES,
  impactLabel,
  impactLevel,
  isDetecting,
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
