import { describe, expect, it } from "vitest";

import { countdownLabel, daysUntil } from "./opportunities";

describe("daysUntil", () => {
  it.each([
    ["2026-11-01", "2026-10-21", 11],
    ["2026-10-22", "2026-10-21", 1],
    ["2026-10-21", "2026-10-21", 0],
    ["2026-10-18", "2026-10-21", -3],
    ["2026-11-01", "2026-10-31", 1], // month end
    ["2028-03-01", "2028-02-28", 2], // leap day
    ["2027-03-01", "2027-02-28", 1],
    ["2027-01-01", "2026-12-31", 1], // year end
  ])("%s from %s is %i", (date, today, days) => {
    expect(daysUntil(date, today)).toBe(days);
  });

  it("is NaN for a non-date", () => {
    expect(daysUntil("soon", "2026-10-21")).toBeNaN();
  });
});

describe("countdownLabel", () => {
  it.each([
    [11, "11 days left"],
    [2, "2 days left"],
    [1, "Due tomorrow"],
    [0, "Due today"],
    [-1, "1 day overdue"],
    [-3, "3 days overdue"],
  ])("%i is %s", (days, label) => {
    expect(countdownLabel(days)).toBe(label);
  });
});
