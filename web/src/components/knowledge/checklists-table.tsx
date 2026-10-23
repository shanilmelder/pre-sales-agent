"use client";

import { PencilLineIcon } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { MandatoryLabel } from "@/components/knowledge/mandatory-label";
import { RetiredLabel } from "@/components/knowledge/sources-table";
import { useShell } from "@/components/shell/shell-context";
import {
  checklistStatus,
  domainLabel,
  EMPTY_STATE,
  EMPTY_STATE_AUTHOR,
  scopeText,
  type Checklist,
} from "@/lib/checklists";

const labelClass =
  "inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground";

/** "Draft": an icon and a label (an unpublished draft is being edited). */
export function DraftLabel() {
  return (
    <span data-label="draft" className={labelClass}>
      <PencilLineIcon aria-hidden="true" className="size-3 shrink-0 text-muted-foreground" />
      Draft
    </span>
  );
}

/** The Checklists as 32px rows: name, domain, scope, status (published version, Draft,
 * Retired), items and the Mandatory count. The name buttons are one Tab stop (roving
 * tabindex); j/k (or the arrow keys) move between rows and Enter opens the inspector. */
export function ChecklistsTable({
  checklists,
  selectedId,
  mayAuthor,
  onOpen,
}: {
  checklists: readonly Checklist[];
  selectedId: string | null;
  /** Whether the empty state invites pressing `c`. */
  mayAuthor: boolean;
  /** `viaKeyboard` is true when the row was opened with Enter or Space, not a pointer. */
  onOpen: (checklist: Checklist, viaKeyboard: boolean) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const root = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && checklists.some((c) => c.id === id)) ??
    checklists[0]?.id;

  if (checklists.length === 0) {
    return (
      <p className="text-muted-foreground">{mayAuthor ? EMPTY_STATE_AUTHOR : EMPTY_STATE}</p>
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      root.current?.querySelectorAll<HTMLButtonElement>("button[data-checklist-row]") ?? [],
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
        <caption className="sr-only">Checklists, by name</caption>
        <thead className="text-label text-muted-foreground">
          <tr className="h-row border-b border-border">
            <th scope="col" className="px-3 font-medium">
              Name
            </th>
            <th scope="col" className="w-28 px-2 font-medium">
              Domain
            </th>
            <th scope="col" className="w-64 px-2 font-medium">
              Scope
            </th>
            <th scope="col" className="w-48 px-2 font-medium">
              Status
            </th>
            <th scope="col" className="w-40 px-2 font-medium">
              Items
            </th>
          </tr>
        </thead>
        <tbody>
          {checklists.map((checklist) => {
            const selected = checklist.id === selectedId;
            const scope = checklist.current_version === null ? "—" : scopeText(checklist);
            return (
              <tr
                key={checklist.id}
                className={`h-row border-b border-border ${selected ? "bg-muted" : "hover:bg-muted/60"}`}
              >
                <td className="truncate px-3">
                  <button
                    type="button"
                    data-checklist-row=""
                    data-checklist-id={checklist.id}
                    tabIndex={checklist.id === tabStopId ? 0 : -1}
                    aria-current={selected ? "true" : undefined}
                    onFocus={() => setFocusedId(checklist.id)}
                    // A keyboard-activated click has no pointer clicks (detail 0).
                    onClick={(event) => onOpen(checklist, event.detail === 0)}
                    className="w-full truncate rounded-sm text-left text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    {checklist.name}
                  </button>
                </td>
                <td className="truncate px-2">{domainLabel(checklist.domain)}</td>
                <td className="truncate px-2" title={scope}>
                  {scope}
                </td>
                <td className="px-2">
                  <span className="flex flex-wrap items-center gap-1">
                    {checklist.retired ? (
                      <RetiredLabel />
                    ) : (
                      <span className="text-body">{checklistStatus(checklist)}</span>
                    )}
                    {checklist.draft && checklist.current_version !== null ? <DraftLabel /> : null}
                  </span>
                </td>
                <td className="px-2">
                  <span className="flex flex-wrap items-center gap-1">
                    <span className="text-numeric">{checklist.item_count}</span>
                    {checklist.mandatory_count > 0 ? (
                      <MandatoryLabel count={checklist.mandatory_count} />
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
