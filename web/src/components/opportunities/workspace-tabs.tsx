"use client";

import Link from "next/link";
import { useSelectedLayoutSegment } from "next/navigation";
import { type KeyboardEvent, type ReactNode, useId, useRef } from "react";

import { useShell, useWorkspaceTabKeys } from "@/components/shell/shell-context";
import { cn } from "@/lib/utils";
import { openCountLabel } from "@/lib/conflicts";
import { activeTab, tabHref, WORKSPACE_TABS, type WorkspaceTabSlug } from "@/lib/workspace";

/** The workspace tab strip and the selected tab's panel. A `tablist` of links (each tab has
 * its own URL), the selected one marked by the route; `1`–`9` reach the tabs through the
 * shell's key handler, and Left/Right/Home/End move focus along the strip. A tab with a
 * count above 0 shows it after its label ("Conflicts 3", read as "Conflicts, 3 open"). */
export function WorkspaceTabs({
  id,
  counts = {},
  children,
}: {
  id: string;
  /** A count shown after a tab's label when above 0 (the Conflicts tab's open count). */
  counts?: Partial<Record<WorkspaceTabSlug, number>>;
  children: ReactNode;
}) {
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
        className="flex shrink-0 gap-0.5 overflow-x-auto border-b border-border px-gutter"
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
              className={cn(
                "-mb-px flex h-[34px] shrink-0 items-center gap-1.5 border-b-2 px-2 text-label whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset",
                isSelected
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="text-meta text-muted-foreground" aria-hidden="true">
                {tab.key}
              </span>
              {tab.label}
              {(counts[tab.slug] ?? 0) > 0 ? (
                <span
                  data-testid={`tab-count-${tab.slug}`}
                  className="inline-flex h-4 min-w-4 items-center justify-center rounded-full border border-border px-1 text-meta text-foreground [font-variant-numeric:tabular-nums]"
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
        {children}
      </div>
    </>
  );
}
