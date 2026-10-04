import { describe, expect, it } from "vitest";

import {
  CATEGORIES,
  categoryLabel,
  countsLabel,
  findingCount,
  isReviewing,
  reviewFailure,
  reviewLabel,
  SEVERITIES,
  severityInfo,
  type FindingCategory,
  type Severity,
} from "./red-team";

describe("red team helpers", () => {
  it("lists severities most severe first, blocker red only for critical and gap amber for high", () => {
    expect(SEVERITIES.map((s) => [s.value, s.label, s.tone])).toEqual([
      ["critical", "Critical", "text-blocker"],
      ["high", "High", "text-gap"],
      ["medium", "Medium", "text-muted-foreground"],
      ["low", "Low", "text-muted-foreground"],
    ]);
    expect(severityInfo("bogus" as Severity).label).toBe("bogus");
  });

  it("labels the categories", () => {
    expect(CATEGORIES.map((c) => c.value)).toEqual([
      "integration_harder",
      "requirement_incomplete",
      "capability_overstated",
      "hidden_dependency",
    ]);
    expect(categoryLabel("hidden_dependency")).toBe("Hidden dependency");
    expect(categoryLabel("new_kind" as FindingCategory)).toBe("new_kind");
  });

  it("says the version, counts and failure", () => {
    expect(reviewLabel({ version: 2 })).toBe("Red Team v2");
    expect(countsLabel({ critical: 1, high: 2, medium: 0, low: 3 })).toBe(
      "1 critical · 2 high · 0 medium · 3 low",
    );
    expect(findingCount(1)).toBe("1 Finding");
    expect(findingCount(4)).toBe("4 Findings");
    expect(reviewFailure("output_invalid")).toBe(
      "Red Team review failed: the model's answer couldn't be used",
    );
    expect(reviewFailure(null)).toBe("Red Team review failed: something went wrong");
  });

  it("is reviewing only while queued or running", () => {
    expect(isReviewing({ status: "queued", error_code: null })).toBe(true);
    expect(isReviewing({ status: "running", error_code: null })).toBe(true);
    expect(isReviewing({ status: "succeeded", error_code: null })).toBe(false);
    expect(isReviewing(null)).toBe(false);
  });
});
