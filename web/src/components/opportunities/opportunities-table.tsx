"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { buttonVariants } from "@/components/ui/button";
import { StatusPill } from "@/components/opportunities/status-pill";
import { useShell } from "@/components/shell/shell-context";
import {
  countLabel,
  EMPTY_FILTERED,
  EMPTY_LIST_BODY,
  EMPTY_LIST_TITLE,
  formatDate,
  formatHours,
  initials,
  type OpportunitySummary,
} from "@/lib/opportunities";
import { NEW_OPPORTUNITY_HREF } from "@/lib/shortcuts";
import { useSkeletonDone } from "@/lib/use-skeleton-done";
import { cn } from "@/lib/utils";

const SKELETON_ROWS = 5;
/** At least 960px wide, so the Opportunity column keeps room; the card scrolls sideways
 * when narrower (small screens, the right pane open). */
const TABLE_CLASS = "w-full min-w-[960px] table-fixed border-collapse text-left";
const COLUMNS = 6;

/** The mockup's grid: a flexible Opportunity column, then 120, 150, 110, 120 and 130px, 16px
 * apart, inside 20px of row padding. Each width here includes the cell's own padding. */
const COLUMN_WIDTHS = [undefined, "136px", "166px", "126px", "136px", "158px"];

/** Each cell pads 8px a side (the 16px gap); the first and last pad 20px at the edge. */
const cellPad = (index: number) =>
  index === 0 ? "pr-2 pl-5" : index === COLUMNS - 1 ? "pr-5 pl-2 text-right" : "px-2";

/** The list's bordered card. The page also puts its "not reachable" text in it. */
export function OpportunitiesCard({ children }: { children: ReactNode }) {
  return (
    <div
      data-testid="opportunities-card"
      className="overflow-x-auto rounded-xl border border-border bg-surface shadow-card"
    >
      {children}
    </div>
  );
}

function Header() {
  const labels = ["Opportunity", "Status", "Owner", "Proposal date", "Open items", "Estimate"];
  return (
    <>
      <colgroup>
        {COLUMN_WIDTHS.map((width, index) => (
          <col key={index} style={width ? { width } : undefined} />
        ))}
      </colgroup>
      <thead className="bg-surface-alt text-label text-text-secondary">
        <tr className="border-b border-border">
          {labels.map((label, index) => (
            <th key={label} scope="col" className={cn("py-2.5 font-medium", cellPad(index))}>
              {label}
            </th>
          ))}
        </tr>
      </thead>
    </>
  );
}

/** A full-width message row inside the card (the empty states). */
function MessageRow({ children }: { children: ReactNode }) {
  return (
    <tr>
      <td colSpan={COLUMNS} className="px-6 py-14 text-center">
        {children}
      </td>
    </tr>
  );
}

/** "3 gaps · 2 conflicts", then (Story 8.6) "· 6 to submit" in the blocker tone while the
 * current Estimate Version has submission blockers: each count in its tone when above 0. */
function OpenItems({
  gaps,
  conflicts,
  toSubmit,
}: {
  gaps: number;
  conflicts: number;
  toSubmit: number;
}) {
  return (
    <span className="text-[13px]">
      <span className={`${gaps > 0 ? "text-gap" : "text-text-secondary"} font-medium`}>
        {countLabel(gaps, "gap")}
      </span>
      <span className="text-text-secondary"> · </span>
      <span className={`${conflicts > 0 ? "text-blocker" : "text-text-secondary"} font-medium`}>
        {countLabel(conflicts, "conflict")}
      </span>
      {toSubmit > 0 ? (
        <>
          <span className="text-text-secondary"> · </span>
          <span className="font-medium text-blocker" data-to-submit="">
            {`${toSubmit} to submit`}
          </span>
        </>
      ) : null}
    </span>
  );
}

function Estimate({ estimate }: { estimate: OpportunitySummary["estimate"] }) {
  return (
    <span className="block text-[13px]">
      <span className="block font-semibold">
        {estimate ? formatHours(estimate.total_hours) : "—"}
      </span>
      <span className="block text-meta text-text-secondary">
        {estimate
          ? `${estimate.status === "submitted" ? "Submitted" : "Draft"} v${estimate.version}`
          : "No estimate"}
      </span>
    </span>
  );
}

/** Opportunities, one page at a time, in a bordered card. Each row's title is a link to the
 * Opportunity, and a click anywhere on the row opens it too. The list is one Tab stop
 * (roving tabindex); j/k (or the arrow keys) move between rows and Enter opens one. Skeleton
 * rows show for at least 150 ms on first load. */
