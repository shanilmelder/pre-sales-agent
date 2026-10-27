"use client";

import {
  CircleAlertIcon,
  CircleCheckIcon,
  LoaderIcon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useId, useState, useTransition, type KeyboardEvent, type ReactNode } from "react";

import { markReviewed, type SourceResult } from "@/app/knowledge/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { Button, buttonVariants } from "@/components/ui/button";
import { Pill } from "@/components/ui/pill";
import { checklistHref, coverageHref, sourceHref } from "@/lib/coverage";
import {
  CITATIONS_PENDING,
  entityId,
  GRAPH_STATUSES,
  GRAPH_TYPES,
  staleInText,
  type GraphEdge,
  type GraphNode,
  type GraphNodeStatus,
} from "@/lib/knowledge-graph";
import { canWrite, formatDate, staleChangeMessage } from "@/lib/knowledge-sources";
import type { Role } from "@/lib/navigation";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "connections", label: "Connections" },
  { id: "citations", label: "Citations" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const REVIEW_FAILED = "The Source could not be marked reviewed. Try again.";
const NO_ACCESS = "Only a platform administrator or the owner can change this Source.";

const STATUS_ICONS: Record<GraphNodeStatus, ReactNode> = {
  ready: <CircleCheckIcon />,
  partial: <TriangleAlertIcon />,
  stale: <TriangleAlertIcon />,
  missing: <CircleAlertIcon />,
  embedding_failed: <CircleAlertIcon />,
  embedding: <LoaderIcon />,
};

/** The score's colour, by the status pill's tone (the mockup's green, amber, red, primary). */
const SCORE_TEXT = { resolved: "text-resolved", gap: "text-gap", blocker: "text-blocker", agent: "text-agent", neutral: "text-neutral" } as const;
const SCORE_BAR = { resolved: "bg-resolved", gap: "bg-gap", blocker: "bg-blocker", agent: "bg-agent", neutral: "bg-neutral" } as const;

type Connection = { node: GraphNode; gap: boolean };

/** The node's links, each with the node at its other end, in edge order. */
export function connectionsOf(
  node: Pick<GraphNode, "id">,
  nodes: readonly GraphNode[],
  edges: readonly GraphEdge[],
): Connection[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const result: Connection[] = [];
  for (const edge of edges) {
    if (edge.source !== node.id && edge.target !== node.id) continue;
    const other = byId.get(edge.source === node.id ? edge.target : edge.source);
    if (other) result.push({ node: other, gap: edge.kind === "gap" });
  }
  return result;
}

function primaryAction(node: GraphNode): { label: string; href: string } {
  switch (node.type) {
    case "source":
      return { label: "Open source", href: sourceHref(entityId(node)) };
    case "checklist":
      return { label: "Edit checklist", href: checklistHref(entityId(node)) };
    case "integration_type":
      return { label: "View coverage", href: coverageHref({ integrationTypeId: entityId(node) }) };
    default:
      return { label: "View coverage", href: coverageHref({ product: node.label }) };
  }
}

/** The selected node's details, in the mockup's 340px card over the canvas's right edge:
 * type, label, owner and last review; the Coverage score with its status pill and bar; the
 * Overview (connections, stale in), Connections (each selects its node) and Citations tabs;
 * the node's primary action, and Mark reviewed for a Source the user may change. Retrieval
 * statistics are left out until agent retrieval is logged. */
export function GraphDrawer({
  node,
  nodes,
  edges,
  me,
  onSelect,
  onClose,
  onReload,
}: {
  node: GraphNode;
  nodes: readonly GraphNode[];
  edges: readonly GraphEdge[];
  me: { id: string; roles: readonly Role[] };
  onSelect: (id: string) => void;
  onClose: () => void;
  /** Reads the graph again (after Mark reviewed, or from the stale notice). */
  onReload: () => Promise<void>;
}) {
  const announce = useAnnounce();
  const [tab, setTab] = useState<TabId>("overview");
  const [notice, setNotice] = useState<{ nodeId: string; kind: "stale" | "error"; text: string } | null>(null);
  const [pending, startTransition] = useTransition();
  const baseId = useId();
  const headingId = `${baseId}-heading`;
  const status = GRAPH_STATUSES[node.status];
  const type = GRAPH_TYPES[node.type];
  const connections = connectionsOf(node, nodes, edges);
  const action = primaryAction(node);
  const mayReview =
    node.type === "source" &&
    node.can_review &&
    node.owner !== null &&
    node.row_version !== null &&
    node.row_version !== undefined &&
    canWrite({ owner: node.owner, retired: false }, me);
  const shownNotice = notice?.nodeId === node.id ? notice : null;

  function review() {
    const rowVersion = node.row_version;
    if (pending || shownNotice?.kind === "stale" || rowVersion === null || rowVersion === undefined) {
      return;
    }
    setNotice(null);
    const nodeId = node.id;
    const label = node.label;
    startTransition(async () => {
      let result: SourceResult;
      try {
        result = await markReviewed({ sourceId: entityId(node), rowVersion });
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok") {
        announce(`Marked ${label} reviewed`);
        await onReload();
        return;
      }
      const text =
        result.kind === "stale"
          ? staleChangeMessage()
          : result.kind === "forbidden"
            ? NO_ACCESS
            : REVIEW_FAILED;
      setNotice({ nodeId, kind: result.kind === "stale" ? "stale" : "error", text });
      announce(text);
    });
  }

  function reload() {
    startTransition(async () => {
      setNotice(null);
      await onReload();
    });
  }

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = TABS.length - 1;
    if (next === null) return;
    event.preventDefault();
    setTab(TABS[next].id);
    document.getElementById(`${baseId}-tab-${TABS[next].id}`)?.focus();
  }

  return (
    <aside
      aria-label="Node details"
      className="absolute inset-4 flex flex-col overflow-hidden rounded-xl border border-border bg-surface text-foreground shadow-[0_12px_32px_rgba(0,0,0,.35)]"
    >
      <div className="relative bg-[linear-gradient(135deg,var(--primary),#6D4FD0)] p-4 text-primary-foreground">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close details"
          className="absolute top-2.5 right-2.5 flex size-[26px] items-center justify-center rounded-md bg-white/20 outline-none focus-visible:ring-2 focus-visible:ring-white"
        >
          <XIcon aria-hidden="true" className="size-3.5" strokeWidth={1.75} />
        </button>
        <div className="text-meta opacity-90">{type.one}</div>
        <h2 id={headingId} className="pr-[30px] text-[18px] leading-[26px] font-semibold">
          {node.label}
        </h2>
        <div className="mt-1.5 text-meta opacity-95">
          Owner {node.owner?.name ?? "—"} · Reviewed{" "}
          {node.last_reviewed_on ? formatDate(node.last_reviewed_on) : "—"}
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <div className="rounded-lg border border-border p-3.5" data-testid="graph-score">
          <div className="flex items-end justify-between">
            <div>
              <div className="text-meta text-text-secondary">Coverage score</div>
              <div className={cn("text-kpi leading-9", SCORE_TEXT[status.tone])}>
                {node.score}
                <span className="text-[14px] font-normal text-text-secondary">/100</span>
              </div>
            </div>
            <Pill tone={status.tone} icon={STATUS_ICONS[node.status]} data-status={node.status}>
              {status.label}
            </Pill>
          </div>
          <div aria-hidden="true" className="mt-2.5 h-1.5 rounded-[3px] bg-surface-alt">
            <div
              data-testid="graph-score-bar"
              className={cn("h-1.5 rounded-[3px]", SCORE_BAR[status.tone])}
              style={{ width: `${node.score}%` }}
            />
          </div>
        </div>

        <div role="tablist" aria-label="Node details sections" className="flex gap-0.5 border-b border-border">
          {TABS.map((t, index) => (
            <button
              key={t.id}
              id={`${baseId}-tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              aria-controls={`${baseId}-panel-${t.id}`}
              tabIndex={tab === t.id ? 0 : -1}
              onClick={() => setTab(t.id)}
              onKeyDown={(event) => onTabKeyDown(event, index)}
              className={cn(
                "-mb-px border-b-2 px-2.5 py-2 text-control outline-none focus-visible:ring-2 focus-visible:ring-primary",
                tab === t.id
                  ? "border-primary text-primary-text"
                  : "border-transparent text-text-secondary hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div
          role="tabpanel"
          id={`${baseId}-panel-${tab}`}
          aria-labelledby={`${baseId}-tab-${tab}`}
          tabIndex={0}
          className="outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {tab === "overview" ? (
            <dl className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-border px-3 py-2.5">
                <dt className="text-meta text-text-secondary">Connections</dt>
                <dd className="text-[18px] font-semibold">{connections.length}</dd>
              </div>
              <div className="rounded-lg border border-border px-3 py-2.5">
                <dt className="text-meta text-text-secondary">Stale in</dt>
                <dd className="text-[18px] font-semibold">{staleInText(node.stale_in_days)}</dd>
              </div>
            </dl>
          ) : tab === "connections" ? (
            connections.length === 0 ? (
              <p className="text-meta text-text-secondary">No connections.</p>
            ) : (
              <ul>
                {connections.map(({ node: other, gap }) => {
                  const meta = GRAPH_TYPES[other.type];
                  return (
                    <li key={`${other.id}-${gap ? "gap" : "linked"}`}>
                      <button
                        type="button"
                        onClick={() => onSelect(other.id)}
                        className="flex w-full items-center gap-2.5 border-b border-border py-2 text-left text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
                      >
                        <svg
                          aria-hidden="true"
                          width="18"
                          height="18"
                          viewBox="0 0 24 24"
                          fill="none"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className={other.type === "checklist" ? "stroke-gap" : "stroke-primary-text"}
                        >
                          <path d={meta.icon} />
                        </svg>
                        <span className="flex-1">{other.label}</span>
                        <span className={cn("text-meta", gap ? "text-gap" : "text-text-secondary")}>
                          {gap ? "Missing coverage" : meta.one}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )
          ) : (
            <p className="text-meta text-text-secondary">{CITATIONS_PENDING}</p>
          )}
        </div>

        {shownNotice ? (
          <div
            role="alert"
            className={cn(
              "flex flex-col gap-2 rounded-lg px-3 py-2.5 text-control",
              shownNotice.kind === "stale" ? "bg-gap-tint text-gap" : "bg-blocker-tint text-blocker",
            )}
          >
            <span>{shownNotice.text}</span>
            {shownNotice.kind === "stale" ? (
              <Button type="button" variant="outline" size="sm" onClick={reload} className="self-start">
                Reload
              </Button>
            ) : null}
          </div>
        ) : null}

        <div className="mt-auto flex gap-2">
          <Link
            href={action.href}
            className={`${buttonVariants({ variant: "default", size: "sm" })} h-9 flex-1 text-control`}
          >
            {action.label}
          </Link>
          {mayReview ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 flex-1"
              onClick={review}
              aria-disabled={pending || shownNotice?.kind === "stale" ? true : undefined}
            >
              Mark reviewed
            </Button>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
