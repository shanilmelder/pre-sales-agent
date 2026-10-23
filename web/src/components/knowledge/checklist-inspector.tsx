"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";

import {
  loadChecklist,
  loadChecklistVersion,
  openDraft,
  publishChecklist,
  retireChecklist,
  saveDraft,
  type ChecklistResult,
} from "@/app/knowledge/checklists/actions";
import { ChecklistItemEditor } from "@/components/knowledge/checklist-item-editor";
import { ChecklistReadOnly } from "@/components/knowledge/checklist-read-only";
import type { CatalogueOption } from "@/components/knowledge/checklists-tab";
import { DraftLabel } from "@/components/knowledge/checklists-table";
import { MandatoryLabel } from "@/components/knowledge/mandatory-label";
import { RetiredLabel } from "@/components/knowledge/sources-table";
import { InlineField } from "@/components/opportunities/inline-field";
import { ReasonInput } from "@/components/opportunities/reason-input";
import { useAnnounce } from "@/components/shell/live-region";
import {
  checklistStatus,
  DOMAINS,
  domainLabel,
  draftInput,
  fieldError,
  formatWhen,
  INDUSTRY_MAX,
  newItem,
  parseProducts,
  REASON_MAX,
  staleChangeMessage,
  type Checklist,
  type ChecklistDomain,
  type ChecklistVersion,
  type ChecklistVersionSummary,
  type DraftBody,
  type DraftItemInput,
} from "@/lib/checklists";

const SAVE_FAILED = "The change could not be saved. Try again.";
const NO_ACCESS = "Only engineering, PM or security reviewers and administrators can change Checklists.";
const GONE = "This Checklist no longer exists.";
const RETIRED = "This Checklist is retired and can't be changed.";
const DRAFT_EXISTS = "Someone already started a draft. Reload to see it.";
const NO_DRAFT = "This Checklist has no draft any more. Reload to see it.";

type Notice = { kind: "stale" } | { kind: "error"; message: string };

/** One write, made against the Checklist as last stored (`base`). `call` returns null when
 * there is nothing to send any more (e.g. the draft is gone or not publishable). */
type Op = {
  call: (base: Checklist) => (() => Promise<ChecklistResult>) | null;
  spoken: (next: Checklist) => string;
  done?: (next: Checklist) => void;
};

const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";
const inputClass =
  "h-7 w-full rounded-md border border-input bg-background px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary";

/** The selected Checklist in the right pane. Authors (engineering, PM and security reviewers
 * and administrators) edit its draft: the name, domain, scope (products, industry and
 * Integration Types) and the items, each saved on blur with the row version as `If-Match`;
 * Publish (disabled until the draft has a scope entry and complete items) and Retire with a
 * reason. A published Checklist is edited by starting a draft from it. Everyone else sees it
 * read-only, with no authoring controls. The version history lists each version with its
 * publisher and date, and selecting one shows it read-only. A 412 shows a notice with Reload
 * and overwrites nothing. */
