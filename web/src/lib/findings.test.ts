import { describe, expect, it } from "vitest";

import { blocksSubmission, findingStatusInfo, totalBlocking } from "@/lib/findings";

describe("totalBlocking (the Assessments badge, Story 6.6)", () => {
  it("sums the Red Team's and the Critic's counts", () => {
    expect(totalBlocking({ blocking_count: 2 }, { blocking_count: 1 })).toBe(3);
    expect(totalBlocking({ blocking_count: 0 }, { blocking_count: 0 })).toBe(0);
  });

  it("is null unless every read succeeded (never a partial count)", () => {
    expect(totalBlocking({ blocking_count: 2 }, null)).toBeNull();
    expect(totalBlocking(undefined, { blocking_count: 1 })).toBeNull();
    expect(totalBlocking(null, null)).toBeNull();
  });
});

describe("a Finding's status", () => {
  it("blocks only when open and critical", () => {
    expect(blocksSubmission({ status: "open", severity: "critical" })).toBe(true);
    expect(blocksSubmission({ status: "open", severity: "high" })).toBe(false);
    expect(blocksSubmission({ status: "overridden", severity: "critical" })).toBe(false);
    expect(findingStatusInfo("open", "critical").tone).toBe("blocker");
    expect(findingStatusInfo("overridden", "critical").label).toBe("Overridden");
  });
});
