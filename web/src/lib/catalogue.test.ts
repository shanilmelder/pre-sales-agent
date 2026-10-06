import { describe, expect, it } from "vitest";

import { entry } from "@/test/catalogue-fixtures";
import {
  fieldError,
  groupByKind,
  staleMessage,
  upsert,
} from "@/lib/catalogue";

describe("catalogue helpers", () => {
  it("groups entries into the two kinds, always both", () => {
    const groups = groupByKind([entry(1), entry(2, { kind: "work_package" })]);
    expect(groups.map((g) => g.plural)).toEqual(["Integration Types", "Work Packages"]);
    expect(groups.map((g) => g.entries.length)).toEqual([1, 1]);
    expect(groupByKind([]).every((g) => g.entries.length === 0)).toBe(true);
  });

  it("validates fields like the API, after trimming", () => {
    expect(fieldError("code", "  ")).toBe("The code is required.");
    expect(fieldError("code", "x".repeat(41))).toBe("The code must be at most 40 characters.");
    expect(fieldError("code", ` ${"x".repeat(40)} `)).toBeNull();
    expect(fieldError("definition", "x".repeat(2001))).toBe(
      "The definition must be at most 2,000 characters.",
    );
    expect(fieldError("reason", "x".repeat(500))).toBeNull();
    expect(fieldError("name", "😀".repeat(120))).toBeNull();
  });

  it("words the 412 notice", () => {
    expect(staleMessage("[ADMIN]")).toBe("Changed by [ADMIN] since you opened it.");
    expect(staleMessage(null)).toBe("Changed by another administrator since you opened it.");
  });

  it("upserts keeping kinds and names in order", () => {
    const list = upsert(
      [entry(1, { name: "b" }), entry(2, { name: "d" })],
      entry(3, { name: "C" }),
    );
    expect(list.map((e) => e.name)).toEqual(["b", "C", "d"]);
    const replaced = upsert(list, entry(3, { name: "a", row_version: 2 }));
    expect(replaced.map((e) => e.name)).toEqual(["a", "b", "d"]);
  });
});