export function OpportunitiesTable({
  items,
  caption,
  canCreate,
  clearFiltersHref,
}: {
  items: readonly OpportunitySummary[];
  caption: string;
  /** Whether the empty state offers New Opportunity (only people who can create). */
  canCreate: boolean;
  /** Set when filters are applied: an empty list then says nothing matches and offers
   * Clear filters (this href) instead of the create empty state. */
  clearFiltersHref?: string;
}) {
  const { singleKeyShortcuts } = useShell();
  const router = useRouter();
  const skeletonDone = useSkeletonDone();
  const body = useRef<HTMLTableSectionElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    (focusedId && items.some((item) => item.id === focusedId) ? focusedId : null) ??
    items[0]?.id;

  if (!skeletonDone) {
    return (
      <OpportunitiesCard>
        <table className={TABLE_CLASS} aria-busy="true">
          <caption className="sr-only">{`${caption} (loading)`}</caption>
          <Header />
          <tbody>
            {Array.from({ length: SKELETON_ROWS }, (_, index) => (
              <tr key={index} data-skeleton-row="" className="border-t border-border">
                {Array.from({ length: COLUMNS }, (_, cell) => (
                  <td key={cell} className={cn("py-[18px]", cellPad(cell))}>
                    <span
                      className={cn(
                        "block h-3.5 rounded-sm bg-surface-alt",
                        cell === 0 ? "w-3/5" : "w-full",
                      )}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </OpportunitiesCard>
    );
  }

  if (items.length === 0) {
    return (
      <OpportunitiesCard>
        <table className={TABLE_CLASS}>
          <caption className="sr-only">{caption}</caption>
          <Header />
          <tbody>
            <MessageRow>
              {clearFiltersHref !== undefined ? (
                <p className="flex items-center justify-center gap-3 text-text-secondary">
                  {EMPTY_FILTERED}
                  <Link
                    href={clearFiltersHref}
                    className="rounded-sm text-label text-foreground underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    Clear filters
                  </Link>
                </p>
              ) : (
                <div data-testid="empty-list" className="flex flex-col items-center">
                  <p className="text-section">{EMPTY_LIST_TITLE}</p>
                  <p className="mt-1 mb-4 text-text-secondary">{EMPTY_LIST_BODY}</p>
                  {canCreate ? (
                    <Link
                      href={NEW_OPPORTUNITY_HREF}
                      className={`${buttonVariants({ variant: "default" })} text-body-strong`}
                    >
                      New Opportunity
                    </Link>
                  ) : null}
                </div>
              )}
            </MessageRow>
          </tbody>
        </table>
      </OpportunitiesCard>
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

  /** A plain click anywhere on the row opens the Opportunity. The title link handles its
   * own clicks, and modified clicks are left alone (no new-tab behaviour off the link). */
  function openRow(event: MouseEvent<HTMLTableRowElement>, href: string) {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if ((event.target as Element).closest("a")) return;
    // The end of a drag-select of the row's text is not a click to open it.
    if (window.getSelection()?.toString()) return;
    router.push(href);
  }

  return (
    <OpportunitiesCard>
      <table className={TABLE_CLASS}>
        <caption className="sr-only">{caption}</caption>
        <Header />
        <tbody ref={body} onKeyDown={onKeyDown}>
          {items.map((item) => {
            const href = `/opportunities/${item.id}`;
            return (
              <tr
                key={item.id}
                onClick={(event) => openRow(event, href)}
                className="cursor-pointer border-t border-border hover:bg-muted/60"
              >
                <td className={cn("py-[18px]", cellPad(0))}>
                  <Link
                    href={href}
                    data-opportunity-row=""
                    data-opportunity-id={item.id}
                    tabIndex={item.id === tabStopId ? 0 : -1}
                    onFocus={() => setFocusedId(item.id)}
                    className="block w-full truncate rounded-sm text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    {item.title}
                  </Link>
                  <span className="block truncate text-meta text-text-secondary">
                    {item.customer_name}
                  </span>
                </td>
                <td className={cn("py-[18px]", cellPad(1))}>
                  <StatusPill status={item.status} />
                </td>
                <td className={cn("py-[18px]", cellPad(2))}>
                  <span className="flex min-w-0 items-center gap-2 text-[13px]">
                    <Avatar className="size-6 bg-primary-tint text-primary-text">
                      <AvatarFallback aria-hidden="true" className="text-[10px] font-semibold">
                        {initials(item.owner.name)}
                      </AvatarFallback>
                    </Avatar>
                    <span className="truncate">{item.owner.name}</span>
                  </span>
                </td>
                <td className={cn("truncate py-[18px] tabular-nums", cellPad(3))}>
                  <span className="text-[13px]">{formatDate(item.target_proposal_date)}</span>
                </td>
                <td className={cn("py-[18px]", cellPad(4))}>
                  <OpenItems
                    gaps={item.open_gaps}
                    conflicts={item.open_conflicts}
                    toSubmit={item.blocker_count}
                  />
                </td>
                <td className={cn("py-[18px] tabular-nums", cellPad(5))}>
                  <Estimate estimate={item.estimate} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </OpportunitiesCard>
  );
}
