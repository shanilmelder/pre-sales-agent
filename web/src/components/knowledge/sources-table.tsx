"use client";

import { ArchiveIcon, HourglassIcon } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { ParseStatusPill } from "@/components/opportunities/sources-list";
import { useShell } from "@/components/shell/shell-context";
import {
  EMPTY_STATE,
  formatDate,
  NO_MATCHES,
  parseFailureReason,
  type KnowledgeSource,
} from "@/lib/knowledge-sources";

const labelClass =
  "inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground";

/** "Stale": an icon and a label, never colour alone. */
export function StaleLabel() {
  return (
    <span data-label="stale" className={labelClass}>
      <HourglassIcon aria-hidden="true" className="size-3 shrink-0 text-gap" />
      Stale
    </span>
  );
}

/** "Retired": an icon and a label, never colour alone. */
export function RetiredLabel() {
  return (
    <span data-label="retired" className={labelClass}>
      <ArchiveIcon aria-hidden="true" className="size-3 shrink-0 text-muted-foreground" />
      Retired
    </span>
  );
}

/** The Knowledge Sources as 32px rows: title, product, Integration Types, owner, last
 * reviewed (with the Stale label), version and parse status (a failed parse shows its
 * reason). The title buttons are one Tab stop (roving tabindex); j/k (or the arrow keys)
 * move between rows and Enter opens the inspector. */
export function SourcesTable({
  sources,
  total,
  selectedId,
  onOpen,
}: {
  sources: readonly KnowledgeSource[];
  /** How many Sources exist before filtering, to tell "none yet" from "none match". */
  total: number;
  selectedId: string | null;
  /** `viaKeyboard` is true when the row was opened with Enter or Space, not a pointer. */
  onOpen: (source: KnowledgeSource, viaKeyboard: boolean) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const root = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && sources.some((s) => s.id === id)) ??
    sources[0]?.id;

  if (sources.length === 0) {
    return (
      <p className="p-gutter text-muted-foreground">{total === 0 ? EMPTY_STATE : NO_MATCHES}</p>
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      root.current?.querySelectorAll<HTMLButtonElement>("button[data-source-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === document.activeElement);
    const next =
      index === -1 ? 0 : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <div ref={root} onKeyDown={onKeyDown}>
      <table className="w-full table-fixed border-collapse text-left">
        <caption className="sr-only">Knowledge Sources, longest-unreviewed first</caption>
        <thead className="text-label text-muted-foreground">
          <tr className="h-row border-b border-border">
            <th scope="col" className="px-gutter font-medium">
              Title
            </th>
            <th scope="col" className="w-32 px-2 font-medium">
              Product
            </th>
            <th scope="col" className="w-48 px-2 font-medium">
              Integration Types
            </th>
            <th scope="col" className="w-36 px-2 font-medium">
              Owner
            </th>
            <th scope="col" className="w-48 px-2 font-medium">
              Last reviewed
            </th>
            <th scope="col" className="w-16 px-2 font-medium">
              Version
            </th>
            <th scope="col" className="w-56 px-2 font-medium">
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => {
            const selected = source.id === selectedId;
            const types = source.integration_types.map((t) => t.name).join(", ");
            return (
              <tr
                key={source.id}
                className={`h-row border-b border-border ${selected ? "bg-muted" : "hover:bg-muted/60"}`}
              >
                <td className="truncate px-gutter">
                  <button
                    type="button"
                    data-source-row=""
                    data-source-id={source.id}
                    tabIndex={source.id === tabStopId ? 0 : -1}
                    aria-current={selected ? "true" : undefined}
                    onFocus={() => setFocusedId(source.id)}
                    // A keyboard-activated click has no pointer clicks (detail 0).
                    onClick={(event) => onOpen(source, event.detail === 0)}
                    className="w-full truncate rounded-sm text-left text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    {source.title}
                  </button>
                </td>
                <td className="truncate px-2" title={source.product}>
                  {source.product}
                </td>
                <td className="truncate px-2" title={types}>
                  {types}
                </td>
                <td className="truncate px-2" title={source.owner.name}>
                  {source.owner.name}
                </td>
                <td className="px-2">
                  <span className="inline-flex items-center gap-2">
                    <span className="text-numeric">{formatDate(source.last_reviewed_on)}</span>
                    {source.stale ? <StaleLabel /> : null}
                  </span>
                </td>
                <td className="px-2 text-numeric">v{source.version}</td>
                <td className="px-2">
                  <span className="flex flex-wrap items-center gap-1">
                    <ParseStatusPill parse={source.parse} />
                    {source.retired ? <RetiredLabel /> : null}
                    {source.parse.status === "failed" ? (
                      <span className="text-meta text-blocker">
                        {parseFailureReason(source.parse.error_code)}
                      </span>
                    ) : null}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
