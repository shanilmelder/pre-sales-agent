import { describe, expect, it } from "vitest";

import {
  filtersHref,
  hasFilters,
  isCalendarDate,
  parseFilters,
  withFilter,
} from "@/app/opportunities/filters";

const OWNER = "00000000-0000-7000-8000-0000000000a1";

describe("parseFilters", () => {
  it("reads every filter from the query", () => {
    expect(
      parseFilters({
        status: "intake",
        owner: OWNER,
        product: "  CRM ",
        from: "2026-11-01",
        to: "2026-11-30",
        page: "2",
      }),
    ).toEqual({
      status: "intake",
      owner: OWNER,
      product: "CRM",
      from: "2026-11-01",
      to: "2026-11-30",
    });
  });

  it("reads URLSearchParams and takes the first of repeated values", () => {
    expect(parseFilters(new URLSearchParams("status=closed&product=a&product=b"))).toEqual({
      status: "closed",
      product: "a",
    });
    expect(parseFilters({ status: ["gaps_open", "closed"] })).toEqual({ status: "gaps_open" });
  });

  it("lowercases an uppercase owner UUID", () => {
    expect(parseFilters({ owner: OWNER.toUpperCase() })).toEqual({ owner: OWNER });
  });

  it("drops invalid values and keeps the valid ones", () => {
    expect(
      parseFilters({
        status: "Intake",
        owner: "not-a-uuid",
        product: "   ",
        from: "2026-02-30",
        to: "2026-12-01",
      }),
    ).toEqual({ to: "2026-12-01" });
    expect(parseFilters({ status: "toString", product: "x".repeat(101) })).toEqual({});
    expect(parseFilters({ product: "x".repeat(100) }).product).toHaveLength(100);
    expect(parseFilters(undefined)).toEqual({});
  });

  it("drops both dates of a reversed range", () => {
    expect(parseFilters({ from: "2026-12-01", to: "2026-11-01", status: "intake" })).toEqual({
      status: "intake",
    });
    expect(parseFilters({ from: "2026-11-01", to: "2026-11-01" })).toEqual({
      from: "2026-11-01",
      to: "2026-11-01",
    });
  });
});

describe("isCalendarDate", () => {
  it.each([
    ["2026-11-01", true],
    ["2028-02-29", true],
    ["2026-02-29", false],
    ["2026-13-01", false],
    ["2026-1-01", false],
    ["tomorrow", false],
  ])("%s → %s", (value, expected) => {
    expect(isCalendarDate(value)).toBe(expected);
  });
});

describe("filtersHref", () => {
  it("serialises the filters in a fixed order and the page past the first", () => {
    expect(filtersHref("/opportunities", {})).toBe("/opportunities");
    expect(filtersHref("/opportunities", {}, 3)).toBe("/opportunities?page=3");
    expect(
      filtersHref(
        "/opportunities",
        { to: "2026-11-30", product: "Pick station", owner: OWNER, status: "intake" },
        2,
      ),
    ).toBe(
      `/opportunities?status=intake&owner=${OWNER}&product=Pick+station&to=2026-11-30&page=2`,
    );
  });

  it("round-trips through parseFilters", () => {
    const filters = { status: "closed", owner: OWNER, product: "A&B", from: "2026-11-01" } as const;
    const href = filtersHref("/opportunities", filters, 4);
    expect(parseFilters(new URLSearchParams(href.split("?")[1]))).toEqual(filters);
  });
});

describe("withFilter and hasFilters", () => {
  it("sets and clears one filter", () => {
    const set = withFilter({ status: "intake" }, "owner", OWNER);
    expect(set).toEqual({ status: "intake", owner: OWNER });
    expect(withFilter(set, "status", "")).toEqual({ owner: OWNER });
    expect(hasFilters({})).toBe(false);
    expect(hasFilters({ to: "2026-11-30" })).toBe(true);
  });
});
