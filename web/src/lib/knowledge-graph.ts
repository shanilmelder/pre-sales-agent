// Knowledge Graph helpers (Story 3.6): the status and type tables, the deterministic layout and
// the search and type filters. Pure; safe on server and client.
import type { components } from "@/lib/api/client";
import type { PillTone } from "@/components/ui/pill";

export type KnowledgeGraph = components["schemas"]["KnowledgeGraph"];
export type GraphNode = components["schemas"]["GraphNode"];
export type GraphEdge = components["schemas"]["GraphEdge"];
export type GraphNodeType = components["schemas"]["GraphNodeType"];
export type GraphNodeStatus = components["schemas"]["NodeStatus"];

/** What someone who may not open the Graph sees on `/knowledge/graph`. */
export const GRAPH_DENIED =
  "You do not have access to the Knowledge Graph. Ask an admin for a role that can edit Checklists.";
export const GRAPH_EMPTY =
  "No Knowledge Sources yet. Upload product or integration documentation to start.";
export const CITATIONS_PENDING = "Citations appear once agent retrieval is logged.";

/** The canvas's SVG coordinate space (the mockup's viewBox). */
export const GRAPH_WIDTH = 1000;
export const GRAPH_HEIGHT = 660;
/** Nodes with this many connections or more are drawn bigger. */
export const HUB_DEGREE = 6;
export const HUB_EXTRA_RADIUS = 5;
/** The opacity of a node search or selection leaves out. */
export const DIMMED_OPACITY = 0.28;

type StatusMeta = {
  label: string;
  /** The badge glyph; the label always shows too, so meaning never rests on colour. */
  glyph: string;
  /** The badge, ring and status-text colour on the dark canvas. */
  color: string;
  /** The drawer's pill tone and the score's colour. */
  tone: PillTone;
  /** Stale, failed and missing nodes get a dashed ring. */
  ring: boolean;
};

export const GRAPH_STATUSES: Record<GraphNodeStatus, StatusMeta> = {
  ready: { label: "Ready", glyph: "✓", color: "var(--graph-ready)", tone: "resolved", ring: false },
  partial: {
    label: "Partial coverage",
    glyph: "!",
    color: "var(--graph-checklist)",
    tone: "gap",
    ring: false,
  },
  missing: {
    label: "Missing coverage",
    glyph: "✕",
    color: "var(--graph-missing)",
    tone: "blocker",
    ring: true,
  },
  stale: { label: "Stale", glyph: "!", color: "var(--graph-checklist)", tone: "gap", ring: true },
  embedding: {
    label: "Embedding",
    glyph: "…",
    color: "var(--graph-product)",
    tone: "agent",
    ring: false,
  },
  embedding_failed: {
    label: "Embedding failed",
    glyph: "✕",
    color: "var(--graph-missing)",
    tone: "blocker",
    ring: true,
  },
};

type TypeMeta = {
  /** The chip's label (plural). */
  label: string;
  /** One node of this type. */
  one: string;
  color: string;
  radius: number;
  /** A 24×24 stroke icon path (the mockup's). */
  icon: string;
};

/** In the mockup's order: the chips and the legend follow it. */
export const GRAPH_TYPES: Record<GraphNodeType, TypeMeta> = {
  product: {
    label: "Products",
    one: "Product",
    color: "var(--graph-product)",
    radius: 21,
    icon: "M21 8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16zM3.3 7 12 12l8.7-5M12 22V12",
  },
  integration_type: {
    label: "Integration Types",
    one: "Integration Type",
    color: "var(--graph-integration-type)",
    radius: 21,
    icon: "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7",
  },
  source: {
    label: "Knowledge Sources",
    one: "Knowledge Source",
    color: "var(--graph-knowledge-source)",
    radius: 17,
    icon: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8",
  },
  checklist: {
    label: "Checklists",
    one: "Checklist",
    color: "var(--graph-checklist)",
    radius: 19,
    icon: "M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11",
  },
};

export const GRAPH_TYPE_ORDER = Object.keys(GRAPH_TYPES) as GraphNodeType[];

/** The node's accessible name: "{label}, {type}, {status}". */
export function nodeAriaLabel(node: Pick<GraphNode, "label" | "type" | "status">): string {
  return `${node.label}, ${GRAPH_TYPES[node.type].one}, ${GRAPH_STATUSES[node.status].label}`;
}

/** The entity id behind a node id (`source:<id>` → `<id>`). */
export function entityId(node: Pick<GraphNode, "id">): string {
  const at = node.id.indexOf(":");
  return at < 0 ? node.id : node.id.slice(at + 1);
}

/** `{node id: ids of the nodes it links to}` over every edge (gaps included). */
export function neighbours(edges: readonly GraphEdge[]): Map<string, string[]> {
  const result = new Map<string, string[]>();
  for (const edge of edges) {
    result.set(edge.source, [...(result.get(edge.source) ?? []), edge.target]);
    result.set(edge.target, [...(result.get(edge.target) ?? []), edge.source]);
  }
  return result;
}

