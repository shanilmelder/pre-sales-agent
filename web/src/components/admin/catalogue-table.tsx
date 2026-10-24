"use client";

import { ArchiveIcon, CircleCheckIcon } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { BODY_ROW, CardTable } from "@/components/admin/card-table";
import { useShell } from "@/components/shell/shell-context";
import { Pill } from "@/components/ui/pill";
import { EMPTY_STATE, groupByKind, kindLabel, type CatalogueEntry } from "@/lib/catalogue";

/** The entry's status: always an icon and a label, never colour alone. */
export function StatusPill({ entry }: { entry: CatalogueEntry }) {
  const retired = entry.retired;
  const Icon = retired ? ArchiveIcon : CircleCheckIcon;
  return (
    <Pill
      data-entry-status={entry.status}
      tone={retired ? "neutral" : "resolved"}
      icon={<Icon />}
      className="shrink-0"
    >
      {retired ? "Retired" : "Active"}
    </Pill>
  );
}

const GRID = "grid-cols-[120px_minmax(0,1fr)_180px_120px]";

/** The catalogue as one card table: Integration Types first, then Work Packages, each row
 * with the code, name, kind and status. The rows are one Tab stop (roving tabindex); j/k (or
 * the arrow keys) move between rows and Enter opens the inspector. */
export function CatalogueTable({
  entries,
  selectedId,
  onOpen,
}: {
  entries: readonly CatalogueEntry[];
  selectedId: string | null;
  /** `viaKeyboard` is true when the row was opened with Enter or Space, not a pointer. */
  onOpen: (entry: CatalogueEntry, viaKeyboard: boolean) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const root = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const ordered = groupByKind(entries).flatMap((group) => group.entries);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && entries.some((e) => e.id === id)) ??
    ordered[0]?.id;

  if (entries.length === 0) {
    return <p className="border-t border-border px-5 py-4 text-text-secondary">{EMPTY_STATE}</p>;
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      root.current?.querySelectorAll<HTMLButtonElement>("button[data-entry-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === document.activeElement);
    const next =
      index === -1 ? 0 : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <div ref={root} onKeyDown={onKeyDown}>
      <CardTable label="Catalogue entries" grid={GRID} columns={["Code", "Name", "Kind", "Status"]}>
        {ordered.map((entry) => {
          const selected = entry.id === selectedId;
          return (
            <div
              key={entry.id}
              role="row"
              className={`relative py-4 ${BODY_ROW} ${GRID} ${
                selected ? "bg-primary-tint" : "hover:bg-muted/60"
              }`}
            >
              <div role="cell" className="min-w-0 truncate text-meta font-semibold text-text-secondary">
                {entry.code}
              </div>
              <div role="rowheader" className="min-w-0">
                <button
                  type="button"
                  data-entry-row=""
                  data-entry-id={entry.id}
                  tabIndex={entry.id === tabStopId ? 0 : -1}
                  aria-current={selected ? "true" : undefined}
                  onFocus={() => setFocusedId(entry.id)}
                  // A keyboard-activated click has no pointer clicks (detail 0).
                  onClick={(event) => onOpen(entry, event.detail === 0)}
                  className="block max-w-full truncate text-left text-body-strong outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset"
                >
                  {entry.name}
                </button>
              </div>
              <div role="cell" className="min-w-0 truncate">
                {kindLabel(entry.kind)}
              </div>
              <div role="cell">
                <StatusPill entry={entry} />
              </div>
            </div>
          );
        })}
      </CardTable>
    </div>
  );
}
