import { describe, expect, it } from "vitest";

import {
  applySuggestions,
  clearSuggestions,
  EMPTY_VALUES,
  addDays,
  fieldCount,
  filledCount,
  type ImportSuggestions,
  withDefaultDate,
} from "./opportunity-import";

const SUGGESTIONS: ImportSuggestions = {
  title: { value: "Riverside DC automation", quote: "Riverside DC" },
  customer_name: { value: "Meridian Fresh Foods", quote: "Meridian Fresh Foods" },
  industry: null,
  products: [
    { value: "Goods-to-person picking", quote: "goods-to-person" },
    { value: "WMS integration", quote: "the WMS" },
  ],
  target_proposal_date: { value: "2026-10-23", quote: "Proposal due: 23 October 2026." },
  industry_inferred: false,
};

describe("applySuggestions", () => {
  it("fills only empty fields and records each quote", () => {
    const { values, fromFile } = applySuggestions(
      { ...EMPTY_VALUES, customer_name: "Typed", products: "  " },
      SUGGESTIONS,
    );
    expect(values).toEqual({
      title: "Riverside DC automation",
      customer_name: "Typed",
      industry: "",
      products: "Goods-to-person picking\nWMS integration",
      target_proposal_date: "2026-10-23",
    });
    expect(Object.keys(fromFile).sort()).toEqual(["products", "target_proposal_date", "title"]);
    expect(fromFile.products?.quote).toBe(
      "Goods-to-person picking: “goods-to-person” · WMS integration: “the WMS”",
    );
    expect(fieldCount(fromFile)).toBe("3 fields");
    expect(fieldCount({ title: { value: "a", quote: "a" } })).toBe("1 field");
  });

  it("clearSuggestions empties only fields still holding the file's value", () => {
    const { values, fromFile } = applySuggestions(EMPTY_VALUES, SUGGESTIONS);
    const edited = { ...values, title: "My own title" };
    expect(clearSuggestions(edited, fromFile)).toEqual({ ...EMPTY_VALUES, title: "My own title" });
  });
});

describe("inferred industry and the default date", () => {
  it("marks an inferred industry", () => {
    const { fromFile } = applySuggestions(EMPTY_VALUES, {
      ...SUGGESTIONS,
      industry: { value: "Food & grocery distribution", quote: "ships groceries" },
      industry_inferred: true,
    });
    expect(fromFile.industry?.kind).toBe("inferred");
    expect(fromFile.customer_name?.kind).toBe("file");
  });

  it("adds 30 days across month and year ends", () => {
    expect(addDays("2026-10-06", 30)).toBe("2026-11-05");
    expect(addDays("2026-12-15", 30)).toBe("2027-01-14");
  });

  it("proposes the default only when no date is typed or suggested", () => {
    const empty = withDefaultDate(EMPTY_VALUES, {}, "2026-10-06");
    expect(empty.values.target_proposal_date).toBe("2026-11-05");
    expect(empty.fromFile.target_proposal_date?.kind).toBe("default");
    expect(filledCount(empty.fromFile)).toBe(0);
    expect(fieldCount(empty.fromFile)).toBe("0 fields");

    const typed = { ...EMPTY_VALUES, target_proposal_date: "2027-01-01" };
    expect(withDefaultDate(typed, {}, "2026-10-06").values).toBe(typed);
    const suggested = applySuggestions(EMPTY_VALUES, SUGGESTIONS);
    expect(withDefaultDate(suggested.values, suggested.fromFile, "2026-10-06").values).toBe(
      suggested.values,
    );
  });
});
