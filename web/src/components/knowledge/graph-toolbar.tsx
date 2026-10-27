"use client";

import { SearchIcon } from "lucide-react";

import { GRAPH_TYPE_ORDER, GRAPH_TYPES, type GraphNodeType } from "@/lib/knowledge-graph";
import { cn } from "@/lib/utils";

/** The mockup's toolbar over the canvas: the search box, then one chip per node type with its
 * count. A chip is a toggle button (`aria-pressed`); turning it off hides that type. */
export function GraphToolbar({
  query,
  onQuery,
  hidden,
  onToggle,
  counts,
  drawerOpen,
}: {
  query: string;
  onQuery: (query: string) => void;
  hidden: ReadonlySet<GraphNodeType>;
  onToggle: (type: GraphNodeType) => void;
  counts: Record<GraphNodeType, number>;
  /** The drawer takes the right of the canvas; the toolbar stops short of it. */
  drawerOpen: boolean;
}) {
  return (
    <div
      data-testid="graph-toolbar"
      className={cn(
        "absolute top-4 left-4 flex flex-wrap items-center gap-2.5",
        drawerOpen ? "right-graph-detail" : "right-4",
      )}
    >
      <label className="flex min-w-[260px] items-center gap-2 rounded-lg border border-graph-chip-off-border bg-graph-chip-background px-3 py-[7px] text-graph-chip-off-text">
        <SearchIcon aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />
        <input
          type="search"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Search sources, products, checklists"
          aria-label="Search the graph"
          className="min-w-0 flex-1 border-0 bg-transparent text-[13px] text-graph-chip-text outline-none placeholder:text-graph-chip-off-text"
        />
      </label>
      {GRAPH_TYPE_ORDER.map((type) => {
        const on = !hidden.has(type);
        const meta = GRAPH_TYPES[type];
        return (
          <button
            key={type}
            type="button"
            aria-pressed={on}
            data-graph-chip={type}
            onClick={() => onToggle(type)}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-lg border px-3 py-[7px] whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-graph-chip-text",
              on
                ? "border-graph-chip-border bg-graph-chip-background text-graph-chip-text"
                : "border-graph-chip-off-border bg-transparent text-graph-chip-off-text",
            )}
          >
            <svg
              aria-hidden="true"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ stroke: meta.color }}
            >
              <path d={meta.icon} />
            </svg>
            <span className="text-control">{meta.label}</span>
            <span className="text-[13px] font-normal opacity-70">{counts[type]}</span>
          </button>
        );
      })}
    </div>
  );
}
