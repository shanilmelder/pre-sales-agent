import type { Checklist, ChecklistItem, ChecklistVersionSummary } from "@/lib/checklists";

export const TYPE_ID = "00000000-0000-7000-8000-000000000001";
export const PACKAGE_ID = "00000000-0000-7000-8000-000000000002";

/** A Checklist item for tests; `n` (1-9) makes its id and text distinct. */
export function item(n: number, over: Partial<ChecklistItem> = {}): ChecklistItem {
  return {
    id: `00000000-0000-7000-8000-00000000030${n}`,
    kind: "question",
    text: `Question ${n}?`,
    why_it_matters: `Why ${n}`,
    affected_area: null,
    impact: "medium",
    mandatory: false,
    ...over,
  };
}

/** A published Checklist (v1, no draft) for tests; `n` (1-9) makes its id and name distinct. */
export function checklist(n: number, over: Partial<Checklist> = {}): Checklist {
  const items = over.items ?? [item(1, { mandatory: true }), item(2)];
  return {
    id: `00000000-0000-7000-8000-00000000040${n}`,
    name: `Checklist ${n}`,
    domain: "security",
    products: ["AutoStore"],
    industry: null,
    integration_types: [{ id: TYPE_ID, code: "SAP", name: "SAP IDoc", retired: false }],
    status: "active",
    retired: false,
    retired_reason: null,
    current_version: 1,
    item_count: items.length,
    mandatory_count: items.filter((i) => i.mandatory).length,
    items,
    draft: null,
    created_by: { id: "00000000-0000-7000-8000-000000000201", name: "[AUTHOR]" },
    created_at: "2026-10-01T10:00:00Z",
    row_version: 2,
    ...over,
  };
}

/** The Checklist with a draft seeded from its published version. */
export function withDraft(c: Checklist, over: Partial<NonNullable<Checklist["draft"]>> = {}): Checklist {
  return {
    ...c,
    draft: {
      name: c.name,
      domain: c.domain,
      products: c.products,
      industry: c.industry,
      integration_types: c.integration_types,
      items: c.items,
      publishable: true,
      publish_problem: null,
      ...over,
    },
  };
}

export const VERSION_1: ChecklistVersionSummary = {
  version: 1,
  name: "Checklist 1",
  published_by: { id: "00000000-0000-7000-8000-000000000201", name: "[PUBLISHER]" },
  published_at: "2026-10-02T09:30:00Z",
  item_count: 2,
  mandatory_count: 1,
};
