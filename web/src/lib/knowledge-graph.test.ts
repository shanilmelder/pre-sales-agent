import { describe, expect, it } from "vitest";

import { GRAPH_IDS, graphFixture } from "@/test/knowledge-fixtures";

import {
  entityId,
  filterGraph,
  GRAPH_STATUSES,
  LAYOUT_BOUNDS,
  layoutGraph,
  neighbours,
  nodeAriaLabel,
  nodeRadius,
  staleInText,
  type GraphEdge,
  type GraphNode,
} from "./knowledge-graph";

function many(count: number): { nodes: Pick<GraphNode, "id" | "type">[]; edges: GraphEdge[] } {
  const types = ["product", "integration_type", "source", "checklist"] as const;
  const nodes = Array.from({ length: count }, (_, i) => ({ id: `n${i}`, type: types[i % 4] }));
  const edges: GraphEdge[] = nodes.slice(1).map((n, i) => ({
    source: n.id,
    target: nodes[i % 5].id,
    kind: i % 7 === 0 ? "gap" : "linked",
  }));
  return { nodes, edges };
}

describe("layoutGraph", () => {
  it("puts every node in the same place for the same data", () => {
    const { nodes, edges } = graphFixture();
    const first = layoutGraph(nodes, edges);
    const second = layoutGraph(structuredClone(nodes), structuredClone(edges));
    expect(second).toEqual(first);
    expect(Object.keys(first).sort()).toEqual(nodes.map((n) => n.id).sort());
  });

  it("keeps every node inside the bounds the drawer leaves free", () => {
    const { nodes, edges } = many(60);
    const positions = layoutGraph(nodes, edges);
    for (const { x, y } of Object.values(positions)) {
      expect(Number.isFinite(x) && Number.isFinite(y)).toBe(true);
      expect(x).toBeGreaterThanOrEqual(LAYOUT_BOUNDS.minX);
      expect(x).toBeLessThanOrEqual(LAYOUT_BOUNDS.maxX);
      expect(y).toBeGreaterThanOrEqual(LAYOUT_BOUNDS.minY);
      expect(y).toBeLessThanOrEqual(LAYOUT_BOUNDS.maxY);
    }
  });

  it("spreads the nodes out and draws linked nodes closer than unlinked ones", () => {
    const { nodes, edges } = graphFixture();
    const p = layoutGraph(nodes, edges);
    const distance = (a: string, b: string) => Math.hypot(p[a].x - p[b].x, p[a].y - p[b].y);
    const ids = nodes.map((n) => n.id);
    for (const a of ids) for (const b of ids) if (a < b) expect(distance(a, b)).toBeGreaterThan(20);
    // The Checklist links to SAP EWM; HubSpot is linked to neither it nor its neighbours.
    expect(distance(GRAPH_IDS.erp, GRAPH_IDS.sap)).toBeLessThan(distance(GRAPH_IDS.erp, GRAPH_IDS.hub));
  });

  it("handles no nodes, and edges to unknown nodes", () => {
    expect(layoutGraph([], [])).toEqual({});
    const positions = layoutGraph([{ id: "a", type: "product" }], [
      { source: "a", target: "ghost", kind: "linked" },
    ]);
    expect(Object.keys(positions)).toEqual(["a"]);
  });
});

describe("filterGraph", () => {
  it("removes a hidden type's nodes and every edge touching them, and keeps the counts", () => {
    const graph = graphFixture();
    const view = filterGraph(graph, { hidden: new Set(["source"]), query: "" });
    expect(view.nodes.map((n) => n.type)).not.toContain("source");
    expect(view.edges.every((e) => !e.source.startsWith("source:") && !e.target.startsWith("source:"))).toBe(true);
    expect(view.edges).toHaveLength(4);
    expect(view.counts).toEqual({ product: 2, integration_type: 1, source: 2, checklist: 1 });
  });

  it("marks the visible nodes the search matches, trimmed and ignoring case", () => {
    const graph = graphFixture();
    const view = filterGraph(graph, { hidden: new Set(), query: "  sap " });
    expect([...view.matches].sort()).toEqual([GRAPH_IDS.sap, GRAPH_IDS.guide].sort());
    expect(view.nodes).toHaveLength(graph.nodes.length);
    expect(filterGraph(graph, { hidden: new Set(), query: "" }).matches.size).toBe(6);
    expect(filterGraph(graph, { hidden: new Set(["product"]), query: "sap" }).matches).toEqual(
      new Set([GRAPH_IDS.guide]),
    );
  });
});

describe("node helpers", () => {
  it("names a node by label, type and status", () => {
    const [sap, , , , playbook] = graphFixture().nodes;
    expect(nodeAriaLabel(sap)).toBe("SAP EWM, Product, Ready");
    expect(nodeAriaLabel(playbook)).toBe("HubSpot playbook, Knowledge Source, Stale");
    expect(nodeAriaLabel({ label: "X", type: "checklist", status: "missing" })).toBe(
      "X, Checklist, Missing coverage",
    );
  });

  it("sizes nodes by type, 5 bigger with six or more connections", () => {
    expect([
      nodeRadius("product", 0),
      nodeRadius("integration_type", 5),
      nodeRadius("source", 0),
      nodeRadius("checklist", 0),
    ]).toEqual([21, 21, 17, 19]);
    expect(nodeRadius("source", 6)).toBe(22);
    expect(nodeRadius("product", 9)).toBe(26);
  });

  it("reads the entity id from a node id and lists neighbours", () => {
    expect(entityId({ id: GRAPH_IDS.guide })).toBe("00000000-0000-7000-8000-000000000101");
    expect(entityId({ id: "product:a:b" })).toBe("a:b");
    expect(neighbours(graphFixture().edges).get(GRAPH_IDS.rest)?.length).toBe(5);
  });

  it("gives every status a glyph and a label, and a dashed ring to stale, failed and missing", () => {
    for (const meta of Object.values(GRAPH_STATUSES)) {
      expect(meta.glyph).not.toBe("");
      expect(meta.label).not.toBe("");
    }
    const ringed = Object.entries(GRAPH_STATUSES)
      .filter(([, meta]) => meta.ring)
      .map(([status]) => status)
      .sort();
    expect(ringed).toEqual(["embedding_failed", "missing", "stale"]);
  });

  it("says when a Source turns stale", () => {
    expect(staleInText(0)).toBe("Now");
    expect(staleInText(1)).toBe("1 day");
    expect(staleInText(40)).toBe("40 days");
    expect(staleInText(null)).toBe("—");
    expect(staleInText(undefined)).toBe("—");
  });
});
