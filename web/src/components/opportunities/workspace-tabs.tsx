"use client";

import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";
import { type KeyboardEvent, type ReactNode, useId, useRef, useState } from "react";

import { ConnectionStatus } from "@/components/opportunities/connection-status";
import { usePublishStreamState, useShell, useWorkspaceTabKeys } from "@/components/shell/shell-context";
import { cn } from "@/lib/utils";
import { openCountLabel } from "@/lib/conflicts";
import { useNarrowViewport } from "@/components/shell/use-narrow-viewport";
import {
  retryEventStream,
  useConflictsEvents,
  useEventStreamStatus,
  useGapsEvents,
} from "@/lib/opportunity-events";
import { activeTab, tabHref, WORKSPACE_TABS, type WorkspaceTabSlug } from "@/lib/workspace";

/** Tabs whose count is open blocking work, shown in the blocker tint. */
const BLOCKER_COUNT_TABS: ReadonlySet<WorkspaceTabSlug> = new Set(["gaps", "conflicts"]);

/** The workspace tab strip and the selected tab's panel. A `tablist` of links (each tab has
 * its own URL), the selected one marked by the route; `1`–`9` reach the tabs through the
 * shell's key handler, and Left/Right/Home/End move focus along the strip. A tab with a
 * count above 0 shows it after its label ("Conflicts 3", read as "Conflicts, 3 open").
 * Story 4.7: with `loadGapCount`, the Gaps tab's open count follows the Opportunity's event
 * stream (`gaps.changed`) without a reload; Story 6.2: with `loadConflictCount`, so does the
 * Conflicts tab's open count (`conflicts.changed`). Story 2.3: a slim status bar at the
 * bottom reads "Reconnecting…" while that stream is down; once it has been down 60 s the
 * shell's Offline strip shows (Story 17.2c) and the tab panel sits in a disabled `fieldset`,
 * so its buttons and inputs go inert (links and the tabs still work). Below 1024px the same
 * `fieldset` is disabled. */
export function WorkspaceTabs({
  id,
  counts: initialCounts = {},
  loadGapCount,
  loadConflictCount,
  children,
}: {
  id: string;
  /** A count shown after a tab's label when above 0 (the Conflicts tab's open count, the Gaps
   * tab's open Gaps). */
  counts?: Partial<Record<WorkspaceTabSlug, number>>;
  /** Reads the open Gap count again (a server action); left out, the count stays as given. */
  loadGapCount?: (opportunityId: string) => Promise<number | null>;
  /** Reads the open-plus-escalated Conflict count again (a server action); left out, the
   * count stays as given. */
  loadConflictCount?: (opportunityId: string) => Promise<number | null>;
  children: ReactNode;
}) {
  const [liveGaps, setLiveGaps] = useState<{ from: number | undefined; count: number } | null>(
    null,
  );
  const [liveConflicts, setLiveConflicts] = useState<{
    from: number | undefined;
    count: number;
  } | null>(null);
  useGapsEvents(
    id,
    () => {
      const from = initialCounts.gaps;
      void loadGapCount?.(id).then(
        (count) => {
          if (count !== null) setLiveGaps({ from, count });
        },
        () => undefined,
      );
    },
    loadGapCount !== undefined,
  );
  useConflictsEvents(
    id,
    () => {
      const from = initialCounts.conflicts;
      void loadConflictCount?.(id).then(
        (count) => {
          if (count !== null) setLiveConflicts({ from, count });
        },
        () => undefined,
      );
    },
    loadConflictCount !== undefined,
  );
  // A newer count from the server (a navigation) wins over the live one read before it.
  const counts = {
    ...initialCounts,
    ...(liveGaps && liveGaps.from === initialCounts.gaps ? { gaps: liveGaps.count } : {}),
    ...(liveConflicts && liveConflicts.from === initialCounts.conflicts
      ? { conflicts: liveConflicts.count }
      : {}),
  };
  const stream = useEventStreamStatus(id);
  const offline = stream === "offline";
  usePublishStreamState(stream, () => retryEventStream(id));
  // Below 1024px the workbench is read-only, like offline (Story 17.2c).
  const narrow = useNarrowViewport();
  const readOnly = offline || narrow;
  const segment = useSelectedLayoutSegment();
  const { singleKeyShortcuts } = useShell();
  const selected = activeTab(segment);
  const baseId = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const hrefs = WORKSPACE_TABS.map((tab) => tabHref(id, tab.slug));
  useWorkspaceTabKeys(hrefs);

  const tabId = (slug: string) => `${baseId}-tab-${slug}`;
  const panelId = `${baseId}-panel`;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const tabs = Array.from(
      listRef.current?.querySelectorAll<HTMLAnchorElement>('[role="tab"]') ?? [],
    );
    const current = tabs.indexOf(document.activeElement as HTMLAnchorElement);
    if (current < 0) return;
    let next: number;
    switch (event.key) {
      case "ArrowRight":
        next = (current + 1) % tabs.length;
        break;
      case "ArrowLeft":
        next = (current - 1 + tabs.length) % tabs.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = tabs.length - 1;
        break;
      default:
        return;
    }
    event.preventDefault();
    tabs[next]?.focus();
  }

  return (
    <>
      <div
        ref={listRef}
        role="tablist"
        aria-label="Opportunity workspace"
        onKeyDown={onKeyDown}
        className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-surface pr-page pl-[calc(var(--spacing-page)-10px)] [scrollbar-width:none]"
      >
        {WORKSPACE_TABS.map((tab, index) => {
          const isSelected = tab.slug === selected;
          // Roving focus: the selected tab (or the first, on an unknown route) is the one stop.
          const focusable = selected ? isSelected : index === 0;
          return (
            <Link
              key={tab.slug}
              id={tabId(tab.slug)}
              href={hrefs[index]!}
              role="tab"
              aria-selected={isSelected}
              aria-controls={isSelected ? panelId : undefined}
              aria-keyshortcuts={singleKeyShortcuts ? tab.key : undefined}
              tabIndex={focusable ? 0 : -1}
              className={`${cn(
                "-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-2.5 py-3 whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset",
                isSelected
                  ? "border-primary text-primary-text"
                  : "border-transparent text-text-secondary hover:text-foreground",
              )} text-[14px] leading-5 ${isSelected ? "font-semibold" : "font-medium"}`}
            >
              {tab.label}
              {(counts[tab.slug] ?? 0) > 0 ? (
                <span
                  data-testid={`tab-count-${tab.slug}`}
                  className={`inline-flex min-w-5 items-center justify-center rounded-[10px] px-[7px] text-[12px] leading-4 font-medium [font-variant-numeric:tabular-nums] ${
                    BLOCKER_COUNT_TABS.has(tab.slug)
                      ? "bg-blocker-tint text-blocker"
                      : "bg-surface-alt text-text-secondary"
                  }`}
                >
                  <span aria-hidden="true">{counts[tab.slug]}</span>
                  <span className="sr-only">, {openCountLabel(counts[tab.slug] ?? 0)}</span>
                </span>
              ) : null}
            </Link>
          );
        })}
      </div>
      <div
        id={panelId}
        role="tabpanel"
        aria-labelledby={selected ? tabId(selected) : undefined}
        className="flex flex-1 flex-col"
      >
        <fieldset
          disabled={readOnly}
          aria-label={
            offline
              ? "Edits disabled while offline"
              : narrow
                ? "Edits disabled on a narrow screen"
                : undefined
          }
          className="m-0 flex min-w-0 flex-1 flex-col border-0 p-0"
        >
          {children}
        </fieldset>
      </div>
      <ConnectionStatus status={stream} />
    </>
  );
}
