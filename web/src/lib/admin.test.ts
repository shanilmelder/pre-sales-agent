import { describe, expect, it } from "vitest";

import {
  authorLabel,
  changedFields,
  changedSummary,
  nextPatch,
  parseBudgets,
  permissionChanges,
  reasonError,
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
