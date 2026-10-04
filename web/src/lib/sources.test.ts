import { describe, expect, it } from "vitest";

import { isParsePending, mergeSources, parseFailureReason, type Source } from "@/lib/sources";

function source(n: number, overrides: Partial<Source> = {}): Source {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    kind: "document",
    filename: `file-${n}.pdf`,
    version: 1,
    version_count: 1,
    size_bytes: 10,
    uploaded_by: { id: "00000000-0000-7000-8000-0000000000a1", name: "[UPLOADER]" },
    uploaded_at: "2026-10-04T13:05:00Z",
    created_at: "2026-10-04T13:05:00Z",
    parse: { status: "queued", error_code: null },
    ...overrides,
  };
}

describe("mergeSources", () => {
  it("takes the server's rows, including their newer parse state", () => {
    const local = [source(1)];
    const server = [source(1, { parse: { status: "parsed", error_code: null } })];
    expect(mergeSources(server, local)).toEqual(server);
  });

  it("keeps Sources added locally since the read began, newest first", () => {
    const old = source(1);
    const addedA = source(2);
    const addedB = source(3);
    const merged = mergeSources([old], [addedB, addedA, old]);
    expect(merged.map((s) => s.id)).toEqual([addedB.id, addedA.id, old.id]);
  });

  it("keeps a newer local version over the server's older one, in place", () => {
    const first = source(1);
    const other = source(2);
    const newer = source(1, { version: 2, version_count: 2, filename: "again.pdf" });
    const merged = mergeSources([other, first], [other, newer]);
    expect(merged).toEqual([other, newer]);
  });

  it("prefers the server when it has the same or a newer version", () => {
    const local = source(1, { version: 2 });
    const server = source(1, { version: 3, parse: { status: "parsing", error_code: null } });
    expect(mergeSources([server], [local])).toEqual([server]);
  });

  it("drops nothing the server sent, even if this page never showed it", () => {
    const fromElsewhere = source(9);
    expect(mergeSources([fromElsewhere], [])).toEqual([fromElsewhere]);
  });
});

describe("parse helpers", () => {
  it("only Queued and Parsing are pending", () => {
    expect(isParsePending(source(1))).toBe(true);
    expect(isParsePending(source(1, { parse: { status: "parsing", error_code: null } }))).toBe(true);
    expect(isParsePending(source(1, { parse: { status: "parsed", error_code: null } }))).toBe(false);
    expect(isParsePending(source(1, { parse: null }))).toBe(false);
  });

  it("an unknown or missing failure code reads as unreadable", () => {
    expect(parseFailureReason(null)).toBe("The file couldn't be read");
    expect(parseFailureReason("timeout")).toBe("Parsing took too long");
  });
});
