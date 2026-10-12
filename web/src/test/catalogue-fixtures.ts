import type { CatalogueEntry } from "@/lib/catalogue";

/** A catalogue entry for tests; `n` (1-9) makes its id, code and name distinct. */
export function entry(n: number, over: Partial<CatalogueEntry> = {}): CatalogueEntry {
  return {
    id: `00000000-0000-7000-8000-00000000000${n}`,
    kind: "integration_type",
    code: `CODE-${n}`,
    name: `Name ${n}`,
    definition: `Definition ${n}`,
    version: 1,
    current_version: 1,
    status: "active",
    retired: false,
    retired_reason: null,
    row_version: 1,
    created_at: "2026-10-06T10:00:00Z",
    ...over,
  };
}
