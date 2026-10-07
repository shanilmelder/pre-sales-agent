"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { ConflictInspector } from "@/components/opportunities/conflict-inspector";
import { ConflictStatusPill } from "@/components/opportunities/conflict-status-pill";
import { SeverityPill } from "@/components/opportunities/severity-pill";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import {
  NO_CONFLICTS,
  OPEN_SECTION,
  positionsSummary,
  RESOLVED_SECTION,
  sections,
  typeLabel,
  type Conflict,
  type ConflictsView,
} from "@/lib/conflicts";

/** Conflicts as dense 32px rows, in the order given (the API ranks them critical to low,
 * then newest first). Each row shows the type, the severity pill, the status pill and the
 * positions summary ("Engineering: 24 h · PM: not sized").
 *
 * The list is one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first row); j/k (with single-key shortcuts on) or the arrow keys move between rows, and
 * Enter, Space or a click opens the row. The selected row is `aria-selected`. */
export function ConflictsList({
  label,
  items,
  selectedId = null,
  onOpen,
}: {
  label: string;
  items: readonly Conflict[];
  selectedId?: string | null;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (item: Conflict, viaKeyboard: boolean) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && items.some((i) => i.id === id)) ??
    items[0]?.id;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      container.current?.querySelectorAll<HTMLButtonElement>("button[data-conflict-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === event.target);
    const next =
      index === -1 ? 0 : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <div
      ref={container}
      role="grid"
      aria-label={label}
      onKeyDown={onKeyDown}
      className="flex flex-col"
    >
      {items.map((item) => {
        const selected = item.id === selectedId;
        return (
          <div
            key={item.id}
            role="row"
            aria-selected={selected}
            className={`border-b border-border ${selected ? "bg-muted" : "hover:bg-muted/60"}`}
          >
            <div role="gridcell">
              <button
                type="button"
                data-conflict-row=""
                data-conflict-id={item.id}
                tabIndex={item.id === tabStopId ? 0 : -1}
                onFocus={() => setFocusedId(item.id)}
                // A keyboard-activated click has no pointer clicks (detail 0).
                onClick={(event) => onOpen?.(item, event.detail === 0)}
                className="flex min-h-row w-full items-center gap-3 rounded-sm px-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <span className="w-24 shrink-0 truncate text-label">{typeLabel(item.type)}</span>
                <SeverityPill severity={item.severity} />
                <ConflictStatusPill status={item.status} />
                {item.requirement ? (
                  <span className="inline-flex h-5 shrink-0 items-center rounded-sm border border-border bg-background px-1.5 font-mono text-meta text-muted-foreground">
                    {item.requirement.label}
                  </span>
                ) : null}
                <span className="min-w-0 flex-1 truncate text-body [font-variant-numeric:tabular-nums]">
                  {positionsSummary(item.positions)}
                </span>
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** The Conflicts tab: Open and Resolved sections of rows in the main pane, and the selected
 * Conflict's inspector in the right pane (opened if closed). Read-only for everyone. */
export function ConflictsSection({ initial }: { initial: ConflictsView }) {
  const openHeadingId = useId();
  const resolvedHeadingId = useId();
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);

  const { open, resolved } = sections(initial.conflicts);
  const selected =
    selectedId === null ? null : (initial.conflicts.find((c) => c.id === selectedId) ?? null);

  // The pane's content unmounts on close: reopening it must not take focus again.
  const [paneWasOpen, setPaneWasOpen] = useState(rightPaneOpen);
  if (paneWasOpen !== rightPaneOpen) {
    setPaneWasOpen(rightPaneOpen);
    if (!rightPaneOpen) setFocusRequest(0);
  }

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(`[data-conflict-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function openRow(item: Conflict, viaKeyboard: boolean) {
    setSelectedId(item.id);
    returnFocusTo.current = viaKeyboard ? item.id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  if (initial.conflicts.length === 0) {
    return <p className="text-muted-foreground">{NO_CONFLICTS}</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <section aria-labelledby={openHeadingId} className="flex flex-col gap-2">
        <h3 id={openHeadingId} className="text-body-strong">
          {OPEN_SECTION}{" "}
          <span className="text-muted-foreground [font-variant-numeric:tabular-nums]">
            {open.length}
          </span>
        </h3>
        {open.length > 0 ? (
          <ConflictsList
            label="Open Conflicts"
            items={open}
            selectedId={selected?.id ?? null}
            onOpen={openRow}
          />
        ) : (
          <p className="text-muted-foreground">No open Conflicts.</p>
        )}
      </section>
      {resolved.length > 0 ? (
        <section aria-labelledby={resolvedHeadingId} className="flex flex-col gap-2">
          <h3 id={resolvedHeadingId} className="text-body-strong">
            {RESOLVED_SECTION}{" "}
            <span className="text-muted-foreground [font-variant-numeric:tabular-nums]">
              {resolved.length}
            </span>
          </h3>
          <ConflictsList
            label="Resolved Conflicts"
            items={resolved}
            selectedId={selected?.id ?? null}
            onOpen={openRow}
          />
        </section>
      ) : null}
      {selected ? (
        <RightPaneContent>
          <ConflictInspector
            key={selected.id}
            conflict={selected}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </div>
  );
}
