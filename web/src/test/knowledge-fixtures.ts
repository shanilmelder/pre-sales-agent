import type { KnowledgeSource } from "@/lib/knowledge-sources";

/** A Knowledge Source for tests; `n` (1-9) makes its id, title and owner distinct. */
export function source(n: number, over: Partial<KnowledgeSource> = {}): KnowledgeSource {
  return {
    id: `00000000-0000-7000-8000-00000000010${n}`,
    title: `Guide ${n}`,
    product: "AutoStore",
    owner: { id: `00000000-0000-7000-8000-00000000020${n}`, name: `[OWNER ${n}]` },
    integration_types: [
      { id: "00000000-0000-7000-8000-000000000001", code: "SAP", name: "SAP IDoc", retired: false },
    ],
    status: "active",
    retired: false,
    retired_reason: null,
    last_reviewed_on: "2026-09-01",
    stale: false,
    version: 1,
    version_count: 1,
    product_version: "2.1",
    filename: `guide-${n}.pdf`,
    size_bytes: 2048,
    uploaded_by: { id: `00000000-0000-7000-8000-00000000020${n}`, name: `[OWNER ${n}]` },
    uploaded_at: "2026-09-01T10:00:00Z",
    parse: { status: "parsed", error_code: null },
    row_version: 1,
    created_at: "2026-09-01T10:00:00Z",
    ...over,
  };
}
