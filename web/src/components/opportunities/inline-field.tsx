"use client";

import { CalendarIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { loadOpportunity, updateOpportunity } from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import {
  codePointLength,
  formatDate,
  NO_ACCESS_TO_OPPORTUNITY,
  staleMessage,
  TITLE_MAX,
  utcToday,
  type Opportunity,
} from "@/lib/opportunities";

const SAVE_FAILED = "The change could not be saved. Try again.";
const NOT_OWNER = "Only the owner can edit this Opportunity.";
const RELOAD_FAILED = "The Opportunity could not be reloaded. Try again.";
const TITLE_TOO_LONG = `The title can be at most ${TITLE_MAX} characters.`;

const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label text-foreground outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";

type InlineFieldProps = {
  /** The edit button's accessible name, e.g. "Edit title". */
  label: string;
  /** The input's accessible name, e.g. "Title". */
  inputLabel: string;
  /** `textarea` is multi-line: Enter still saves, Shift+Enter starts a new line. */
  type: "text" | "date" | "textarea";
  /** The value the input starts from. */
  value: string;
  /** Text the input starts from instead of `value` (e.g. the user's unsaved text after a
   * failed save); saving still compares against `value`. */
  draft?: string;
  /** How the value shows when not editing. */
  children: ReactNode;
  /** The earliest date a date input offers. */
  min?: string;
  /** A reason shown under the field (and linked to its button). */
  error?: string | null;
  /** True while nothing may be edited (a save in flight, or a stale view). */
  locked?: boolean;
  /** Bump to start editing from outside (e.g. the `e` shortcut); 0 does nothing. A field
   * mounted with a value above 0 starts editing. */
  editRequest?: number;
  /** Called on blur or Enter with the new text, only when it differs from `value`. */
  onCommit: (next: string) => void;
  className?: string;
  inputClassName?: string;
};

/** Click-to-edit: shows `children` under a button named `label`; clicking it swaps in an
 * input. Blur or Enter saves (nothing when unchanged), Esc reverts and leaves the field.
 * After Enter or Esc focus goes back to the button. */
export function InlineField({
  label,
  inputLabel,
  type,
  value,
  draft: keptDraft,
  children,
  min,
  error,
  locked = false,
  editRequest = 0,
  onCommit,
  className,
  inputClassName,
}: InlineFieldProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const finished = useRef(false);
  const refocus = useRef(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const errorId = useId();
  // Starts at 0, so a field mounted with a pending request (e.g. the inspector opened by
  // the `e` shortcut) starts editing too.
  const [handledRequest, setHandledRequest] = useState(0);
  if (handledRequest !== editRequest) {
    setHandledRequest(editRequest);
    if (editRequest > 0 && !locked && !editing) {
      // `finished` is reset by the effect below once the input shows.
      setDraft(keptDraft ?? value);
      setEditing(true);
    }
  }

  useEffect(() => {
    if (editing) {
      finished.current = false;
      inputRef.current?.focus();
    } else if (refocus.current) {
      refocus.current = false;
      buttonRef.current?.focus();
    }
  }, [editing]);

  function start() {
    if (locked) return;
    finished.current = false;
    setDraft(keptDraft ?? value);
    setEditing(true);
  }

  function finish(save: boolean, returnFocus: boolean) {
    // Enter or Esc already ended the edit; the blur that follows must not save again.
    if (finished.current) return;
    finished.current = true;
    refocus.current = returnFocus;
    setEditing(false);
    if (save && draft !== value) onCommit(draft);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
    if (event.key === "Enter" && !(type === "textarea" && event.shiftKey)) {
      event.preventDefault();
      finish(true, true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      finish(false, true);
    }
  }

  return (
    <div className={className}>
      {editing && type === "textarea" ? (
        <textarea
          ref={inputRef}
          aria-label={inputLabel}
          value={draft}
          rows={3}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => finish(true, false)}
          onKeyDown={onKeyDown}
          className={inputClassName}
        />
      ) : editing ? (
        <input
          ref={inputRef}
          type={type}
          aria-label={inputLabel}
          value={draft}
          min={min}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => finish(true, false)}
          onKeyDown={onKeyDown}
          className={inputClassName}
        />
      ) : (
        <div className="relative">
          {children}
          <button
            ref={buttonRef}
            type="button"
            aria-label={label}
            aria-disabled={locked || undefined}
            aria-describedby={error ? errorId : undefined}
            onClick={start}
            className="absolute inset-0 cursor-text rounded-sm outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-primary aria-disabled:cursor-default"
          />
        </div>
      )}
      {error ? (
        <p id={errorId} className="text-meta text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** The editing half of `InlineField`, for a parent that decides when editing starts and
 * ends (e.g. a list row opened with `e` or a double-click). Focuses itself on mount unless
 * `autoFocus` is false. Blur or
 * Enter calls `onCommit` with the text, Esc calls `onCancel`; `viaKey` is true for Enter and
 * Esc, so the parent can move focus back. A blur right after Enter or Esc is ignored. */
export function InlineInput({
  label,
  initial,
  describedBy,
  autoFocus = true,
  onCommit,
  onCancel,
  className,
}: {
  /** The input's accessible name. */
  label: string;
  /** The text the input starts with. */
  initial: string;
  describedBy?: string;
  autoFocus?: boolean;
  onCommit: (text: string, viaKey: boolean) => void;
  onCancel: (viaKey: boolean) => void;
  className?: string;
}) {
  const [draft, setDraft] = useState(initial);
  const finished = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
    // Only on mount: focus is the parent's once editing is under way.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      finished.current = true;
      onCommit(draft, true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      finished.current = true;
      onCancel(true);
    }
  }

  return (
    <input
      ref={inputRef}
      type="text"
      aria-label={label}
      aria-describedby={describedBy}
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onFocus={() => {
        finished.current = false;
      }}
      onBlur={() => {
        if (finished.current) return;
        finished.current = true;
        onCommit(draft, false);
      }}
      onKeyDown={onKeyDown}
      className={className}
    />
  );
}

type Field = "title" | "target_proposal_date";
const FIELD_NAMES: Record<Field, string> = {
  title: "Title",
  target_proposal_date: "Target proposal date",
};

/** The owner's workspace header: the title and target proposal date are click-to-edit.
 * Each save is optimistic and sends `If-Match` with the last `row_version` seen. A 422
 * rolls back and shows the API's reason under the field; a 412 rolls back and shows who
 * changed it with a Reload button (nothing is overwritten); 403, 404 and network errors roll
 * back with a short message. On success the server data is refreshed so the rest of the
 * workspace follows the new version. `meta` is the read-only part of the meta row. */
export function EditableWorkspaceHeader({
  opportunity,
  meta,
}: {
  opportunity: Opportunity;
  meta: ReactNode;
}) {
  const announce = useAnnounce();
  const router = useRouter();
  const [current, setCurrent] = useState(opportunity);
  const [seen, setSeen] = useState(opportunity);
  const [saving, setSaving] = useState<{ field: Field; value: string } | null>(null);
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({});
  const [stale, setStale] = useState<{ changedBy: string | null } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);
  if (seen !== opportunity) {
    // A refresh (e.g. after a collaborator change) brought newer server data: follow it, so
    // the next save sends the current version. Newer data also answers a 412: drop the
    // notice (and any message) so editing unlocks.
    setSeen(opportunity);
    if (opportunity.row_version > current.row_version) {
      setCurrent(opportunity);
      setStale(null);
      setErrors({});
      setMessage(null);
    }
  }
  const reloadRef = useRef<HTMLButtonElement>(null);
  const locked = saving !== null || stale !== null || reloading;

  useEffect(() => {
    if (stale) reloadRef.current?.focus();
  }, [stale]);

  const title = saving?.field === "title" ? saving.value : current.title;
  const targetDate =
    saving?.field === "target_proposal_date" ? saving.value : current.target_proposal_date;

  function rejectField(field: Field, reason: string) {
    setErrors({ [field]: reason });
    announce(`${FIELD_NAMES[field]} not saved. ${reason}`);
  }

  function fail(text: string) {
    setMessage(text);
    announce(text);
  }

  async function save(field: Field, raw: string) {
    if (locked) return;
    let shown: string;
    let body: { title: string } | { target_proposal_date: string };
    if (field === "title") {
      const trimmed = raw.trim();
      shown = trimmed || current.customer_name;
      if (shown === current.title) return; // unchanged: nothing is sent
      if (codePointLength(trimmed) > TITLE_MAX) {
        rejectField(field, TITLE_TOO_LONG);
        return;
      }
      body = { title: trimmed };
    } else {
      // A cleared date input has nothing to save.
      if (!raw || raw === current.target_proposal_date) return;
      shown = raw;
      body = { target_proposal_date: raw };
    }
    setErrors({});
    setMessage(null);
    setSaving({ field, value: shown });
    let result: Awaited<ReturnType<typeof updateOpportunity>>;
    try {
      result = await updateOpportunity({
        opportunityId: current.id,
        rowVersion: current.row_version,
        ...body,
      });
    } catch {
      result = { kind: "error" };
    }
    setSaving(null); // the optimistic value goes; `current` decides what shows
    switch (result.kind) {
      case "ok":
        // A refresh may already have brought a newer version: keep whichever is newer.
        setCurrent((previous) =>
          previous.row_version > result.opportunity.row_version ? previous : result.opportunity,
        );
        announce(`${FIELD_NAMES[field]} saved`);
        // Overview and Collaborators read the Opportunity too: give them the new version.
        router.refresh();
        return;
      case "stale":
        setStale({ changedBy: result.changedBy });
        announce(staleMessage(result.changedBy));
        return;
      case "invalid":
        rejectField(field, result.detail);
        return;
      case "forbidden":
        fail(NOT_OWNER);
        // Access changed: re-read `can_edit` so the editors go away.
        router.refresh();
        return;
      case "not-found":
        fail(NO_ACCESS_TO_OPPORTUNITY);
        router.refresh();
        return;
      default:
        fail(SAVE_FAILED);
    }
  }

  async function reload() {
    if (reloading) return;
    setReloading(true);
    let result: Awaited<ReturnType<typeof loadOpportunity>>;
    try {
      result = await loadOpportunity(current.id);
    } catch {
      result = { kind: "error" };
    }
    setReloading(false);
    if (result.kind === "ok") {
      setStale(null);
      setErrors({});
      setMessage(null);
      setCurrent(result.opportunity);
      announce("Reloaded the Opportunity");
      router.refresh();
    } else if (result.kind === "not-found") {
      setStale(null);
      fail(NO_ACCESS_TO_OPPORTUNITY);
    } else {
      // Keep the stale notice (and its Reload button); nothing was overwritten.
      announce(RELOAD_FAILED);
    }
  }

  return (
    <header
      className="flex shrink-0 flex-col gap-1.5 px-gutter pt-gutter pb-3"
      aria-busy={saving !== null || reloading}
    >
      <InlineField
        label="Edit title"
        inputLabel="Title"
        type="text"
        value={title}
        error={errors.title}
        locked={locked}
        onCommit={(next) => void save("title", next)}
        className="flex flex-col gap-0.5"
        inputClassName="h-9 w-full max-w-3xl rounded-md border border-input bg-transparent px-1.5 text-title outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        <h1 className="text-title">{title}</h1>
      </InlineField>
      <div className="flex flex-wrap items-start gap-x-3.5 gap-y-1 text-label text-muted-foreground">
        {meta}
        <span className="inline-flex items-start gap-1.5">
          <span className="inline-flex h-5 items-center gap-1.5">
            <CalendarIcon className="size-3 shrink-0" aria-hidden="true" />
            Proposal due
          </span>
          <InlineField
            label="Edit target proposal date"
            inputLabel="Target proposal date"
            type="date"
            value={targetDate}
            min={utcToday()}
            error={errors.target_proposal_date}
            locked={locked}
            onCommit={(next) => void save("target_proposal_date", next)}
            className="inline-flex flex-col"
            inputClassName="h-6 rounded-md border border-input bg-transparent px-1 text-numeric text-foreground outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <span className="inline-flex h-5 items-center px-0.5 text-numeric text-foreground">
              {formatDate(targetDate)}
            </span>
          </InlineField>
        </span>
      </div>
      {/* Screen readers hear these through the shell's single live region. */}
      {stale ? (
        <div className="flex max-w-md items-center justify-between gap-2 rounded-md border border-border p-2">
          <p className="text-meta">{staleMessage(stale.changedBy)}</p>
          <button
            type="button"
            ref={reloadRef}
            onClick={() => void reload()}
            aria-disabled={reloading || undefined}
            className={buttonClass}
          >
            Reload
          </button>
        </div>
      ) : null}
      {message ? <p className="text-meta text-destructive">{message}</p> : null}
    </header>
  );
}