/** The drawn radius: the type's, plus `HUB_EXTRA_RADIUS` with `HUB_DEGREE` or more links. */
export function nodeRadius(type: GraphNodeType, degree: number): number {
  return GRAPH_TYPES[type].radius + (degree >= HUB_DEGREE ? HUB_EXTRA_RADIUS : 0);
}

/** The mockup's string hash, seeding each node's start angle. */
function hash(id: string, modulo: number): number {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 9973;
  return h % modulo;
}

export type Point = { x: number; y: number };

export const LAYOUT_ITERATIONS = 420;
export const LAYOUT_BOUNDS = { minX: 60, maxX: 640, minY: 70, maxY: 590 } as const;

/** The mockup's force-directed layout, deterministic: nodes start on a circle (Sources
 * outermost, then Checklists, then Products and Integration Types), seeded by their order and
 * id hash; then 420 cooling rounds of all-pairs repulsion, a pull to the centre and springs
 * along `linked` edges (gap edges pull nothing). Positions stay inside `LAYOUT_BOUNDS`, the
 * part of the canvas the node drawer leaves free. Same input, same output. */
export function layoutGraph(
  nodes: readonly Pick<GraphNode, "id" | "type">[],
  edges: readonly GraphEdge[],
): Record<string, Point> {
  const count = nodes.length;
  const state = nodes.map((n, i) => {
    const angle = (i / count) * 6.283 + hash(n.id, 100) / 100;
    const ring = n.type === "source" ? 250 : n.type === "checklist" ? 200 : 110;
    return {
      id: n.id,
      x: 500 + Math.cos(angle) * ring,
      y: 330 + Math.sin(angle) * ring * 0.75,
      vx: 0,
      vy: 0,
    };
  });
  const index = new Map(state.map((n) => [n.id, n]));
  const springs = edges
    .filter((e) => e.kind === "linked")
    .map((e) => [index.get(e.source), index.get(e.target)] as const)
    .filter((pair): pair is readonly [(typeof state)[number], (typeof state)[number]] =>
      Boolean(pair[0] && pair[1]),
    );
  const { minX, maxX, minY, maxY } = LAYOUT_BOUNDS;
  for (let it = 0; it < LAYOUT_ITERATIONS; it++) {
    const cool = 1 - it / LAYOUT_ITERATIONS;
    for (const a of state) {
      for (const b of state) {
        if (a === b) continue;
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const d2 = dx * dx + dy * dy + 0.01;
        const d = Math.sqrt(d2);
        const force = 14000 / d2;
        a.vx += (dx / d) * force;
        a.vy += (dy / d) * force;
      }
      a.vx += (500 - a.x) * 0.012;
      a.vy += (330 - a.y) * 0.014;
    }
    for (const [a, b] of springs) {
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const force = (d - 95) * 0.035;
      a.vx += (dx / d) * force;
      a.vy += (dy / d) * force;
      b.vx -= (dx / d) * force;
      b.vy -= (dy / d) * force;
    }
    for (const a of state) {
      const stepX = Math.max(-12, Math.min(12, a.vx)) * cool * 0.6;
      const stepY = Math.max(-12, Math.min(12, a.vy)) * cool * 0.6;
      a.x = Math.max(minX, Math.min(maxX, a.x + stepX));
      a.y = Math.max(minY, Math.min(maxY, a.y + stepY));
      a.vx *= 0.6;
      a.vy *= 0.6;
    }
  }
  return Object.fromEntries(state.map((n) => [n.id, { x: n.x, y: n.y }]));
}

export type GraphFilters = {
  /** The types whose chips are off. */
  hidden: ReadonlySet<GraphNodeType>;
  query: string;
};

export type FilteredGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** The visible nodes the search matches (all of them with no search). */
  matches: Set<string>;
  /** Nodes per type, for the chips (whatever is hidden). */
  counts: Record<GraphNodeType, number>;
};

/** A hidden type's nodes go, and every edge touching them; the search (trimmed, ignoring case,
 * on the label) only marks which visible nodes match. */
export function filterGraph(graph: Pick<KnowledgeGraph, "nodes" | "edges">, filters: GraphFilters): FilteredGraph {
  const counts = Object.fromEntries(GRAPH_TYPE_ORDER.map((t) => [t, 0])) as Record<
    GraphNodeType,
    number
  >;
  for (const node of graph.nodes) counts[node.type] += 1;
  const nodes = graph.nodes.filter((n) => !filters.hidden.has(n.type));
  const visible = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter((e) => visible.has(e.source) && visible.has(e.target));
  const query = filters.query.trim().toLowerCase();
  const matches = new Set(
    nodes.filter((n) => query === "" || n.label.toLowerCase().includes(query)).map((n) => n.id),
  );
  return { nodes, edges, matches, counts };
}

/** "Now" once stale, else "N days" ("1 day"); "—" for a node with no review. */
export function staleInText(days: number | null | undefined): string {
  if (days === null || days === undefined) return "—";
  if (days === 0) return "Now";
  return days === 1 ? "1 day" : `${days} days`;
}
