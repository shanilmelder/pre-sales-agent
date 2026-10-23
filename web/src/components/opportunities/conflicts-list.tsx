"use client";

import { ArrowUpIcon, CircleAlertIcon, CircleCheckIcon } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent } from "react";

import { Card } from "@/components/ui/card";
import { EmptyTabCard } from "@/components/ui/empty-tab-card";
import { Pill } from "@/components/ui/pill";
import { ConflictInspector } from "@/components/opportunities/conflict-inspector";
import { useShell } from "@/components/shell/shell-context";
import {
  escalatedLabel,
  headerCounts,
  NO_CONFLICTS_BODY,
  NO_CONFLICTS_TITLE,
  NO_OPEN_CONFLICTS,
  OPEN_ASSESSMENTS,
  RESOLVED_SECTION,
  resolvedLine,
  resolvedTag,
  rowSubline,
  sections,
  statusInfo,
  type Conflict,
  type ConflictsView,
} from "@/lib/conflicts";
import { tabHref } from "@/lib/workspace";

/** The right side of an open row: "Open" in red, or "Escalated to Sam" in amber with the
 * up-arrow (never colour alone: always the words). */
function OpenRowStatus({ item }: { item: Conflict }) {
  if (item.status === "escalated" && item.escalated_to) {
    return (
      <span className="flex shrink-0 items-center gap-1 text-label text-gap">
        <ArrowUpIcon aria-hidden="true" className="size-3.5 shrink-0" />
        {escalatedLabel(item)}
      </span>
    );
  }
  const status = statusInfo(item.status);
  return <span className={`shrink-0 text-label ${status.tone}`}>{status.label}</span>;
}

/** One row's content: the open (red alert) or resolved (green check) icon, the summary as the
 * title, a muted sub-line, and the status or the resolved tag on the right. */
function RowContent({ item, variant }: { item: Conflict; variant: "open" | "resolved" }) {
  const line = variant === "open" ? rowSubline(item) : resolvedLine(item);
  return (
    <>
      {variant === "open" ? (
        <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-blocker" />
      ) : (
        <CircleCheckIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-resolved" />
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-body-strong [overflow-wrap:anywhere]">{item.summary}</span>
        {line ? (
          <span className="text-meta text-muted-foreground [overflow-wrap:anywhere]">{line}</span>
        ) : null}
      </span>
      {variant === "open" ? (
        <OpenRowStatus item={item} />
      ) : (
        <Pill tone="neutral" className="shrink-0">
          {resolvedTag(item)}
        </Pill>
      )}
    </>
  );
}

/** Conflicts as card rows, in the order given (the API ranks them critical to low, then newest
 * first), separated by top borders. An open row has a 3px red bar on its left, the red alert
 * icon, the summary, "{type} · {Requirement}" (plus "Detected from text", 6.2) and "Open" or
 * "Escalated to Sam"; a resolved row has the green check, the decision (or the system's reason)
 * and "Resolved by Alex" or "No longer present". The selected row gets the primary tint.
 *
 * The list is one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first row); j/k (with single-key shortcuts on) or the arrow keys move between rows, and
 * Enter, Space or a click opens the row. The selected row is `aria-selected`. */
export function ConflictsList({
  label,
  items,
  variant = "open",
  selectedId = null,
  onOpen,
}: {
  label: string;
  items: readonly Conflict[];
  variant?: "open" | "resolved";
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
            className={`border-t border-border first:border-t-0 ${variant === "open" ? "shadow-[inset_3px_0_0_var(--blocker)]" : ""} ${selected ? "bg-primary-tint" : "hover:bg-surface-alt"}`}
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
                className="flex w-full items-start gap-3 px-5 py-3.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset"
              >
                <RowContent item={item} variant={variant} />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** The Conflicts tab body: the "Conflicts" heading with "{n} open · {n} resolved", a card of
 * open rows, the selected Conflict's decision card inline under it (where those allowed resolve
 * or escalate it, Story 6.3), and the "Resolved {n}" card. The first open Conflict is selected
 * on load, and the next open one after a resolve; a keyboard open moves focus to the decision
 * card's title. */
export function ConflictsSection({
  initial,
  opportunityId = "",
}: {
  initial: ConflictsView;
  opportunityId?: string;
}) {
  const headingId = useId();
  const resolvedHeadingId = useId();
  const { open, resolved } = sections(initial.conflicts);
  // Pinned to the first open Conflict on load; falls back to the first open one only when the
  // pinned Conflict is gone.
  const [selectedId, setSelectedId] = useState<string | null>(() => open[0]?.id ?? null);
  const [focusRequest, setFocusRequest] = useState(0);

  const selected =
    selectedId === null
      ? null
      : (initial.conflicts.find((c) => c.id === selectedId) ?? open[0] ?? null);

  function openRow(item: Conflict, viaKeyboard: boolean) {
    setSelectedId(item.id);
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
  }

  /** After a resolve, the next open Conflict (its title takes focus, as the form's button is
   * gone); after an escalation, the selection stays. */
  function decided(decidedId: string, kind: "resolved" | "escalated") {
    if (kind === "escalated") return;
    setSelectedId(open.find((c) => c.id !== decidedId)?.id ?? null);
    setFocusRequest((n) => n + 1);
  }

  const header = (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 id={headingId} className="text-section">
        Conflicts
      </h2>
      {initial.conflicts.length > 0 ? (
        <span className="text-[13px] leading-[1.4] text-muted-foreground [font-variant-numeric:tabular-nums]">
          {headerCounts(initial.conflicts)}
        </span>
      ) : null}
    </div>
  );

  if (initial.conflicts.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {header}
        <EmptyTabCard
          title={NO_CONFLICTS_TITLE}
          body={NO_CONFLICTS_BODY}
          actionLabel={OPEN_ASSESSMENTS}
          href={tabHref(opportunityId, "assessments")}
        />
      </div>
    );
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      {header}
      <Card className="min-w-0 overflow-hidden">
        {open.length > 0 ? (
          <ConflictsList
            label="Open Conflicts"
            items={open}
            selectedId={selected?.id ?? null}
            onOpen={openRow}
          />
        ) : (
          <p className="px-5 py-3.5 text-muted-foreground">{NO_OPEN_CONFLICTS}</p>
        )}
      </Card>
      {selected ? (
        <ConflictInspector
          key={`${selected.id}:${selected.row_version}`}
          conflict={selected}
          focusRequest={focusRequest}
          opportunityId={opportunityId}
          reviewers={initial.reviewers}
          onDecided={(kind) => decided(selected.id, kind)}
        />
      ) : null}
      {resolved.length > 0 ? (
        <Card role="region" aria-labelledby={resolvedHeadingId} className="min-w-0 overflow-hidden">
          <div className="border-b border-border px-5 py-[18px]">
            <h3 id={resolvedHeadingId} className="text-section">
              {RESOLVED_SECTION}{" "}
              <span className="text-muted-foreground [font-variant-numeric:tabular-nums]">
                {resolved.length}
              </span>
            </h3>
          </div>
          <ConflictsList
            label="Resolved Conflicts"
            items={resolved}
            variant="resolved"
            selectedId={selected?.id ?? null}
            onOpen={openRow}
          />
        </Card>
      ) : null}
    </section>
  );
}
