"use client";

import { useEffect, useRef, useState } from "react";

import { CatalogueCreateForm } from "@/components/admin/catalogue-create-form";
import { CatalogueInspector } from "@/components/admin/catalogue-inspector";
import { CatalogueTable } from "@/components/admin/catalogue-table";
import { isEditableTarget } from "@/components/shell/keyboard-shortcuts";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import { upsert, type CatalogueEntry } from "@/lib/catalogue";

/** Admin → Catalogue: the list in the main pane; the selected entry's inspector, or the
 * create form (`c`), in the right pane. Saved changes update the list row in place; new
 * server data replaces the rows. */
export function CatalogueAdmin({ initialEntries }: { initialEntries: readonly CatalogueEntry[] }) {
  const { rightPaneOpen, setRightPaneOpen, singleKeyShortcuts, dialog } = useShell();
  const [entries, setEntries] = useState<readonly CatalogueEntry[]>(initialEntries);
  const [syncedFrom, setSyncedFrom] = useState(initialEntries);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);

  // A server refresh (e.g. router.refresh or revisiting the page) brings new rows.
  if (initialEntries !== syncedFrom) {
    setSyncedFrom(initialEntries);
    setEntries(initialEntries);
  }

  const selected = entries.find((entry) => entry.id === selectedId) ?? null;

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(`[data-entry-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function startCreate() {
    setCreating(true);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  // `c` opens the create form. The shell leaves it to this page (it would otherwise start
  // an Opportunity), so only the keys the shell ignores reach here.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "c" || event.isComposing || event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!singleKeyShortcuts || dialog || isEditableTarget(event.target)) return;
      if (event.target instanceof Element && event.target.closest('[role="menu"]')) return;
      event.preventDefault();
      startCreate();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // `startCreate` only reads `rightPaneOpen` and the setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [singleKeyShortcuts, dialog, rightPaneOpen]);

  function open(entry: CatalogueEntry, viaKeyboard: boolean) {
    setCreating(false);
    setSelectedId(entry.id);
    returnFocusTo.current = viaKeyboard ? entry.id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function replace(next: CatalogueEntry) {
    setEntries((current) => upsert(current, next));
  }

  function created(entry: CatalogueEntry) {
    replace(entry);
    setCreating(false);
    setSelectedId(entry.id);
    returnFocusTo.current = entry.id;
    setFocusRequest((n) => n + 1);
  }

  function cancelCreate(viaKey: boolean) {
    setCreating(false);
    if (viaKey) {
      const row =
        document.querySelector<HTMLElement>(`[data-entry-id="${selectedId}"]`) ??
        document.querySelector<HTMLElement>("[data-entry-row]");
      row?.focus();
    }
  }

  return (
    <>
      <div className="flex items-center justify-between gap-2 px-gutter pb-2">
        <p className="text-meta text-muted-foreground">
          Every Checklist, Assessment line, Estimate line and Actual is classified by these entries.
        </p>
        <button
          type="button"
          onClick={startCreate}
          aria-keyshortcuts="c"
          className="h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
        >
          New entry
        </button>
      </div>
      <CatalogueTable entries={entries} selectedId={selectedId} onOpen={open} />
      {creating ? (
        <RightPaneContent>
          <CatalogueCreateForm onCreated={created} onCancel={cancelCreate} />
        </RightPaneContent>
      ) : selected ? (
        <RightPaneContent>
          <CatalogueInspector
            key={selected.id}
            entry={selected}
            onChange={replace}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </>
  );
}
