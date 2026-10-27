import type { KnowledgeGraph } from "@/lib/knowledge-graph";
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
    embed: { status: "ready", error_code: null },
    row_version: 1,
    created_at: "2026-09-01T10:00:00Z",
    ...over,
  };
}

// --- Knowledge Graph (Story 3.6) -------------------------------------------------------------

export const GRAPH_IDS = {
  sap: "product:sap ewm",
  hub: "product:hubspot",
  rest: "integration_type:00000000-0000-7000-8000-000000000011",
  guide: "source:00000000-0000-7000-8000-000000000101",
  playbook: "source:00000000-0000-7000-8000-000000000102",
  erp: "checklist:00000000-0000-7000-8000-000000000301",
} as const;

export const GRAPH_OWNER = { id: "00000000-0000-7000-8000-000000000201", name: "[OWNER 1]" };

/** A small graph: SAP EWM × REST API is Ready (a Source and a Checklist); HubSpot × REST API
 * is a gap (only a stale Source). */
export function graphFixture(over: Partial<KnowledgeGraph> = {}): KnowledgeGraph {
  const plain = { owner: null, last_reviewed_on: null, can_review: false } as const;
  return {
    nodes: [
      { id: GRAPH_IDS.sap, type: "product", label: "SAP EWM", status: "ready", score: 100, ...plain },
      { id: GRAPH_IDS.hub, type: "product", label: "HubSpot", status: "partial", score: 25, ...plain },
      {
        id: GRAPH_IDS.rest,
        type: "integration_type",
        label: "REST API",
        status: "partial",
        score: 63,
        ...plain,
      },
      {
        id: GRAPH_IDS.guide,
        type: "source",
        label: "SAP EWM guide",
        status: "ready",
        score: 100,
        owner: GRAPH_OWNER,
        last_reviewed_on: "2026-03-12",
        row_version: 3,
        can_review: true,
        stale_in_days: 200,
      },
      {
        id: GRAPH_IDS.playbook,
        type: "source",
        label: "HubSpot playbook",
        status: "stale",
        score: 25,
        owner: { id: "00000000-0000-7000-8000-000000000202", name: "[OWNER 2]" },
        last_reviewed_on: "2025-01-08",
        row_version: 1,
        can_review: true,
        stale_in_days: 0,
      },
      {
        id: GRAPH_IDS.erp,
        type: "checklist",
        label: "ERP checklist",
        status: "ready",
        score: 100,
        owner: { id: "00000000-0000-7000-8000-000000000203", name: "[AUTHOR]" },
        last_reviewed_on: "2026-09-03",
        can_review: false,
      },
    ],
    edges: [
      { source: GRAPH_IDS.sap, target: GRAPH_IDS.rest, kind: "linked" },
      { source: GRAPH_IDS.hub, target: GRAPH_IDS.rest, kind: "gap" },
      { source: GRAPH_IDS.guide, target: GRAPH_IDS.sap, kind: "linked" },
      { source: GRAPH_IDS.guide, target: GRAPH_IDS.rest, kind: "linked" },
      { source: GRAPH_IDS.playbook, target: GRAPH_IDS.hub, kind: "linked" },
      { source: GRAPH_IDS.playbook, target: GRAPH_IDS.rest, kind: "linked" },
      { source: GRAPH_IDS.erp, target: GRAPH_IDS.sap, kind: "linked" },
      { source: GRAPH_IDS.erp, target: GRAPH_IDS.rest, kind: "linked" },
    ],
    stale_months: 12,
    ...over,
  };
}
