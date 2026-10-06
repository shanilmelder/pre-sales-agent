"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";

import {
  loadEntry,
  reactivateEntry,
  retireEntry,
  editEntry,
  type EntryResult,
} from "@/app/admin/catalogue/actions";
import { StatusPill } from "@/components/admin/catalogue-table";
import { InlineField } from "@/components/opportunities/inline-field";
import { useAnnounce } from "@/components/shell/live-region";
import {
  fieldError,
  kindLabel,
  REASON_MAX,
  staleMessage,
  type CatalogueEntry,
  type CatalogueVersion,
} from "@/lib/catalogue";

const SAVE_FAILED = "The change could not be saved. Try again.";
const NO_ACCESS = "You don't have access to change the catalogue.";
const GONE = "This catalogue entry no longer exists.";
const RELOAD_FAILED = "The entry could not be reloaded. Try again.";

type Notice =
  | { kind: "stale"; changedBy: string | null }
  | { kind: "error"; message: string };

type FieldFailure = { field: "name" | "definition"; text: string; error: string };

const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";

function formatWhen(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

/** The selected catalogue entry in the right pane. Name and definition are click-to-edit
 * (Enter or blur saves, Esc reverts) and each change saves a new version with `If-Match`;
 * the version history lists every version with who saved it. Retire asks for a reason;
 * Reactivate brings a retired entry back (the API refuses when an active entry took its
 * name). A 412 shows who changed the entry with a Reload button and overwrites nothing. */
export function CatalogueInspector({
  entry,
  onChange,
  focusRequest = 0,
}: {
  entry: CatalogueEntry;
  /** Called with the entry as stored after a save or a reload. */
  onChange: (entry: CatalogueEntry) => void;
  /** Bump to move keyboard focus to the inspector's heading (0: leave focus alone). */
  focusRequest?: number;
}) {
  const announce = useAnnounce();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [failure, setFailure] = useState<FieldFailure | null>(null);
  const [versions, setVersions] = useState<CatalogueVersion[] | null>(null);
  const [pending, startTransition] = useTransition();
  const [retiring, setRetiring] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const headingId = useId();
  const reasonId = useId();
  const stale = notice?.kind === "stale";
  const locked = pending || stale;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const reasonRef = useRef<HTMLInputElement>(null);
  const retireRef = useRef<HTMLButtonElement>(null);

  // The history of the entry shown; it is loaded again after every change.
  useEffect(() => {
    let live = true;
    loadEntry(entry.id)
      .then((result) => {
        if (live && result.kind === "ok") setVersions(result.versions);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [entry.id, entry.row_version]);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  useEffect(() => {
    if (stale) reloadRef.current?.focus();
  }, [stale]);

  useEffect(() => {
    if (retiring) reasonRef.current?.focus();
  }, [retiring]);

  function fail(next: Notice, spoken: string) {
    setNotice(next);
    announce(spoken);
  }

  /** Shows a failed write; true when it was a success. */
  function handle(result: EntryResult, field?: FieldFailure["field"], text?: string): boolean {
    switch (result.kind) {
      case "ok":
        return true;
      case "stale":
        fail({ kind: "stale", changedBy: result.changedBy }, staleMessage(result.changedBy));
        return false;
      case "duplicate":
      case "invalid":
        if (field) {
          setFailure({ field, text: text ?? "", error: result.detail });
          announce(result.detail);
        } else {
          setConflict(result.detail);
          announce(result.detail);
        }
        return false;
      case "forbidden":
        fail({ kind: "error", message: NO_ACCESS }, NO_ACCESS);
        return false;
      case "not-found":
        fail({ kind: "error", message: GONE }, GONE);
        return false;
      default:
        fail({ kind: "error", message: SAVE_FAILED }, SAVE_FAILED);
        return false;
    }
  }

  function save(field: "name" | "definition", value: string) {
    if (locked) return;
    const invalid = fieldError(field, value);
    if (invalid) {
      setFailure({ field, text: value, error: invalid });
      announce(invalid);
      return;
    }
    setNotice(null);
    setFailure(null);
    setConflict(null);
    startTransition(async () => {
      let result: EntryResult;
      try {
        result = await editEntry({
          entryId: entry.id,
          rowVersion: entry.row_version,
          [field]: value,
        });
      } catch {
        result = { kind: "error" };
      }
      if (handle(result, field, value) && result.kind === "ok") {
        onChange(result.entry);
        announce(`Saved ${field} of ${result.entry.name}, version ${result.entry.current_version}`);
      }
    });
  }

  function retire() {
    if (locked) return;
    const invalid = fieldError("reason", reason);
    if (invalid) {
      setReasonError(invalid);
      reasonRef.current?.focus();
      return;
    }
    setNotice(null);
    setConflict(null);
    setReasonError(null);
    startTransition(async () => {
      let result: EntryResult;
      try {
        result = await retireEntry({ entryId: entry.id, rowVersion: entry.row_version, reason });
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "invalid") {
        setReasonError(result.detail);
        announce(result.detail);
      } else if (handle(result) && result.kind === "ok") {
        setRetiring(false);
        setReason("");
        onChange(result.entry);
        announce(`Retired ${result.entry.name}`);
        // The Retire button is gone: keep focus in the inspector.
        headingRef.current?.focus();
      }
    });
  }

  function reactivate() {
    if (locked) return;
    setNotice(null);
    setConflict(null);
    startTransition(async () => {
      let result: EntryResult;
      try {
        result = await reactivateEntry({ entryId: entry.id, rowVersion: entry.row_version });
      } catch {
        result = { kind: "error" };
      }
      if (handle(result) && result.kind === "ok") {
        onChange(result.entry);
        announce(`Reactivated ${result.entry.name}`);
        headingRef.current?.focus();
      }
    });
  }

  function reload() {
    if (pending) return;
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof loadEntry>>;
      try {
        result = await loadEntry(entry.id);
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok" || result.kind === "not-found" || result.kind === "forbidden") {
        headingRef.current?.focus();
      }
      if (result.kind === "ok") {
        setNotice(null);
        setFailure(null);
        setVersions(result.versions);
        onChange(result.entry);
        announce(`Reloaded ${result.entry.name}`);
      } else if (result.kind === "not-found") {
        fail({ kind: "error", message: GONE }, GONE);
      } else if (result.kind === "forbidden") {
        fail({ kind: "error", message: NO_ACCESS }, NO_ACCESS);
      } else {
        // Keep the stale notice (and its Reload button); nothing was overwritten.
        announce(RELOAD_FAILED);
      }
    });
  }

  const shownVersions = versions ?? [];

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-section outline-none">
            {entry.name}
          </h3>
          <StatusPill entry={entry} />
        </div>
        <p className="text-meta text-muted-foreground">
          {kindLabel(entry.kind)} · <span className="text-numeric">{entry.code}</span> · version{" "}
          <span className="text-numeric">{entry.current_version}</span>
        </p>
        {entry.retired && entry.retired_reason ? (
          <p className="text-meta">Retired: {entry.retired_reason}</p>
        ) : null}
      </div>

      <div className="flex flex-col gap-3" aria-busy={pending}>
        <div className="flex flex-col gap-1">
          <span className="text-label text-muted-foreground">Name</span>
          <InlineField
            label="Edit name"
            inputLabel="Name"
            type="text"
            value={entry.name}
            draft={failure?.field === "name" ? failure.text : undefined}
            error={failure?.field === "name" ? failure.error : null}
            locked={locked}
            onCommit={(next) => save("name", next)}
            inputClassName="h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <p className="min-h-6 py-0.5 text-body">{entry.name}</p>
          </InlineField>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-label text-muted-foreground">Definition</span>
          <InlineField
            label="Edit definition"
            inputLabel="Definition"
            type="textarea"
            value={entry.definition}
            draft={failure?.field === "definition" ? failure.text : undefined}
            error={failure?.field === "definition" ? failure.error : null}
            locked={locked}
            onCommit={(next) => save("definition", next)}
            inputClassName="min-h-24 w-full resize-y rounded-md border border-input bg-transparent px-1.5 py-1 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <p className="min-h-6 whitespace-pre-wrap py-0.5 text-body">{entry.definition}</p>
          </InlineField>
        </div>
      </div>

      {notice?.kind === "stale" ? (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border p-2">
          <p className="text-meta">{staleMessage(notice.changedBy)}</p>
          <button
            type="button"
            ref={reloadRef}
            onClick={reload}
            aria-disabled={pending || undefined}
            className={buttonClass}
          >
            Reload
          </button>
        </div>
      ) : null}
      {notice?.kind === "error" ? <p className="text-meta text-destructive">{notice.message}</p> : null}
      {conflict ? <p className="text-meta text-destructive">{conflict}</p> : null}

      <div className="flex flex-col gap-2">
        {entry.retired ? (
          <div>
            <button
              type="button"
              onClick={reactivate}
              aria-disabled={locked || undefined}
              className={buttonClass}
            >
              Reactivate
            </button>
          </div>
        ) : retiring ? (
          <div className="flex flex-col gap-1">
            <label htmlFor={reasonId} className="text-label text-muted-foreground">
              Reason for retiring
            </label>
            <input
              id={reasonId}
              ref={reasonRef}
              type="text"
              value={reason}
              maxLength={REASON_MAX * 2}
              aria-invalid={reasonError ? true : undefined}
              aria-describedby={reasonError ? `${reasonId}-error` : undefined}
              onChange={(event) => setReason(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  retire();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  event.stopPropagation();
                  setRetiring(false);
                  setReasonError(null);
                  retireRef.current?.focus();
                }
              }}
              className="h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
            />
            {reasonError ? (
              <p id={`${reasonId}-error`} className="text-meta text-destructive">
                {reasonError}
              </p>
            ) : null}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={retire}
                aria-disabled={locked || undefined}
                className={buttonClass}
              >
                Confirm retire
              </button>
              <button
                type="button"
                onClick={() => {
                  setRetiring(false);
                  setReasonError(null);
                }}
                className={buttonClass}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div>
            <button
              type="button"
              ref={retireRef}
              onClick={() => setRetiring(true)}
              aria-disabled={locked || undefined}
              className={buttonClass}
            >
              Retire
            </button>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Version history</h4>
        {versions === null ? (
          <p className="text-meta text-muted-foreground">Loading…</p>
        ) : (
          <ol className="flex flex-col">
            {shownVersions.map((v) => (
              <li key={v.version} className="flex flex-col gap-0.5 border-b border-border py-1.5">
                <p className="text-label">
                  <span className="text-numeric">Version {v.version}</span>
                  {v.version === entry.current_version ? " (current)" : ""}
                </p>
                <p className="text-meta text-muted-foreground">
                  {v.changed_by_name} · {formatWhen(v.changed_at)}
                </p>
                <p className="text-meta">{v.name}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
