import { describe, expect, it } from "vitest";

import {
  agentName,
  agentRows,
  diffRows,
  formatCost,
  meets,
  percent,
  signedPoints,
  statusLabel,
  thresholdLabel,
} from "@/lib/evals";
import { evalResult } from "@/test/eval-fixtures";

describe("eval helpers", () => {
  it("labels statuses and formats values", () => {
    expect(["pass", "fail", "not_measured"].map((s) => statusLabel(s as never))).toEqual([
      "Pass",
      "Fail",
      "Not measured",
    ]);
    expect(percent(91)).toBe("91.0%");
    expect(percent(null)).toBe("—");
    expect(thresholdLabel({ comparator: "min", threshold: 90 })).toBe("≥ 90%");
    expect(thresholdLabel({ comparator: "max", threshold: 20 })).toBe("≤ 20%");
    expect(formatCost({ amount_minor: 1234, currency: "EUR" })).toBe("12.34 EUR");
    expect(formatCost({ amount_minor: 1234, currency: "JPY" })).toBe("1234 JPY");
    expect(formatCost({ amount_minor: 1234, currency: "BHD" })).toBe("1.234 BHD");
  });

  it("signs deltas with a real minus sign", () => {
    expect(signedPoints(-7)).toBe("−7.0");
    expect(signedPoints(1.5)).toBe("+1.5");
    expect(signedPoints(0)).toBe("0.0");
    expect(signedPoints(null)).toBe("—");
  });

  it("names agents", () => {
    expect(agentName("intake_agent")).toBe("Intake Agent");
    expect(agentName("red_team_agent")).toBe("Red Team Agent");
    expect(agentName("pm_agent")).toBe("PM Agent");
  });

  it("judges values against min and max thresholds", () => {
    const min = { comparator: "min", threshold: 80 } as const;
    const max = { comparator: "max", threshold: 20 } as const;
    expect([meets(min, 80), meets(min, 79.9), meets(min, null)]).toEqual([
      "pass",
      "fail",
      "not_measured",
    ]);
    expect([meets(max, 20), meets(max, 20.1)]).toEqual(["pass", "fail"]);
  });

  it("lists each Agent's value for the bars it owns", () => {
    const rows = agentRows(evalResult(1, { gap_recall: 84, evidence_support: 100 }));
    const evidence = rows.filter((r) => r.bar.metric === "evidence_support");
    expect(evidence.map((r) => [r.agentId, r.status])).toEqual([
      ["engineering_agent", "not_measured"],
      ["red_team_agent", "pass"],
    ]);
    expect(rows.find((r) => r.bar.metric === "gap_recall")?.status).toBe("pass");
  });

  it("diffs bar values against the previous result", () => {
    const rows = diffRows(
      evalResult(2, { gap_recall: 84, irrelevant_gaps: 10 }),
      evalResult(1, { gap_recall: 91, irrelevant_gaps: 10 }),
    );
    const gap = rows.find((r) => r.metric === "gap_recall");
    expect(gap).toMatchObject({ previous: 91, current: 84, delta: -7, changed: true });
    expect(rows.find((r) => r.metric === "irrelevant_gaps")).toMatchObject({
      delta: 0,
      changed: false,
    });
    expect(rows.find((r) => r.metric === "evidence_support")).toMatchObject({
      delta: null,
      changed: false,
    });
  });
});
