import { describe, expect, it } from "vitest";

import { applyChecklistFilters, checklistProducts } from "@/lib/checklists";
import {
  checklistsHref,
  checklistsText,
  COVERAGE_STATUSES,
  seededFilters,
  sourcesHref,
  sourcesText,
  withOption,
} from "@/lib/coverage";
import { checklist, TYPE_ID } from "@/test/checklist-fixtures";

const OTHER_TYPE = "00000000-0000-7000-8000-000000000009";

describe("coverage words", () => {
  it("labels each status, with the mockup's tones", () => {
    expect(COVERAGE_STATUSES).toEqual({
      ready: { label: "Ready", tone: "resolved" },
      partial: { label: "Partial", tone: "gap" },
      missing: { label: "Missing", tone: "blocker" },
    });
  });

  it.each([
    [0, 0, "None"],
    [1, 0, "1"],
    [3, 1, "3 (1 stale)"],
    [2, 2, "Stale (2)"],
  ])("reads %i Sources with %i stale as %s", (sources, stale, text) => {
    expect(sourcesText({ sources, stale })).toBe(text);
  });

  it("reads no Checklists as None", () => {
    expect(checklistsText({ checklists: 0 })).toBe("None");
    expect(checklistsText({ checklists: 4 })).toBe("4");
  });
});

describe("filter links", () => {
  it("carry the product and the Integration Type", () => {
    expect(sourcesHref("SAP EWM & co", TYPE_ID)).toBe(
      `/knowledge?product=SAP+EWM+%26+co&type=${TYPE_ID}`,
    );
    expect(checklistsHref("HubSpot", TYPE_ID)).toBe(
      `/knowledge/checklists?product=HubSpot&type=${TYPE_ID}`,
    );
  });

  it("are read back, ignoring anything malformed", () => {
    expect(seededFilters({ product: " SAP EWM ", type: TYPE_ID.toUpperCase() })).toEqual({
      product: "SAP EWM",
      integrationTypeId: TYPE_ID,
    });
    expect(seededFilters({ product: ["A", "B"], type: "not-a-uuid" })).toEqual({
      product: "A",
      integrationTypeId: "",
    });
    expect(seededFilters({ product: "x".repeat(201) })).toEqual({
      product: "",
      integrationTypeId: "",
    });
    expect(seededFilters(undefined)).toEqual({ product: "", integrationTypeId: "" });
  });

  it("select an existing option ignoring case, or add the product", () => {
    expect(withOption(["AutoStore", "SAP"], "autostore")).toEqual({
      options: ["AutoStore", "SAP"],
      selected: "AutoStore",
    });
    expect(withOption(["SAP"], "HubSpot")).toEqual({
      options: ["HubSpot", "SAP"],
      selected: "HubSpot",
    });
    expect(withOption(["SAP"], "")).toEqual({ options: ["SAP"], selected: "" });
  });
});

describe("applyChecklistFilters", () => {
  const both = checklist(1, { name: "Both" });
  const productsOnly = checklist(2, { name: "Products only", integration_types: [] });
  const typesOnly = checklist(3, { name: "Types only", products: [] });
  const industryOnly = checklist(4, {
    name: "Industry only",
    products: [],
    integration_types: [],
    industry: "Retail",
  });
  const elsewhere = checklist(5, { name: "Elsewhere", products: ["SAP"] });
  const retired = checklist(7, {
    name: "Retired",
    status: "retired",
    retired: true,
    retired_reason: "Old",
  });
  const all = [both, productsOnly, typesOnly, industryOnly, elsewhere, retired];
  const names = (product: string, integrationTypeId: string) =>
    applyChecklistFilters(all, { product, integrationTypeId }).map((c) => c.name);

  it("matches Coverage's pairing rule", () => {
    expect(names(" autostore ", TYPE_ID)).toEqual(["Both", "Products only", "Types only"]);
    expect(names("AutoStore", OTHER_TYPE)).toEqual(["Products only"]);
    expect(names("HubSpot", TYPE_ID)).toEqual(["Types only"]);
    expect(names("", "")).toEqual(all.map((c) => c.name));
  });

  it("leaves retired Checklists out only when a filter is set", () => {
    expect(names("AutoStore", "")).not.toContain("Retired");
    expect(names("", TYPE_ID)).not.toContain("Retired");
    expect(names("", "")).toContain("Retired");
  });

  it("never matches an industry-only Checklist on product or Integration Type", () => {
    expect(names("AutoStore", "")).not.toContain("Industry only");
    expect(names("", TYPE_ID)).not.toContain("Industry only");
  });

  it("lists the distinct products, sorted", () => {
    expect(checklistProducts([...all, checklist(6, { products: ["autostore", " Zed "] })])).toEqual([
      "AutoStore",
      "SAP",
      "Zed",
    ]);
  });
});
