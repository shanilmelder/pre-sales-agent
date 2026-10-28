import { describe, expect, it } from "vitest";

import {
  actualsSubtitle,
  costText,
  currencyExponent,
  changedItems,
  errorsByLine,
  filterByIntegrationType,
  integrationTypeChipLabel,
  invalidLines,
  parseActualsDrill,
  needsReason,
  nextSort,
  parseHours,
  sortLines,
  varianceTone,
  type ActualsLine,
  type VarianceView,
} from "@/lib/actuals";

function variance(hours: number): VarianceView {
  return {
    hours,
    percent: null,
    direction: hours > 0 ? "over" : hours < 0 ? "under" : "on",
    label: `${hours} h`,
    direction_label: "",
  };
}

function line(id: string, estimate: number, recorded: number | null): ActualsLine {
  return {
    line_id: id,
    label: id,
    title: id,
    section: "integration",
    estimate_hours: estimate,
    integration_types: [],
    actual:
      recorded === null
        ? null
        : ({
            id: `${id}-a`,
            kind: "milestone",
            milestone_label: "Design",
            effort_hours: recorded,
            duration_days: 2,
            cost_minor: 100,
            currency: "EUR",
            variance_cause: null,
            note: "kept",
            failed_assumptions: [{ assumption_id: "a1", version: 1, kind: "condition", wording: "" }],
          } as unknown as ActualsLine["actual"]),
    variance: recorded === null ? null : variance(recorded - estimate),
    cost_variance: null,
  };
}

describe("actuals helpers", () => {
  it("the subtitle names the Baseline version", () => {
    expect(actualsSubtitle(3)).toBe(
      "Hours per Estimate line with a variance cause. Estimate v3 · import from file or enter by line.",
    );
  });

  it("amber over, green under, never red", () => {
    expect(varianceTone(variance(5))).toBe("text-gap");
    expect(varianceTone(variance(-2))).toBe("text-resolved");
    expect(varianceTone(variance(0))).toBe("text-text-secondary");
    expect(varianceTone(null)).toBe("text-text-secondary");
  });

  it("parses hours to one decimal place", () => {
    expect(parseHours(" 41 ")).toBe(41);
    expect(parseHours("41.5")).toBe(41.5);
    expect(parseHours("")).toBeNull();
    for (const bad of ["4.25", "-1", "abc", "1e3"]) expect(parseHours(bad)).toBe("invalid");
  });

  it("sorts by the server's variance, unrecorded lines last", () => {
    const lines = [line("a", 10, null), line("b", 10, 12), line("c", 10, 8)];
    expect(sortLines(lines, "descending").map((l) => l.line_id)).toEqual(["b", "c", "a"]);
    expect(sortLines(lines, "ascending").map((l) => l.line_id)).toEqual(["c", "b", "a"]);
    expect(sortLines(lines, "none").map((l) => l.line_id)).toEqual(["a", "b", "c"]);
    expect(nextSort("none")).toBe("descending");
    expect(nextSort("descending")).toBe("ascending");
    expect(nextSort("ascending")).toBe("none");
  });

  it("sends only changed lines, keeping a recorded Actual's other fields", () => {
    const lines = [line("a", 10, null), line("b", 10, 12), line("c", 10, 8)];
    const items = changedItems(lines, {
      a: { effort: "9", cause: "" },
      b: { effort: "12.0", cause: "" }, // unchanged
      c: { effort: "9", cause: "scope_change" },
    });
    expect(items).toEqual([
      { kind: "final", line_id: "a", effort_hours: 9, variance_cause: null },
      {
        kind: "milestone",
        milestone_label: "Design",
        effort_hours: 9,
        duration_days: 2,
        cost_minor: 100,
        currency: "EUR",
        variance_cause: "scope_change",
        note: "kept",
        failed_assumption_ids: ["a1"],
        integration_type_id: null,
        work_package_id: null,
        line_id: "c",
      },
    ]);
    expect(needsReason(lines, items)).toBe(true);
    expect(needsReason(lines, items.slice(0, 1))).toBe(false);
    expect(invalidLines({ a: { effort: "x", cause: "" } })).toEqual([
      { lineId: "a", message: "Enter hours of 0 or more, to one decimal place." },
    ]);
    // A cause with no hours is never dropped silently.
    expect(invalidLines({ a: { effort: " ", cause: "scope_change" } })).toEqual([
      { lineId: "a", message: "Enter hours to record this line" },
    ]);
    expect(changedItems(lines, { a: { effort: "", cause: "scope_change" } })).toEqual([]);
    expect(invalidLines({ a: { effort: "", cause: "" } })).toEqual([]);
  });

  it("maps the API's errors to their lines", () => {
    const items = [{ kind: "final" as const, line_id: "a", effort_hours: 1 }];
    const found = errorsByLine(
      [
        { item: 0, field: "variance_cause", message: "m" },
        { item: null, field: "reason", message: "r" },
      ],
      items,
    );
    expect(Object.keys(found.byLine)).toEqual(["a"]);
    expect(found.general.map((e) => e.field)).toEqual(["reason"]);
  });
});


describe("costText", () => {
  it("uses the currency's own exponent", () => {
    expect(currencyExponent("EUR")).toBe(2);
    expect(currencyExponent("JPY")).toBe(0);
    expect(costText(480000, "EUR")).toBe("EUR 4,800.00");
    expect(costText(4800, "JPY")).toBe("JPY 4,800");
    expect(costText(null, "EUR")).toBe("—");
  });
});

describe("the drill-down from Reports (Story 10.4)", () => {
  const IT = "0190C000-0000-7000-8000-0000000000A1";
  const tagged = { ...line("L1", 10, 12), integration_types: [{ id: IT.toLowerCase(), kind: "integration_type" as const, name: "SAP EWM" }] };
  const bare = line("L2", 10, null);

  it("reads the sort and the Integration Type from the URL, ignoring anything else", () => {
    expect(parseActualsDrill({ sort: "variance_desc", integration_type: IT })).toEqual({
      sort: "descending",
      integrationType: IT.toLowerCase(),
    });
    expect(parseActualsDrill({ sort: "variance_asc", integration_type: "none" })).toEqual({
      sort: "ascending",
      integrationType: "none",
    });
    expect(parseActualsDrill({ sort: "title", integration_type: "nope" })).toEqual({
      sort: "none",
      integrationType: null,
    });
    expect(parseActualsDrill(undefined)).toEqual({ sort: "none", integrationType: null });
  });

  it("filters lines by their Integration Types and names the chip", () => {
    const lines = [tagged, bare];
    expect(filterByIntegrationType(lines, null)).toEqual(lines);
    expect(filterByIntegrationType(lines, IT.toLowerCase())).toEqual([tagged]);
    expect(filterByIntegrationType(lines, "none")).toEqual([bare]);
    expect(integrationTypeChipLabel(lines, IT.toLowerCase())).toBe("Integration Type: SAP EWM");
    expect(integrationTypeChipLabel(lines, "none")).toBe("Integration Type: No Integration Type");
    expect(integrationTypeChipLabel(lines, "other")).toBe("Integration Type: Unknown");
  });
});
