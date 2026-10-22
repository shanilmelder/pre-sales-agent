"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";

import { createChecklist } from "@/app/knowledge/checklists/actions";
import { ChecklistInspector } from "@/components/knowledge/checklist-inspector";
import { ChecklistsTable } from "@/components/knowledge/checklists-table";
import { isEditableTarget } from "@/components/shell/keyboard-shortcuts";
import { useAnnounce } from "@/components/shell/live-region";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import {
  canAuthor,
  DOMAINS,
  fieldError,
  NAME_MAX,
  upsert,
  type Checklist,
  type ChecklistDomain,
} from "@/lib/checklists";
import type { Permission } from "@/lib/navigation";

/** An active catalogue entry, for scope tags (Integration Types) and affected areas (both
 * kinds). */
export type CatalogueOption = {
  id: string;
  kind: "integration_type" | "work_package";
  name: string;
};

const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";
const inputClass =
  "h-7 w-full rounded-md border border-input bg-background px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary";

/** Knowledge → Checklists: the list in the main pane; the selected Checklist's inspector,
 * or the create form (`c`, authors only), in the right pane. */
export function ChecklistsTab({
  initialChecklists,
  catalogue,
  permissions,
}: {
  initialChecklists: readonly Checklist[];
  catalogue: readonly CatalogueOption[];
  permissions: readonly Permission[];
}) {
  const { rightPaneOpen, setRightPaneOpen, singleKeyShortcuts, dialog } = useShell();
  const [checklists, setChecklists] = useState<readonly Checklist[]>(initialChecklists);
  const [syncedFrom, setSyncedFrom] = useState(initialChecklists);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);
  const mayAuthor = canAuthor(permissions);

  // A server refresh (e.g. revisiting the page) brings new rows.
  if (initialChecklists !== syncedFrom) {
    setSyncedFrom(initialChecklists);
    setChecklists(initialChecklists);
  }

  const selected = checklists.find((c) => c.id === selectedId) ?? null;

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(`[data-checklist-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function startCreate() {
    if (!mayAuthor) return;
    setCreating(true);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  // `c` opens the create form. The shell leaves it to this page (it would otherwise start an
  // Opportunity), so only the keys the shell ignores reach here.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "c" || event.isComposing || event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!singleKeyShortcuts || dialog || isEditableTarget(event.target)) return;
      if (event.target instanceof Element && event.target.closest('[role="menu"]')) return;
      if (!mayAuthor) return;
      event.preventDefault();
      startCreate();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // `startCreate` only reads `rightPaneOpen`, `mayAuthor` and the setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [singleKeyShortcuts, dialog, rightPaneOpen, mayAuthor]);

  function open(checklist: Checklist, viaKeyboard: boolean) {
    setCreating(false);
    setSelectedId(checklist.id);
    returnFocusTo.current = viaKeyboard ? checklist.id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function replace(next: Checklist) {
    setChecklists((current) => upsert(current, next));
  }

  function created(checklist: Checklist) {
    replace(checklist);
    setCreating(false);
    setSelectedId(checklist.id);
    returnFocusTo.current = checklist.id;
    setFocusRequest((n) => n + 1);
  }

  return (
    <>
      {mayAuthor ? (
        <div className="flex items-center gap-2 px-gutter pb-2">
          <button
            type="button"
            onClick={startCreate}
            aria-keyshortcuts="c"
            className={`${buttonClass} ml-auto`}
          >
            New Checklist
          </button>
        </div>
      ) : null}
      <ChecklistsTable
        checklists={checklists}
        selectedId={selectedId}
        mayAuthor={mayAuthor}
        onOpen={open}
      />
      {creating ? (
        <RightPaneContent>
          <ChecklistCreateForm onCreated={created} onCancel={() => setCreating(false)} />
        </RightPaneContent>
      ) : selected ? (
        <RightPaneContent>
          <ChecklistInspector
            key={selected.id}
            checklist={selected}
            catalogue={catalogue}
            mayAuthor={mayAuthor}
            onChange={replace}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </>
  );
}

/** A name and a domain; the new Checklist starts as an empty draft. */
export function ChecklistCreateForm({
  onCreated,
  onCancel,
}: {
  onCreated: (checklist: Checklist) => void;
  onCancel: () => void;
}) {
  const announce = useAnnounce();
  const [name, setName] = useState("");
  const [domain, setDomain] = useState<ChecklistDomain>("engineering");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const headingId = useId();
  const nameId = useId();
  const domainId = useId();
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  function submit() {
    if (pending) return;
    const invalid = fieldError("name", name);
    if (invalid) {
      setError(invalid);
      nameRef.current?.focus();
      return;
    }
    setError(null);
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof createChecklist>>;
      try {
        result = await createChecklist({ name, domain });
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok") {
        announce(`Created ${result.checklist.name}`);
        onCreated(result.checklist);
      } else {
        const message =
          result.kind === "invalid"
            ? result.detail
            : result.kind === "forbidden"
              ? "Only engineering, PM or security reviewers and administrators can write Checklists."
              : "The Checklist could not be created. Try again.";
        setError(message);
        announce(message);
      }
    });
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 p-gutter">
      <h3 id={headingId} className="text-section">
        New Checklist
      </h3>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            onCancel();
          }
        }}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor={nameId} className="text-label text-muted-foreground">
            Name
          </label>
          <input
            id={nameId}
            ref={nameRef}
            type="text"
            value={name}
            maxLength={NAME_MAX * 2}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${nameId}-error` : undefined}
            onChange={(event) => setName(event.target.value)}
            className={inputClass}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={domainId} className="text-label text-muted-foreground">
            Domain
          </label>
          <select
            id={domainId}
            value={domain}
            onChange={(event) => setDomain(event.target.value as ChecklistDomain)}
            className={inputClass}
          >
            {DOMAINS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </div>
        {error ? (
          <p id={`${nameId}-error`} className="text-meta text-destructive">
            {error}
          </p>
        ) : null}
        <div className="flex gap-2">
          <button type="submit" aria-disabled={pending || undefined} className={buttonClass}>
            Create
          </button>
          <button type="button" onClick={onCancel} className={buttonClass}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
