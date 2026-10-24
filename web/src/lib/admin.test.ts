import { describe, expect, it } from "vitest";

import {
  agentAtVersion,
  authorLabel,
  categoryLabel,
  changedFields,
  changedSummary,
  denialReasonLabel,
  denialsHref,
  grantableTools,
  hasDenialFilters,
  nextPatch,
  parseBudgets,
  parseDenialFilters,
  permissionChanges,
  permissionWithCategory,
  reasonError,
  shortId,
} from "@/lib/admin";
import { configVersion } from "@/test/agent-fixtures";

describe("Agent config helpers", () => {
  it("changedFields lists differing config fields in display order", () => {
    const a = configVersion(1, {
      tool_permissions: ["a.b.list", "c.d.list"],
      budgets: { x: 1, y: 2 },
    });
    const b = configVersion(2, {
      model_profile: "local-chat",
      tool_permissions: ["c.d.list", "a.b.list"],
      budgets: { y: 2, x: 1 },
    });
    expect(changedFields(a, b)).toEqual(["model_profile"]);
    expect(changedFields(a, { ...b, budgets: { x: 2 }, prompt_version: 3 })).toEqual([
      "model_profile",
      "prompt_version",
      "budgets",
    ]);
    expect(changedSummary(b, a)).toBe("Changed: model profile");
    expect(changedSummary(a, null)).toBe("First version");
  });

  it("permissionChanges splits granted and removed", () => {
    expect(permissionChanges(["a", "b"], ["b", "c"])).toEqual({ granted: ["c"], removed: ["a"] });
  });

  it("nextPatch bumps the patch number", () => {
    expect(nextPatch("0.2.9")).toBe("0.2.10");
    expect(nextPatch("v1")).toBe("v1");
  });

  it("reasonError requires 1-500 characters after trimming", () => {
    expect(reasonError("  ")).toBe("Give a reason for this version.");
    expect(reasonError("x".repeat(501))).toBe("The reason can be at most 500 characters.");
    expect(reasonError(` ${"x".repeat(500)} `)).toBeNull();
  });

  it("parseBudgets takes a JSON object of at most 20 keys", () => {
    expect(parseBudgets("")).toEqual({ ok: true, value: {} });
    expect(parseBudgets('{"max_tokens_per_run": 1}')).toEqual({
      ok: true,
      value: { max_tokens_per_run: 1 },
    });
    expect(parseBudgets("[1]").ok).toBe(false);
    expect(parseBudgets("{").ok).toBe(false);
    const many = Object.fromEntries(Array.from({ length: 21 }, (_, i) => [`k${i}`, i]));
    expect(parseBudgets(JSON.stringify(many)).ok).toBe(false);
  });

  it("authorLabel names seeded versions System", () => {
    expect(authorLabel(configVersion(1))).toBe("System");
    expect(authorLabel(configVersion(2))).toBe("[ADMIN]");
    expect(authorLabel(configVersion(2, { created_by_name: null }))).toBe("Unknown user");
  });
});

describe("Tool permission categories (Story 7.4)", () => {
  it("only read options are grantable, sorted by action", () => {
    expect(
      grantableTools([
        { action: "knowledge.chunk.read", category: "read" },
        { action: "gaps.clarification_question.send", category: "send" },
        { action: "gaps.gap.list", category: "read" },
        { action: "intake.requirement.edit", category: "write" },
      ]).map((option) => option.action),
    ).toEqual(["gaps.gap.list", "knowledge.chunk.read"]);
  });

  it("labels categories and permissions", () => {
    expect(categoryLabel("read")).toBe("Read");
    expect(categoryLabel("approve")).toBe("Approve");
    expect(permissionWithCategory("knowledge.chunk.read")).toBe("knowledge.chunk.read (read)");
  });
});

describe("Denied tool call helpers (Story 7.4)", () => {
  it("parses the URL filters, dropping invalid values and a reversed range", () => {
    const valid = { agent_id: "pm_agent", from: "2026-10-01", to: "2026-10-24" };
    expect(parseDenialFilters(valid)).toEqual(valid);
    const invalid = { agent_id: "PM Agent!", from: "2026-02-30", to: "soon" };
    expect(parseDenialFilters(invalid)).toEqual({});
    expect(parseDenialFilters({ from: "2026-10-25", to: "2026-10-24" })).toEqual({});
    expect(parseDenialFilters({ agent_id: ["pm_agent", "x_agent"] })).toEqual({
      agent_id: "pm_agent",
    });
    expect(parseDenialFilters(undefined)).toEqual({});
    expect(hasDenialFilters({})).toBe(false);
    expect(hasDenialFilters({ to: "2026-10-24" })).toBe(true);
  });

  it("builds the list URL with the filters and the page", () => {
    expect(denialsHref({})).toBe("/admin/agents/denials");
    expect(denialsHref({ to: "2026-10-24", agent_id: "pm_agent" }, 2)).toBe(
      "/admin/agents/denials?agent_id=pm_agent&to=2026-10-24&page=2",
    );
  });

  it("formats ids, the Agent and the reason", () => {
    expect(shortId("01a16ea4-1c5e-7b24-9513-3b90006f2b1e")).toBe("01a16ea4");
    expect(agentAtVersion({ agent_id: "pm_agent", semver: "0.1.0" })).toBe("pm_agent@0.1.0");
    expect(agentAtVersion({ agent_id: "pm_agent", semver: null })).toBe("pm_agent");
    expect(denialReasonLabel("tool_not_permitted")).toBe("Not permitted");
  });
});
