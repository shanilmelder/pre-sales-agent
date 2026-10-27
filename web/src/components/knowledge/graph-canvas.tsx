"use client";

import { useMemo, useState, type KeyboardEvent } from "react";

import { loadGraph } from "@/app/knowledge/graph/actions";
import { GraphDrawer } from "@/components/knowledge/graph-drawer";
import { GraphLegend } from "@/components/knowledge/graph-legend";
import { GraphToolbar } from "@/components/knowledge/graph-toolbar";
import { EmptyTabCard } from "@/components/ui/empty-tab-card";
import { Skeleton } from "@/components/ui/skeleton";
import { SOURCES_HREF } from "@/lib/coverage";
import {
  DIMMED_OPACITY,
  filterGraph,
  GRAPH_EMPTY,
  GRAPH_HEIGHT,
  GRAPH_STATUSES,
  GRAPH_TYPES,
  GRAPH_WIDTH,
  layoutGraph,
  neighbours,
  nodeAriaLabel,
  nodeRadius,
  type GraphNode,
  type GraphNodeType,
  type KnowledgeGraph,
  type Point,
} from "@/lib/knowledge-graph";
import type { Role } from "@/lib/navigation";
import { useSkeletonDone } from "@/lib/use-skeleton-done";

const GLOW = "rgba(124,135,240,.28)";

function focusNode(id: string) {
  document.querySelector<SVGGElement>(`[data-node-id="${CSS.escape(id)}"]`)?.focus();
}

/** One node, drawn as in the mockup: a glow when selected, a dashed status ring for stale,
 * failed and missing nodes, the type-coloured circle and icon, the status badge with its glyph,
 * the label and (unless Ready) the status text. A focusable button: Enter or Space selects it. */
function GraphNodeMark({
  node,
  at,
  radius,
  selected,
  opacity,
  onSelect,
}: {
  node: GraphNode;
  at: Point;
  radius: number;
  selected: boolean;
  opacity: number;
  onSelect: (id: string) => void;
}) {
  const type = GRAPH_TYPES[node.type];
  const status = GRAPH_STATUSES[node.status];
  const iconSize = Math.round(radius * 0.95) * 0.78;
  const badge = Math.round(radius * 0.72);

  function onKeyDown(event: KeyboardEvent<SVGGElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(node.id);
    }
  }

  return (
    <g
      data-node-id={node.id}
      data-node-type={node.type}
      data-status={node.status}
      data-selected={selected ? "" : undefined}
      transform={`translate(${at.x.toFixed(1)},${at.y.toFixed(1)})`}
      role="button"
      tabIndex={0}
      aria-label={nodeAriaLabel(node)}
      opacity={opacity}
      onClick={() => onSelect(node.id)}
      onKeyDown={onKeyDown}
      className="group cursor-pointer outline-none"
    >
      <circle r={radius + 14} fill={GLOW} opacity={selected ? 1 : 0} />
      <circle
        r={radius + 11}
        fill="none"
        strokeWidth="2"
        className="opacity-0 group-focus-visible:opacity-100"
        style={{ stroke: "var(--graph-chip-text)" }}
      />
      <circle
        data-status-ring=""
        r={radius + 7}
        fill="none"
        strokeWidth="2"
        strokeDasharray="5 4"
        opacity={status.ring ? 1 : 0}
        style={{ stroke: status.color }}
      />
      <circle
        r={radius}
        strokeWidth={selected ? 3 : 2}
        style={{ fill: "var(--graph-chip-background)", stroke: type.color }}
      />
      <g transform={`translate(${-iconSize / 2},${-iconSize / 2}) scale(${iconSize / 24})`}>
        <path
          d={type.icon}
          fill="none"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ stroke: type.color }}
        />
      </g>
      <circle cx={badge} cy={-badge} r="8" strokeWidth="2" style={{ fill: status.color, stroke: "var(--graph-canvas)" }} />
      <text
        x={badge}
        y={-badge}
        dy=".35em"
        textAnchor="middle"
        fontSize="10"
        fontWeight="700"
        className="font-sans"
        style={{ fill: "var(--graph-badge-text)" }}
      >
        {status.glyph}
      </text>
      <text
        y={radius + 16}
        textAnchor="middle"
        fontSize="12"
        fontWeight="500"
        className="font-sans"
        style={{ fill: "var(--graph-chip-text)" }}
      >
        {node.label}
      </text>
      <text
        data-status-text=""
        y={radius + 29}
        textAnchor="middle"
        fontSize="11"
        fontWeight="500"
        className="font-sans"
        style={{ fill: status.color }}
      >
        {node.status === "ready" ? "" : status.label}
      </text>
    </g>
  );
}

