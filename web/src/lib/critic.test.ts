import { describe, expect, it } from "vitest";

import {
  CRITIC_CATEGORIES,
  CRITIC_REVIEWING,
  citedFindingLabel,
  criticCategoryLabel,
  criticReviewLabel,
} from "@/lib/critic";

describe("Critic display helpers (Story 6.4)", () => {
  it("labels every category, and falls back to the raw value", () => {
    expect(CRITIC_CATEGORIES.map((c) => criticCategoryLabel(c.value))).toEqual([
      "Coverage",
      "Unsupported claim",
      "Timeline",
      "Dependency",
      "Risk coverage",
    ]);
    expect(criticCategoryLabel("velocity" as never)).toBe("velocity");
  });

  it("names the review and its cited Findings", () => {
    expect(criticReviewLabel({ version: 2 })).toBe("Critic v2");
    expect(citedFindingLabel({ role: "PM Agent", assessment_version: 3 })).toBe("PM Agent v3");
    expect(CRITIC_REVIEWING).toBe("Critic reviewing");
  });
});