export function ChecklistInspector({
  checklist,
  catalogue,
  mayAuthor,
  onChange,
  focusRequest = 0,
}: {
  checklist: Checklist;
  /** The active Integration Types and Work Packages. */
  catalogue: readonly CatalogueOption[];
  mayAuthor: boolean;
  /** Called with the Checklist as stored after a change or a reload. */
  onChange: (checklist: Checklist) => void;
  /** Bump to move keyboard focus to the inspector's heading (0: leave focus alone). */
  focusRequest?: number;
}) {
  const announce = useAnnounce();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [nameFailure, setNameFailure] = useState<{ text: string; error: string } | null>(null);
  const [versions, setVersions] = useState<ChecklistVersionSummary[] | "failed" | null>(null);
  const [shown, setShown] = useState<ChecklistVersion | "loading" | "failed" | null>(null);
  const [pending, startTransition] = useTransition();
  const [retiring, setRetiring] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [focusItem, setFocusItem] = useState<number | null>(null);
  const headingId = useId();
  const domainId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const itemsRef = useRef<HTMLOListElement>(null);
  // Writes asked for while one is in flight, replayed in order against the Checklist each
  // write returns (its new row version); a failed write discards them.
  const queued = useRef<Op[]>([]);
  const inFlight = useRef(false);
  const stale = notice?.kind === "stale";
  // While a write is in flight the draft stays editable (changes queue); a stale view locks
  // it. `locked` still guards the one-off actions (Edit, Retire, Reload).
  const locked = pending || stale;
  const checklistId = checklist.id;
  const currentVersion = checklist.current_version;
  const draft = checklist.draft;
  const editing = mayAuthor && !checklist.retired && draft !== null;

  // The version history; it changes only on Publish (Reload refreshes it too).
  useEffect(() => {
    let live = true;
    loadChecklist(checklistId)
      .then((result) => {
        if (live) setVersions(result.kind === "ok" ? result.versions : "failed");
      })
      .catch(() => {
        if (live) setVersions("failed");
      });
    return () => {
      live = false;
    };
  }, [checklistId, currentVersion]);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  useEffect(() => {
    if (stale) reloadRef.current?.focus();
  }, [stale]);

  useEffect(() => {
    if (retiring) reasonRef.current?.focus();
  }, [retiring]);

  // After adding an item, focus its text once it is saved and shown.
  useEffect(() => {
    if (focusItem === null) return;
    const items = itemsRef.current?.querySelectorAll<HTMLElement>("li[data-item-id]");
    const index = Math.min(focusItem, (items?.length ?? 1) - 1);
    const target = items?.[index]?.querySelector<HTMLTextAreaElement>("textarea");
    if (target) {
      target.focus();
      setFocusItem(null);
    }
  }, [focusItem, draft]);

  function fail(next: Notice, spoken: string) {
    setNotice(next);
    announce(spoken);
  }

  /** Shows a failed write; true when it was a success. */
  function handle(result: ChecklistResult): boolean {
    switch (result.kind) {
      case "ok":
        return true;
      case "stale":
        fail({ kind: "stale" }, staleChangeMessage());
        return false;
      case "forbidden":
        fail({ kind: "error", message: NO_ACCESS }, NO_ACCESS);
        return false;
      case "not-found":
        fail({ kind: "error", message: GONE }, GONE);
        return false;
      case "conflict": {
        const message =
          result.code === "checklist_draft_exists"
            ? DRAFT_EXISTS
            : result.code === "checklist_no_draft"
              ? NO_DRAFT
              : RETIRED;
        fail({ kind: "error", message }, message);
        return false;
      }
      case "invalid":
        fail({ kind: "error", message: result.detail }, result.detail);
        return false;
      default:
        fail({ kind: "error", message: SAVE_FAILED }, SAVE_FAILED);
        return false;
    }
  }

  /** Runs `op`, or queues it behind the write in flight. */
  function run(op: Op) {
    if (stale) return;
    if (inFlight.current) {
      queued.current.push(op);
      return;
    }
    inFlight.current = true;
    setNotice(null);
    startTransition(async () => {
      let base = checklist;
      let next: Op | undefined = op;
      try {
        while (next) {
          const call = next.call(base);
          if (call === null) {
            next = queued.current.shift();
            continue;
          }
          let result: ChecklistResult;
          try {
            result = await call();
          } catch {
            result = { kind: "error" };
          }
          if (!handle(result) || result.kind !== "ok") {
            queued.current = [];
            return;
          }
          base = result.checklist;
          onChange(base);
          next.done?.(base);
          announce(next.spoken(base));
          next = queued.current.shift();
        }
      } finally {
        inFlight.current = false;
      }
    });
  }

  function save(change: (current: DraftBody) => DraftBody, spoken: string, done?: () => void) {
    run({
      call: (base) => {
        if (base.draft === null) return null;
        const body = change(draftInput(base.draft));
        return () => saveDraft({ checklistId, rowVersion: base.row_version, draft: body });
      },
      spoken: () => spoken,
      done,
    });
  }

  /** Changes one item, by id, keeping whatever an earlier queued write changed. */
  function saveItem(itemId: string, change: Partial<DraftItemInput>, spoken: string) {
    save(
      (d) => ({ ...d, items: d.items.map((i) => (i.id === itemId ? { ...i, ...change } : i)) }),
      spoken,
    );
  }

  function saveName(value: string) {
    const invalid = fieldError("name", value);
    if (invalid) {
      setNameFailure({ text: value, error: invalid });
      announce(invalid);
      return;
    }
    setNameFailure(null);
    save((d) => ({ ...d, name: value }), "Saved the name");
  }

  function moveItem(itemId: string, delta: -1 | 1, number: number) {
    save(
      (d) => {
        const items = [...d.items];
        const from = items.findIndex((i) => i.id === itemId);
        const to = from + delta;
        if (from < 0 || to < 0 || to >= items.length) return d;
        const [moved] = items.splice(from, 1);
        if (moved) items.splice(to, 0, moved);
        return { ...d, items };
      },
      `Moved item ${number} to ${number + delta}`,
    );
  }

  function removeItem(itemId: string, number: number) {
    save(
      (d) => ({ ...d, items: d.items.filter((i) => i.id !== itemId) }),
      `Removed item ${number}`,
    );
  }

  function addItem() {
    save(
      (d) => ({ ...d, items: [...d.items, newItem()] }),
      "Added an item",
      () => setFocusItem(Number.MAX_SAFE_INTEGER),
    );
  }

  function toggleTag(tagId: string, on: boolean) {
    save(
      (d) => ({
        ...d,
        integration_type_ids: on
          ? [...new Set([...d.integration_type_ids, tagId])]
          : d.integration_type_ids.filter((t) => t !== tagId),
      }),
      "Saved the Integration Types",
    );
  }

  function edit() {
    run({
      call: (base) => () => openDraft({ checklistId, rowVersion: base.row_version }),
      spoken: (next) => `Started a draft of ${next.name}`,
    });
  }

  function publish() {
    // A queued Publish is checked against the draft as the writes before it leave it.
    if (!inFlight.current && !draft?.publishable) return;
    run({
      call: (base) =>
        base.draft?.publishable
          ? () => publishChecklist({ checklistId, rowVersion: base.row_version })
          : null,
      spoken: (next) => `Published version ${next.current_version} of ${next.name}`,
      done: () => headingRef.current?.focus(),
    });
  }

  function retire() {
    const invalid = fieldError("reason", reason);
    if (invalid) {
      setReasonError(invalid);
      reasonRef.current?.focus();
      return;
    }
    setReasonError(null);
    run({
      call: (base) => () => retireChecklist({ checklistId, rowVersion: base.row_version, reason }),
      spoken: (next) => `Retired ${next.name}`,
      done: () => {
        setRetiring(false);
        setReason("");
        headingRef.current?.focus();
      },
    });
  }

  function reload() {
    if (pending || inFlight.current) return;
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof loadChecklist>>;
      try {
        result = await loadChecklist(checklistId);
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok") {
        setNotice(null);
        setNameFailure(null);
        setVersions(result.versions);
        onChange(result.checklist);
        headingRef.current?.focus();
        announce(`Reloaded ${result.checklist.name}`);
      } else if (result.kind === "not-found") {
        fail({ kind: "error", message: GONE }, GONE);
      } else {
        // Keep the stale notice (and its Reload button); nothing was overwritten.
        announce("The Checklist could not be reloaded. Try again.");
      }
    });
  }

  async function showVersion(version: number) {
    setShown("loading");
    try {
      const result = await loadChecklistVersion(checklistId, version);
      setShown(result.kind === "ok" ? result.version : "failed");
    } catch {
      setShown("failed");
    }
  }

  const typeOptions = catalogue.filter((c) => c.kind === "integration_type");
  const scopeTags = draft
    ? [
        ...typeOptions.map((t) => ({ id: t.id, name: t.name, retired: false })),
        ...draft.integration_types
          .filter((t) => !typeOptions.some((o) => o.id === t.id))
          .map((t) => ({ id: t.id, name: t.name, retired: true })),
      ]
    : [];
  const chosen = new Set(draft?.integration_types.map((t) => t.id) ?? []);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-section outline-none">
          {checklist.name}
        </h3>
        <div className="flex flex-wrap items-center gap-2 text-meta">
          <span>{domainLabel(checklist.domain)}</span>
          {checklist.retired ? <RetiredLabel /> : <span>{checklistStatus(checklist)}</span>}
          {draft && checklist.current_version !== null ? <DraftLabel /> : null}
          {checklist.mandatory_count > 0 ? (
            <MandatoryLabel count={checklist.mandatory_count} />
          ) : null}
        </div>
        {checklist.retired && checklist.retired_reason ? (
          <p className="text-meta">Retired: {checklist.retired_reason}</p>
        ) : null}
      </div>

      {notice?.kind === "stale" ? (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border p-2">
          <p className="text-meta">{staleChangeMessage()}</p>
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

      {editing && draft ? (
        <div className="flex flex-col gap-3" aria-busy={pending}>
          <h4 className="text-label text-muted-foreground">
            {checklist.current_version === null
              ? "Draft (not published yet)"
              : `Draft of version ${checklist.current_version + 1}: version ${checklist.current_version} stays in use until you publish`}
          </h4>
          <div className="flex flex-col gap-1">
            <span className="text-label text-muted-foreground">Name</span>
            <InlineField
              label="Edit name"
              inputLabel="Name"
              type="text"
              value={draft.name}
              draft={nameFailure?.text}
              error={nameFailure?.error ?? null}
              locked={stale}
              onCommit={saveName}
              inputClassName={inputClass}
            >
              <p className="min-h-6 py-0.5 text-body">{draft.name}</p>
            </InlineField>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={domainId} className="text-label text-muted-foreground">
              Domain
            </label>
            <select
              id={domainId}
              value={draft.domain}
              disabled={stale}
              onChange={(event) =>
                save(
                  (d) => ({ ...d, domain: event.target.value as ChecklistDomain }),
                  "Saved the domain",
                )
              }
              className={inputClass}
            >
              {DOMAINS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-label text-muted-foreground">Products (comma-separated)</span>
            <InlineField
              label="Edit products"
              inputLabel="Products"
              type="text"
              value={draft.products.join(", ")}
              locked={stale}
              onCommit={(next) =>
                save((d) => ({ ...d, products: parseProducts(next) }), "Saved the products")
              }
              inputClassName={inputClass}
            >
              <p className="min-h-6 py-0.5 text-body">
                {draft.products.length > 0 ? draft.products.join(", ") : "None"}
              </p>
            </InlineField>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-label text-muted-foreground">Industry</span>
            <InlineField
              label="Edit industry"
              inputLabel="Industry"
              type="text"
              value={draft.industry ?? ""}
              locked={stale}
              onCommit={(next) =>
                save(
                  (d) => ({ ...d, industry: next.trim() ? next.slice(0, INDUSTRY_MAX * 2) : null }),
                  "Saved the industry",
                )
              }
              inputClassName={inputClass}
            >
              <p className="min-h-6 py-0.5 text-body">{draft.industry ?? "None"}</p>
            </InlineField>
          </div>
          <fieldset className="flex flex-col gap-1" disabled={stale}>
            <legend className="text-label text-muted-foreground">Integration Types (scope)</legend>
            <ul className="flex max-h-40 flex-col overflow-y-auto">
              {scopeTags.map((option) => (
                <li key={option.id}>
                  <label className="flex min-h-row items-center gap-2 text-body">
                    <input
                      type="checkbox"
                      checked={chosen.has(option.id)}
                      onChange={(event) => toggleTag(option.id, event.target.checked)}
                    />
                    {option.name}
                    {option.retired ? <RetiredLabel /> : null}
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>

          <div className="flex flex-col gap-2">
            <h4 className="text-label text-muted-foreground">Items</h4>
            {draft.items.length === 0 ? (
              <p className="text-meta text-muted-foreground">No items yet.</p>
            ) : (
              <ol ref={itemsRef} className="flex flex-col gap-2">
                {draft.items.map((item, index) => (
                  <ChecklistItemEditor
                    key={item.id}
                    item={item}
                    index={index}
                    count={draft.items.length}
                    catalogue={catalogue}
                    locked={stale}
                    onCommit={(change) => saveItem(item.id, change, `Saved item ${index + 1}`)}
                    onMove={(delta) => moveItem(item.id, delta, index + 1)}
                    onRemove={() => removeItem(item.id, index + 1)}
                  />
                ))}
              </ol>
            )}
            <div>
              <button
                type="button"
                onClick={addItem}
                aria-disabled={stale || undefined}
                className={buttonClass}
              >
                Add item
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <div>
              <button
                type="button"
                onClick={publish}
                aria-disabled={stale || (!pending && !draft.publishable) || undefined}
                aria-describedby={draft.publish_problem ? `${headingId}-publish` : undefined}
                className={buttonClass}
              >
                Publish
              </button>
            </div>
            {draft.publish_problem ? (
              <p id={`${headingId}-publish`} className="text-meta text-muted-foreground">
                {draft.publish_problem}
              </p>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {checklist.current_version === null ? (
            <p className="text-meta text-muted-foreground">
              This Checklist hasn&apos;t been published yet.
            </p>
          ) : (
            <ChecklistReadOnly checklist={checklist} />
          )}
          {mayAuthor && !checklist.retired && draft === null ? (
            <div>
              <button
                type="button"
                onClick={edit}
                aria-disabled={locked || undefined}
                className={buttonClass}
              >
                Edit
              </button>
            </div>
          ) : null}
        </div>
      )}

      {mayAuthor && !checklist.retired ? (
        retiring ? (
          <div className="flex flex-col gap-1">
            <ReasonInput
              label="Reason for retiring"
              value={reason}
              onChange={setReason}
              error={reasonError}
              disabled={pending}
              inputRef={reasonRef}
              max={REASON_MAX}
            />
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
            <button type="button" onClick={() => setRetiring(true)} className={buttonClass}>
              Retire
            </button>
          </div>
        )
      ) : null}

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Version history</h4>
        {versions === null ? (
          <p className="text-meta text-muted-foreground">Loading…</p>
        ) : versions === "failed" ? (
          <p className="text-meta text-destructive">The version history could not be loaded.</p>
        ) : versions.length === 0 ? (
          <p className="text-meta text-muted-foreground">No published versions yet.</p>
        ) : (
          <ol className="flex flex-col">
            {versions.map((v) => (
              <li
                key={v.version}
                className="flex flex-wrap items-center justify-between gap-2 border-b border-border py-1.5"
              >
                <span className="flex flex-col gap-0.5">
                  <span className="text-label">
                    <span className="text-numeric">Version {v.version}</span>
                    {v.version === checklist.current_version ? " (current)" : ""}
                  </span>
                  <span className="text-meta text-muted-foreground">
                    {v.published_by.name} · {formatWhen(v.published_at)} · {v.item_count} items
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => void showVersion(v.version)}
                  aria-label={`View version ${v.version}`}
                  className={buttonClass}
                >
                  View
                </button>
              </li>
            ))}
          </ol>
        )}
      </div>

      {shown === "loading" ? (
        <p className="text-meta text-muted-foreground">Loading version…</p>
      ) : shown === "failed" ? (
        <p className="text-meta text-destructive">The version could not be loaded.</p>
      ) : shown ? (
        <section
          aria-label={`Version ${shown.version} (read-only)`}
          className="flex flex-col gap-1 rounded-md border border-border p-2"
        >
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-label">
              Version {shown.version} (read-only): {shown.name}
            </h4>
            <button type="button" onClick={() => setShown(null)} className={buttonClass}>
              Close
            </button>
          </div>
          <p className="text-meta text-muted-foreground">
            {domainLabel(shown.domain)} · {shown.published_by.name} ·{" "}
            {formatWhen(shown.published_at)}
          </p>
          <ChecklistReadOnly checklist={shown} />
        </section>
      ) : null}
    </section>
  );
}
