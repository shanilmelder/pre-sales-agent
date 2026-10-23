import { describe, expect, it } from "vitest";

import {
  agentPillLabel,
  conflictNote,
  headerCounts,
  openCountLabel,
  positionRole,
  positionVersion,
  resolvedLine,
  resolvedTag,
  rowSubline,
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
    finding: null,
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
  it("names positions by role", () => {
    expect(positionRole(position({}))).toBe("Engineering");
    expect(positionRole(position({ agent: "pm_agent" }))).toBe("PM");
    expect(positionRole(ESTIMATE)).toBe("Estimate v3");
  });

  it("labels the position cards' agent pill and version", () => {
    expect(agentPillLabel(position({}))).toBe("Engineering Agent");
    expect(agentPillLabel(position({ agent: "pm_agent" }))).toBe("PM Agent");
    expect(agentPillLabel(ESTIMATE)).toBe("Estimate v3");
    expect(positionVersion(position({}))).toBe("Assessment v2");
    expect(positionVersion(position({ assessment_version: null }))).toBeNull();
    expect(positionVersion(ESTIMATE)).toBeNull();
  });

  it("builds the header counts, row sub-lines and the decision note", () => {
    const c = (id: string, status: Conflict["status"]) => ({ id, status }) as Conflict;
    expect(headerCounts([c("a", "open"), c("b", "escalated"), c("c", "resolved")])).toBe(
      "2 open · 1 resolved",
    );
    expect(headerCounts([])).toBe("0 open · 0 resolved");
    const r1 = { id: "r", version: 1, label: "R1", excerpt: "" };
    expect(rowSubline({ type: "effort", requirement: r1, detected_by: "rule" })).toBe("Effort · R1");
    expect(rowSubline({ type: "security", requirement: null, detected_by: "rule" })).toBe(
      "Security",
    );
    expect(rowSubline({ type: "architecture", requirement: r1, detected_by: "semantic" })).toBe(
      "Architecture · R1 · Detected from text",
    );
    expect(conflictNote({ type: "effort", severity: "medium", detected_by: "rule" })).toBe(
      "Effort Conflict · Medium severity",
    );
    expect(conflictNote({ type: "scope", severity: "critical", detected_by: "semantic" })).toBe(
      "Scope Conflict · Critical severity · Detected from text",
    );
  });

  it("tags and describes a resolved row", () => {
    expect(resolvedTag({ resolved_by_name: "Alex" })).toBe("Resolved by Alex");
    expect(resolvedTag({ resolved_by_name: null })).toBe("No longer present");
    const base = {
      status: "resolved",
      resolved_by_name: null,
      entered_position: null,
      chosen_position: null,
      positions: [position({})],
      resolution_reason: "No longer present in PM Assessment v2",
    } as unknown as Conflict;
    expect(resolvedLine(base)).toBe("No longer present in PM Assessment v2");
    expect(resolvedLine({ ...base, resolved_by_name: "Alex", chosen_position: 1 })).toBe(
      "Engineering's position, 24 h",
    );
    expect(
      resolvedLine({ ...base, resolved_by_name: "Alex", entered_position: "In scope: PM in v2" }),
    ).toBe("In scope: PM in v2");
    expect(resolvedLine({ ...base, resolution_reason: null })).toBeNull();
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

describe("decision display (Story 6.3)", () => {
  it("reads entered hours as the API does", async () => {
    const { isEnteredHours } = await import("@/lib/conflicts");
    for (const ok of ["48", "48.5", "48 h", "0", "2000"]) expect(isEnteredHours(ok)).toBe(true);
    for (const bad of ["about two days", "48.25", "-4", "2001", ""]) {
      expect(isEnteredHours(bad)).toBe(false);
    }
  });

  it("labels an escalation and an earlier decision", async () => {
    const { escalatedLabel, previousDecisionLabel } = await import("@/lib/conflicts");
    expect(escalatedLabel({ escalated_to: { id: "x", name: "Sam" } })).toBe("Escalated to Sam");
    expect(escalatedLabel({ escalated_to: null })).toBeNull();
    expect(
      previousDecisionLabel({ previous_decision: { name: "Alex", resolved_at: "2026-10-07" } }),
    ).toBe("Resolved earlier by Alex; positions have changed.");
  });
});

describe("estimateEffect (Story 6.3)", () => {
  it("says why a decision did not change the Estimate", async () => {
    const { estimateEffect } = await import("@/lib/conflicts");
    const base = { applied_hours: null } as unknown as Parameters<typeof estimateEffect>[0];
    expect(estimateEffect({ ...base, not_applied: "not_permitted" })).toBe(
      "Not applied: you can't edit the Estimate.",
    );
    expect(estimateEffect({ ...base, not_applied: "no_line" })).toBe(
      "Not applied: no Estimate line covers it.",
    );
    expect(estimateEffect({ ...base, applied_hours: 100, not_applied: null })).toBe(
      "Estimate line set to 100 h.",
    );
  });
});