/** Knowledge → Graph: the always-dark, 660px canvas (Story 3.6). Nodes sit where the
 * deterministic force layout puts them (memoised per data set, so a reload draws the same
 * picture); search dims the nodes it doesn't match, a type chip turned off removes that type
 * and its edges, and selecting a node dims all but it and its neighbours and opens its
 * drawer (Esc closes it). Skeleton for at least 150 ms; an empty card when there is nothing. */
export function GraphCanvas({
  initialGraph,
  me,
}: {
  initialGraph: KnowledgeGraph;
  me: { id: string; roles: readonly Role[] };
}) {
  const skeletonDone = useSkeletonDone();
  const [graph, setGraph] = useState(initialGraph);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hidden, setHidden] = useState<ReadonlySet<GraphNodeType>>(new Set());
  const [query, setQuery] = useState("");

  const positions = useMemo(() => layoutGraph(graph.nodes, graph.edges), [graph]);
  const links = useMemo(() => neighbours(graph.edges), [graph]);
  const view = filterGraph(graph, { hidden, query });
  const selected = graph.nodes.find((n) => n.id === selectedId) ?? null;
  const focus = selected ? new Set([selected.id, ...(links.get(selected.id) ?? [])]) : null;

  if (!skeletonDone) {
    return (
      <div aria-busy="true" className="relative h-graph overflow-hidden rounded-xl border border-border bg-graph-canvas">
        <p className="sr-only">Loading the Knowledge Graph</p>
        <Skeleton className="absolute top-4 left-4 h-9 w-[260px] rounded-lg opacity-20" />
        <Skeleton className="absolute bottom-4 left-4 h-8 w-[420px] rounded-lg opacity-20" />
        <Skeleton className="absolute top-1/2 left-1/2 size-24 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-20" />
      </div>
    );
  }

  if (graph.nodes.length === 0) {
    return (
      <EmptyTabCard
        title="Nothing to graph yet"
        body={GRAPH_EMPTY}
        actionLabel="Go to Sources"
        href={SOURCES_HREF}
      />
    );
  }

  function select(id: string) {
    setSelectedId(id);
  }

  function close() {
    const id = selectedId;
    setSelectedId(null);
    if (id) requestAnimationFrame(() => focusNode(id));
  }

  async function reload() {
    try {
      const result = await loadGraph();
      if (result.kind === "ok") setGraph(result.graph);
    } catch {
      // Keep what is shown; the next visit reads it again.
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && selectedId !== null) {
      event.preventDefault();
      close();
    }
  }

  function toggle(type: GraphNodeType) {
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  return (
    <div
      data-testid="graph-canvas"
      onKeyDown={onKeyDown}
      className="relative h-graph overflow-hidden rounded-xl border border-border bg-graph-canvas"
    >
      <svg
        viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        role="group"
        aria-label="Knowledge graph"
        className="absolute inset-0 size-full"
      >
        {view.edges.map((edge) => {
          const a = positions[edge.source];
          const b = positions[edge.target];
          if (!a || !b) return null;
          const on = selectedId !== null && (edge.source === selectedId || edge.target === selectedId);
          const gap = edge.kind === "gap";
          return (
            <line
              key={`${edge.source}|${edge.target}|${edge.kind}`}
              data-edge-kind={edge.kind}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              strokeWidth={on ? 2.2 : 1.2}
              strokeDasharray={gap ? "5 4" : undefined}
              opacity={on ? 1 : gap ? (selected ? 0.35 : 0.5) : 0.45}
              style={{
                stroke: gap
                  ? "var(--graph-edge-gap)"
                  : on
                    ? "var(--graph-edge-selected)"
                    : "var(--graph-edge)",
              }}
            />
          );
        })}
        {view.nodes.map((node) => {
          const at = positions[node.id];
          if (!at) return null;
          const lit = view.matches.has(node.id) && (focus === null || focus.has(node.id));
          return (
            <GraphNodeMark
              key={node.id}
              node={node}
              at={at}
              radius={nodeRadius(node.type, links.get(node.id)?.length ?? 0)}
              selected={node.id === selectedId}
              opacity={lit ? 1 : DIMMED_OPACITY}
              onSelect={select}
            />
          );
        })}
      </svg>
      <GraphToolbar
        query={query}
        onQuery={setQuery}
        hidden={hidden}
        onToggle={toggle}
        counts={view.counts}
        drawerOpen={selected !== null}
      />
      <GraphLegend />
      {selected ? (
        <div className="absolute inset-y-0 right-0 w-graph-detail">
          <GraphDrawer
            node={selected}
            nodes={graph.nodes}
            edges={graph.edges}
            me={me}
            onSelect={select}
            onClose={close}
            onReload={reload}
          />
        </div>
      ) : null}
    </div>
  );
}
