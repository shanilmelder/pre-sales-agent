import { describe, expect, it } from "vitest";

import { checklist, withDraft } from "@/test/checklist-fixtures";
import { permissionsFor } from "@/test/permissions";

import {
  canAuthor,
  checklistStatus,
  draftInput,
  fieldError,
  parseProducts,
  scopeText,
} from "./checklists";

describe("checklists", () => {
  it("lets reviewers and administrators author, nobody else", () => {
    for (const role of [
      "engineering_reviewer",
      "pm_reviewer",
      "security_reviewer",
      "platform_administrator",
    ] as const) {
      expect(canAuthor(permissionsFor([role]))).toBe(true);
    }
    for (const role of ["presales_engineer", "sales_representative", "commercial"] as const) {
      expect(canAuthor(permissionsFor([role]))).toBe(false);
    }
  });

  it("parses products like the API stores them", () => {
    expect(parseProducts(" AutoStore, autostore ,, SAP ")).toEqual(["AutoStore", "SAP"]);
    expect(parseProducts("  ")).toEqual([]);
  });

  it("says where a Checklist stands and what it covers", () => {
    expect(checklistStatus(checklist(1))).toBe("Published v1");
    expect(checklistStatus(checklist(1, { current_version: null }))).toBe("Draft");
    expect(checklistStatus(checklist(1, { retired: true }))).toBe("Retired");
    expect(scopeText(checklist(1, { industry: "Retail" }))).toBe("AutoStore · Retail · SAP IDoc");
    expect(scopeText(checklist(1, { products: [], integration_types: [] }))).toBe("No scope");
  });

  it("turns the stored draft into the PUT body, keeping item ids", () => {
    const body = draftInput(withDraft(checklist(1)).draft!);
    expect(body.integration_type_ids).toEqual(["00000000-0000-7000-8000-000000000001"]);
    expect(body.items.map((i) => i.id)).toEqual([
      "00000000-0000-7000-8000-000000000301",
      "00000000-0000-7000-8000-000000000302",
    ]);
  });

  it("checks the name and reason", () => {
    expect(fieldError("name", " ")).toBe("The name is required.");
    expect(fieldError("name", "x".repeat(201))).toMatch(/at most 200/);
    expect(fieldError("reason", "Old")).toBeNull();
  });
});
