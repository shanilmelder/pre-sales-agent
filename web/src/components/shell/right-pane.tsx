"use client";

import { cn } from "cn";
import { XIcon } from "lucide-react";
import { useRef, type KeyboardEvent } from "react";

import {
  RIGHT_PANE_ID,
  useRightPaneSlot,
  useShell,
  type RightPaneTab,
} from "@/components/shell/shell-context";

export const EMPTY_INSPECTOR = "Select a gap or estimate line to see its details.";
export const EMPTY_ACTIVITY = "No activity yet.";

const TABS: readonly { id: RightPaneTab; label: string }[] = [
  { id: "inspector", label: "Inspector" },
  { id: "activity", label: "Activity" },
];

const tabId = (id: RightPaneTab) => `right-pane-tab-${id}`;
const panelId = (id: RightPaneTab) => `right-pane-panel-${id}`;

/** The one right pane: Inspector and Activity tabs. Pages put content in the Inspector
 * with `RightPaneContent`; both panels stay mounted, so switching tabs keeps their state.
 * Docked at 1440px and wider; below that it overlays the main pane. */
export function RightPane() {
  const { rightPaneOpen, setRightPaneOpen, rightPaneTab, setRightPaneTab } = useShell();
  const { setTarget, contentCount } = useRightPaneSlot();
  const tabRefs = useRef<Partial<Record<RightPaneTab, HTMLButtonElement | null>>>({});
  if (!rightPaneOpen) return null;

  function onKeyDown(event: KeyboardEvent, index: number) {
    // Alt+Left is the browser Back; leave modified keys alone.
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = TABS.length - 1;
    else return;
    event.preventDefault();
    const target = TABS[next].id;
    setRightPaneTab(target);
    tabRefs.current[target]?.focus();
  }

  return (
    <aside
      id={RIGHT_PANE_ID}
      aria-label="Details"
      className="absolute inset-y-0 right-0 z-10 flex w-inspector max-w-full shrink-0 flex-col border-l border-border bg-surface-inspector shadow-lg min-[1440px]:static min-[1440px]:shadow-none"
    >
      <div className="flex h-12 items-center justify-between border-b border-border pr-gutter pl-2">
        <div role="tablist" aria-label="Right pane" className="flex h-full items-stretch gap-1">
          {TABS.map((tab, index) => {
            const active = rightPaneTab === tab.id;
            return (
              <button
                key={tab.id}
                ref={(element) => {
                  tabRefs.current[tab.id] = element;
                }}
                id={tabId(tab.id)}
                type="button"
                role="tab"
                aria-selected={active}
                aria-controls={panelId(tab.id)}
                tabIndex={active ? 0 : -1}
                onClick={() => setRightPaneTab(tab.id)}
                onKeyDown={(event) => onKeyDown(event, index)}
                className={cn(
                  "flex items-center border-b-2 px-3 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary",
                  active
                    ? "border-primary font-semibold text-primary-text"
                    : "border-transparent text-text-secondary hover:text-foreground",
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          aria-label="Close right pane"
          onClick={() => setRightPaneOpen(false)}
          className="flex size-7 items-center justify-center rounded-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
        >
          <XIcon className="size-4" aria-hidden="true" />
        </button>
      </div>
      <div
        id={panelId("inspector")}
        role="tabpanel"
        aria-labelledby={tabId("inspector")}
        hidden={rightPaneTab !== "inspector"}
        className="flex min-h-0 flex-1 flex-col overflow-auto"
      >
        {contentCount === 0 ? (
          <p className="p-gutter text-muted-foreground">{EMPTY_INSPECTOR}</p>
        ) : null}
        <div ref={setTarget} className="flex min-h-0 flex-1 flex-col" />
      </div>
      <div
        id={panelId("activity")}
        role="tabpanel"
        aria-labelledby={tabId("activity")}
        hidden={rightPaneTab !== "activity"}
        className="flex min-h-0 flex-1 flex-col overflow-auto"
      >
        <p className="p-gutter text-muted-foreground">{EMPTY_ACTIVITY}</p>
      </div>
    </aside>
  );
}
