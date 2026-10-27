import { describe, expect, it } from "vitest";

import { group, variance } from "@/test/report-fixtures";

import {
  groupSubline,
  nextSort,
  parseReportParams,
  reportHref,
  reportQuery,
  sortGroups,
} from "./reports";

const WP = "0190C000-0000-7000-8000-000000000001";

describe("parseReportParams", () => {
  it("defaults to Integration Type without milestones", () => {
    expect(parseReportParams(undefined)).toEqual({
      groupBy: "integration_type",
      includeMilestones: false,
    });
  });

  it("reads every parameter, from an object or URLSearchParams", () => {
    const search = {
      group_by: "cause",
      product: " Payments ",
      work_package_id: WP,
      cause: "scope_change",
      closed_from: "2026-01-01",
      closed_to: "2026-06-30",
      include_milestones: "true",
    };
    const expected = {
      groupBy: "cause",
      product: "Payments",
      workPackageId: WP.toLowerCase(),
      cause: "scope_change",
      closedFrom: "2026-01-01",
      closedTo: "2026-06-30",
      includeMilestones: true,
    };
    expect(parseReportParams(search)).toEqual(expected);
    expect(parseReportParams(new URLSearchParams(search))).toEqual(expected);
    expect(parseReportParams({ group_by: ["product", "cause"] }).groupBy).toBe("product");
  });

  it("drops invalid values so a hand-edited URL never gets a 422", () => {
    expect(
      parseReportParams({
        group_by: "region",
        product: "x".repeat(101),
        work_package_id: "not-a-uuid",
        cause: "weather",
        closed_from: "2026-02-30",
        include_milestones: "yes",
      }),
    ).toEqual({ groupBy: "integration_type", includeMilestones: false });
  });

  it("a reversed date range drops both dates", () => {
    expect(parseReportParams({ closed_from: "2026-06-30", closed_to: "2026-01-01" })).toEqual({
      groupBy: "integration_type",
      includeMilestones: false,
    });
  });
});

describe("reportHref and reportQuery", () => {
  it("round-trips through the URL, leaving defaults out", () => {
    expect(reportHref(parseReportParams({}))).toBe("/reports");
    const href = "/reports?group_by=product&cause=customer_delay&closed_to=2026-06-30&include_milestones=true";
    const params = parseReportParams(new URLSearchParams(href.split("?")[1]));
    expect(reportHref(params)).toBe(href);
    expect(reportQuery(params)).toEqual({
      group_by: "product",
      product: undefined,
      work_package_id: undefined,
      cause: "customer_delay",
      closed_from: undefined,
      closed_to: "2026-06-30",
      include_milestones: true,
    });
  });
});

describe("sorting", () => {
  it("cycles descending, ascending, off; names start ascending", () => {
    expect(nextSort(null, "variance")).toEqual({ key: "variance", order: "descending" });
    expect(nextSort({ key: "variance", order: "descending" }, "variance")).toEqual({
      key: "variance",
      order: "ascending",
    });
    expect(nextSort({ key: "variance", order: "ascending" }, "variance")).toBeNull();
    expect(nextSort({ key: "variance", order: "ascending" }, "label")).toEqual({
      key: "label",
      order: "ascending",
    });
    expect(nextSort({ key: "label", order: "descending" }, "label")).toBeNull();
  });

  it("variance sorts by percent, and a group with no estimate by its hours", () => {
    const groups = [
      group({ key: "a", variance: variance(5, 5) }),
      group({ key: "b", variance: variance(null, 12) }),
      group({ key: "c", variance: variance(30, 3) }),
    ];
    const keys = (state: Parameters<typeof sortGroups>[1]) => sortGroups(groups, state).map((g) => g.key);
    expect(keys({ key: "variance", order: "descending" })).toEqual(["c", "b", "a"]);
    expect(keys(null)).toEqual(["a", "b", "c"]);
    // A copy: the server's order is kept.
    expect(groups.map((g) => g.key)).toEqual(["a", "b", "c"]);
  });
});

describe("groupSubline", () => {
  it("counts Opportunities and failed Assumptions", () => {
    expect(groupSubline(group({ opportunity_count: 3, failed_assumptions: 0 }))).toBe(
      "3 Opportunities · 0 failed Assumptions",
    );
    expect(groupSubline(group())).toBe("1 Opportunity · 1 failed Assumption");
  });
});
