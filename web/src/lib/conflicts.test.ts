import { describe, expect, it } from "vitest";

import {
  openCountLabel,
  positionRole,
  positionSource,
  positionsSummary,
  sections,
  statusInfo,
  typeLabel,
  type Conflict,
  type ConflictPosition,
} from "@/lib/conflicts";

function position(overrides: Partial<ConflictPosition>): ConflictPosition {
  return {
    position: 1,
    source: "assessment",
    agent: "engineering_agent",
    assessment_id: "00000000-0000-7000-8000-0000000000a1",
    assessment_version: 2,
    estimate_version_id: null,
    estimate_version: null,
    summary: "24 h",
    value: 24,
    requirement: null,
    ...overrides,
  };
}

const ESTIMATE = position({
  source: "estimate",
  agent: null,
  assessment_id: null,
  assessment_version: null,
  estimate_version_id: "00000000-0000-7000-8000-0000000000e3",
  estimate_version: 3,
  summary: "131 h",
});

describe("conflicts display", () => {
  it("names positions by role and source version", () => {
    expect(positionRole(position({}))).toBe("Engineering");
    expect(positionRole(position({ agent: "pm_agent" }))).toBe("PM");
    expect(positionSource(position({}))).toBe("Engineering Assessment v2");
    expect(positionSource(position({ agent: "security_agent", assessment_version: 1 }))).toBe(
      "Security Assessment v1",
    );
    expect(positionRole(ESTIMATE)).toBe("Estimate v3");
    expect(positionSource(ESTIMATE)).toBe("Estimate v3");
  });

  it("summarises the positions in a row", () => {
    expect(
      positionsSummary([
        position({}),
        position({ position: 2, agent: "pm_agent", summary: "Not sized", value: null }),
      ]),
    ).toBe("Engineering: 24 h · PM: not sized");
    expect(
      positionsSummary([
        position({ summary: "Proceed", value: null }),
        position({ position: 2, agent: "security_agent", summary: "Do not proceed", value: null }),
      ]),
    ).toBe("Engineering: proceed · Security: do not proceed");
    expect(positionsSummary([position({ summary: "60 h" }), ESTIMATE])).toBe(
      "Engineering: 60 h · Estimate v3: 131 h",
    );
  });

  it("labels types and statuses, each status with an icon", () => {
    expect(typeLabel("scope")).toBe("Scope");
    expect(typeLabel("assumption")).toBe("Assumption");
    expect(statusInfo("open")).toMatchObject({ label: "Open", tone: "text-blocker" });
    expect(statusInfo("escalated")).toMatchObject({ label: "Escalated", tone: "text-gap" });
    expect(statusInfo("resolved").tone).toBe("text-resolved");
    expect(openCountLabel(3)).toBe("3 open");
  });

  it("splits the Conflicts into Open and Resolved, keeping their order", () => {
    const c = (id: string, status: Conflict["status"]) => ({ id, status }) as Conflict;
    const { open, resolved } = sections([
      c("a", "open"),
      c("b", "escalated"),
      c("c", "resolved"),
      c("d", "negotiating"),
    ]);
    expect(open.map((x) => x.id)).toEqual(["a", "b", "d"]);
    expect(resolved.map((x) => x.id)).toEqual(["c"]);
  });
});
