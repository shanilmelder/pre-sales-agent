import { describe, expect, it } from "vitest";

import { source } from "@/test/knowledge-fixtures";

import {
  applyFilters,
  canRegister,
  canWrite,
  EMPTY_STATE,
  exceedsTransportLimit,
  fieldError,
  formatDate,
  formatSize,
  hasFilters,
  isParsePending,
  mergeSources,
  NO_FILTERS,
  ownersOf,
  parseFailureReason,
  productsOf,
  upsert,
} from "./knowledge-sources";

describe("knowledge source helpers", () => {
  it("has the spec's empty state", () => {
    expect(EMPTY_STATE).toBe(
      "No Knowledge Sources yet. Upload product or integration documentation to start.",
    );
  });

  it("filters by product (ignoring case), Integration Type, owner and stale", () => {
    const a = source(1, { product: "AutoStore" });
    const b = source(2, {
      product: "Pick station",
      stale: true,
      integration_types: [{ id: "t2", code: "EDI", name: "EDI", retired: false }],
    });
    const all = [a, b];
    expect(applyFilters(all, NO_FILTERS)).toEqual(all);
    expect(applyFilters(all, { ...NO_FILTERS, product: "autostore" })).toEqual([a]);
    expect(applyFilters(all, { ...NO_FILTERS, integrationTypeId: "t2" })).toEqual([b]);
    expect(applyFilters(all, { ...NO_FILTERS, ownerId: a.owner.id })).toEqual([a]);
    expect(applyFilters(all, { ...NO_FILTERS, staleOnly: true })).toEqual([b]);
    expect(hasFilters(NO_FILTERS)).toBe(false);
    expect(hasFilters({ ...NO_FILTERS, staleOnly: true })).toBe(true);
  });

  it("lists distinct products and owners", () => {
    const list = [source(1), source(2, { product: "autostore" }), source(3, { product: "Zed" })];
    expect(productsOf(list)).toEqual(["AutoStore", "Zed"]);
    expect(ownersOf(list).map((o) => o.name)).toEqual(["[OWNER 1]", "[OWNER 2]", "[OWNER 3]"]);
  });

  it("only administrators and the owner may write, and never on a retired Source", () => {
    const s = source(1);
    expect(canWrite(s, { id: s.owner.id, roles: ["commercial"] })).toBe(true);
    expect(canWrite(s, { id: "other", roles: ["platform_administrator"] })).toBe(true);
    expect(canWrite(s, { id: "other", roles: ["engineering_reviewer"] })).toBe(false);
    expect(
      canWrite({ ...s, retired: true }, { id: s.owner.id, roles: ["platform_administrator"] }),
    ).toBe(false);
    expect(canRegister(["platform_administrator"])).toBe(true);
    expect(canRegister(["pm_reviewer"])).toBe(false);
    expect(canRegister(["sales_representative"])).toBe(false);
  });

  it("knows when a parse is pending and why one failed", () => {
    expect(isParsePending(source(1, { parse: { status: "queued", error_code: null } }))).toBe(true);
    expect(isParsePending(source(1, { parse: { status: "parsing", error_code: null } }))).toBe(
      true,
    );
    expect(isParsePending(source(1))).toBe(false);
    expect(parseFailureReason("no_text")).toBe("No text found — scanned PDF?");
    expect(parseFailureReason(null)).toBe("The file couldn't be read");
  });

  it("upserts keeping the longest-unreviewed first", () => {
    const old = source(1, { last_reviewed_on: "2025-01-01" });
    const fresh = source(2);
    const reviewed = { ...old, last_reviewed_on: "2026-10-07", row_version: 2 };
    expect(upsert([old, fresh], reviewed).map((s) => s.id)).toEqual([fresh.id, old.id]);
    expect(upsert([fresh], old).map((s) => s.id)).toEqual([old.id, fresh.id]);
  });

  it("keeps what the page changed since a poll began", () => {
    const stored = source(1);
    const mine = { ...stored, row_version: 2, title: "Mine" };
    const added = source(2);
    expect(mergeSources([stored], [mine, added]).map((s) => s.title)).toEqual([
      "Guide 2",
      "Mine",
    ]);
    const newer = { ...stored, row_version: 3, title: "Theirs" };
    expect(mergeSources([newer], [mine])[0]?.title).toBe("Theirs");
  });

  it("mirrors the API's field rules", () => {
    expect(fieldError("title", "  ")).toBe("The title is required.");
    expect(fieldError("title", "x".repeat(201))).toBe("The title must be at most 200 characters.");
    expect(fieldError("product version", "x".repeat(60))).toBeNull();
  });

  it("formats dates and sizes", () => {
    expect(formatDate("2026-10-07")).toBe("7 Oct 2026");
    expect(formatSize(500)).toBe("500 B");
    expect(formatSize(2048)).toBe("2.0 KB");
    expect(formatSize(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(exceedsTransportLimit(51 * 1024 * 1024)).toBe(true);
    expect(exceedsTransportLimit(1024)).toBe(false);
  });
});
