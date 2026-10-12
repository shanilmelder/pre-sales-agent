"use client";

import { ArchiveIcon, CircleCheckIcon } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { useShell } from "@/components/shell/shell-context";
import { EMPTY_STATE, groupByKind, type CatalogueEntry } from "@/lib/catalogue";

/** The entry's status: always an icon and a label, never colour alone. */
export function StatusPill({ entry }: { entry: CatalogueEntry }) {
  const retired = entry.retired;
  const Icon = retired ? ArchiveIcon : CircleCheckIcon;
  return (
    <span
      data-entry-status={entry.status}
      className="inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground"
    >
      <Icon
        className={`size-3 shrink-0 ${retired ? "text-muted-foreground" : "text-resolved"}`}
        aria-hidden="true"
      />
      {retired ? "Retired" : "Active"}
    </span>
  );
}

/** The catalogue as two groups, Integration Types and Work Packages, of 32px rows with the
 * code, name, current version and status. The rows are one Tab stop (roving tabindex); j/k
 * (or the arrow keys) move between rows across both groups and Enter opens the inspector. */
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
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && entries.some((e) => e.id === id)) ??
    groupByKind(entries).find((g) => g.entries.length > 0)?.entries[0]?.id;

  if (entries.length === 0) {
    return <p className="p-gutter text-muted-foreground">{EMPTY_STATE}</p>;
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
    <div ref={root} onKeyDown={onKeyDown} className="flex flex-col gap-4">
      {groupByKind(entries).map((group) => (
        <section key={group.kind} aria-labelledby={`catalogue-${group.kind}`}>
          <h2
            id={`catalogue-${group.kind}`}
            className="px-gutter py-1 text-label text-muted-foreground"
          >
            {group.plural}
          </h2>
          {group.entries.length === 0 ? (
            <p className="px-gutter text-meta text-muted-foreground">None yet.</p>
          ) : (
            <table className="w-full table-fixed border-collapse text-left">
              <caption className="sr-only">{group.plural}</caption>
              <thead className="text-label text-muted-foreground">
                <tr className="h-row border-b border-border">
                  <th scope="col" className="w-1/5 px-gutter font-medium">
                    Code
                  </th>
                  <th scope="col" className="px-2 font-medium">
                    Name
                  </th>
                  <th scope="col" className="w-20 px-2 font-medium">
                    Version
                  </th>
                  <th scope="col" className="w-28 px-2 font-medium">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {group.entries.map((entry) => {
                  const selected = entry.id === selectedId;
                  return (
                    <tr
                      key={entry.id}
                      className={`h-row border-b border-border ${selected ? "bg-muted" : "hover:bg-muted/60"}`}
                    >
                      <td className="truncate px-gutter text-numeric text-muted-foreground">
                        {entry.code}
                      </td>
                      <td className="truncate px-2">
                        <button
                          type="button"
                          data-entry-row=""
                          data-entry-id={entry.id}
                          tabIndex={entry.id === tabStopId ? 0 : -1}
                          aria-current={selected ? "true" : undefined}
                          onFocus={() => setFocusedId(entry.id)}
                          // A keyboard-activated click has no pointer clicks (detail 0).
                          onClick={(event) => onOpen(entry, event.detail === 0)}
                          className="w-full truncate rounded-sm text-left text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
                        >
                          {entry.name}
                        </button>
                      </td>
                      <td className="px-2 text-numeric">v{entry.current_version}</td>
                      <td className="px-2">
                        <StatusPill entry={entry} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      ))}
    </div>
  );
}
