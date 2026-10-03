"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { StatusPill } from "@/components/opportunities/status-pill";
import { useShell } from "@/components/shell/shell-context";
import {
  EMPTY_FILTERED,
  EMPTY_LIST,
  EMPTY_LIST_CREATOR,
  formatDate,
  SKELETON_MIN_MS,
  type OpportunitySummary,
} from "@/lib/opportunities";

const SKELETON_ROWS = 5;

/** True once the skeleton has been up for `SKELETON_MIN_MS` after the list first mounted. */
function useSkeletonDone(): boolean {
  const [done, setDone] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setDone(true), SKELETON_MIN_MS);
    return () => window.clearTimeout(timer);
  }, []);
  return done;
}

function Header() {
  return (
    <thead className="text-label text-muted-foreground">
      <tr className="h-row border-b border-border">
        <th scope="col" className="w-2/5 px-gutter font-medium">
          Customer
        </th>
        <th scope="col" className="px-2 font-medium">
          Status
        </th>
        <th scope="col" className="px-2 font-medium">
          Owner
        </th>
        <th scope="col" className="px-2 font-medium">
          Target proposal date
        </th>
      </tr>
    </thead>
  );
}

/** Opportunities, one page at a time, in 32px rows. Each row's customer is a link to the
 * Opportunity. The list is one Tab stop (roving tabindex); j/k (or the arrow keys) move
 * between rows and Enter opens one. Skeleton rows show for at least 150 ms on first load. */
export function OpportunitiesTable({
  items,
  caption,
  canCreate,
  clearFiltersHref,
}: {
  items: readonly OpportunitySummary[];
  caption: string;
  /** Whether the empty state may suggest `c` (only people who can create have it). */
  canCreate: boolean;
  /** Set when filters are applied: an empty list then says nothing matches and offers
   * Clear filters (this href) instead of the create empty state. */
  clearFiltersHref?: string;
}) {
  const { singleKeyShortcuts } = useShell();
  const skeletonDone = useSkeletonDone();
  const body = useRef<HTMLTableSectionElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    (focusedId && items.some((item) => item.id === focusedId) ? focusedId : null) ??
    items[0]?.id;

  if (!skeletonDone) {
    return (
      <table className="w-full table-fixed border-collapse text-left" aria-busy="true">
        <caption className="sr-only">{`${caption} (loading)`}</caption>
        <Header />
        <tbody>
          {Array.from({ length: SKELETON_ROWS }, (_, index) => (
            <tr key={index} data-skeleton-row="" className="h-row border-b border-border">
              {[0, 1, 2, 3].map((cell) => (
                <td key={cell} className={cell === 0 ? "px-gutter" : "px-2"}>
                  <span className="block h-3 w-3/4 animate-pulse rounded-sm bg-muted" />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (items.length === 0 && clearFiltersHref !== undefined) {
    return (
      <p className="flex items-center gap-3 p-gutter text-muted-foreground">
        {EMPTY_FILTERED}
        <Link
          href={clearFiltersHref}
          className="rounded-sm text-label text-foreground underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          Clear filters
        </Link>
      </p>
    );
  }

  if (items.length === 0) {
    return (
      <p className="p-gutter text-muted-foreground">{canCreate ? EMPTY_LIST_CREATOR : EMPTY_LIST}</p>
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLTableSectionElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const links = Array.from(
      body.current?.querySelectorAll<HTMLAnchorElement>("a[data-opportunity-row]") ?? [],
    );
    const index = links.findIndex((link) => link === document.activeElement);
    const next =
      index === -1 ? 0 : Math.min(links.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    links[next]?.focus();
  }

  return (
    <table className="w-full table-fixed border-collapse text-left">
      <caption className="sr-only">{caption}</caption>
      <Header />
      <tbody ref={body} onKeyDown={onKeyDown}>
        {items.map((item) => (
          <tr key={item.id} className="h-row border-b border-border hover:bg-muted/60">
            <td className="truncate px-gutter">
              <Link
                href={`/opportunities/${item.id}`}
                data-opportunity-row=""
                data-opportunity-id={item.id}
                tabIndex={item.id === tabStopId ? 0 : -1}
                onFocus={() => setFocusedId(item.id)}
                className="block w-full truncate rounded-sm text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                {item.customer_name}
              </Link>
            </td>
            <td className="px-2">
              <StatusPill status={item.status} />
            </td>
            <td className="truncate px-2">{item.owner.name}</td>
            <td className="truncate px-2 text-numeric">{formatDate(item.target_proposal_date)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
