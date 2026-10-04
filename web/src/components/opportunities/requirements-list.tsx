"use client";

import { CheckIcon, CircleAlertIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import {
  confirmAllRequirements,
  confirmRequirement,
  editRequirement,
  loadRequirements,
  startExtraction,
  type ConfirmAllResult,
  type RequirementWriteResult,
  type StartExtractionResult,
} from "@/app/opportunities/actions";
import { InlineInput } from "@/components/opportunities/inline-field";
import {
  EvidenceChip,
  RequirementInspector,
} from "@/components/opportunities/requirement-inspector";
import { isEditableTarget } from "@/components/shell/keyboard-shortcuts";
import { useAnnounce } from "@/components/shell/live-region";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import { NO_ACCESS_TO_OPPORTUNITY, staleMessage } from "@/lib/opportunities";
import {
  CONFIRMED,
  confirmAllLabel,
  EXTRACTING,
  EXTRACTION_POLL_LIMIT_MS,
  EXTRACTION_POLL_MS,
  extractionFailure,
  groupRequirements,
  isExtracting,
  NO_REQUIREMENTS,
  noneFound,
  originLabel,
  requirementCount,
  requirementTextProblem,
  STILL_EXTRACTING,
  TOO_MUCH_TEXT,
  unconfirmed,
  type Classification,
  type Extraction,
  type Requirement,
  type RequirementList,
} from "@/lib/requirements";

export const RETRY = "Retry";
const RETRY_FAILED = "The retry failed. Try again.";
const RETRY_NOT_ALLOWED = "Only the owner and collaborators can extract Requirements.";
export const CONFIRM = "Confirm";
export const RELOAD = "Reload";
const SAVE_FAILED = "The change could not be saved. Try again.";
const CONFIRM_FAILED = "The Requirements could not be confirmed. Try again.";
export const EDIT_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can edit Requirements.";
const REQUIREMENT_GONE = "This Requirement is no longer available.";
const RELOAD_FAILED = "The Requirements could not be reloaded. Try again.";

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

/** Where a text save was committed: the list row's inline editor or the inspector. */
type SaveSource = "list" | "inspector";

/** What the list needs to edit and confirm Requirements in place (Story 2.6). */
export type RequirementEditing = {
  /** The row being edited inline, the text its input starts with, and whether the input
   * takes focus when it opens. */
  editing: { id: string; initial: string; autoFocus: boolean; seq: number } | null;
  /** Rows with a save or confirmation in flight. */
  busyIds: ReadonlySet<string>;
  /** True while nothing may be changed (a stale view, or a reload or Confirm all in flight). */
  locked: boolean;
  /** The id of a sentence describing the inline input (an error under the list). */
  describedBy?: string;
  onStartEdit: (item: Requirement) => void;
  onCommitText: (item: Requirement, text: string, viaKey: boolean) => void;
  onCancelEdit: (item: Requirement, viaKey: boolean) => void;
  onConfirm: (item: Requirement) => void;
};

/** "Confirmed" with a check icon. */
export function ConfirmedLabel() {
  return (
    <span className="inline-flex items-center gap-1 text-meta text-foreground">
      <CheckIcon aria-hidden="true" className="size-3 shrink-0 text-resolved" />
      {CONFIRMED}
    </span>
  );
}

/** The Requirements grouped by classification (Functional, Integration, Data, Security,
 * Non-functional, Commercial), each group headed by its label and count; empty groups are
 * hidden. Each row shows the text, its Evidence chips, "Edited" once a person changed it and
 * "Confirmed" once confirmed.
 *
 * The list is one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first row); j/k (with single-key shortcuts on) or the arrow keys move between rows across
 * the groups, and Enter, Space or a click opens the row. A chip opens its row with that
 * chip's passage shown. The selected row is `aria-selected`.
 *
 * With `edit`, `e` (with single-key shortcuts on) or a double-click on the text edits the
 * row inline (blur or Enter saves, Esc reverts), and each unconfirmed row has **Confirm**. */
export function RequirementsList({
  items,
  selectedId = null,
  onOpen,
  edit,
}: {
  items: readonly Requirement[];
  selectedId?: string | null;
  /** `passageId` is the chip clicked (null: the row itself); `viaKeyboard` is true when
   * opened with Enter or Space, not a pointer. */
  onOpen?: (item: Requirement, passageId: string | null, viaKeyboard: boolean) => void;
  /** Left out for those who may not edit: no inline edit and no Confirm. */
  edit?: RequirementEditing;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const groups = groupRequirements(items);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && items.some((i) => i.id === id)) ??
    groups[0]?.items[0]?.id;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    // Keys typed into the inline editor are text, not list navigation.
    if (isEditableTarget(event.target)) return;
    if (edit && singleKeyShortcuts && event.key === "e") {
      const rowId =
        event.target instanceof Element
          ? event.target.closest('[role="row"]')?.getAttribute("data-row-id")
          : null;
      const item = items.find((i) => i.id === rowId);
      if (item && !edit.locked && !edit.busyIds.has(item.id)) {
        event.preventDefault();
        edit.onStartEdit(item);
      }
      return;
    }
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      container.current?.querySelectorAll<HTMLButtonElement>("button[data-requirement-row]") ??
        [],
    );
    // From a chip, move from its row.
    const current =
      event.target instanceof Element
        ? event.target.closest('[role="row"]')?.querySelector("button[data-requirement-row]")
        : null;
    const index = buttons.findIndex((button) => button === current);
    const next =
      index === -1 ? 0 : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <div ref={container} onKeyDown={onKeyDown} className="flex flex-col gap-6">
      {groups.map((group) => {
        const headingId = `requirements-${group.classification}`;
        return (
          <section key={group.classification} aria-labelledby={headingId}>
            <h3 id={headingId} className="mb-1 flex items-baseline gap-2 text-section">
              {group.label}{" "}
              <span className="text-meta text-numeric text-muted-foreground">
                {group.items.length}
              </span>
            </h3>
            <div role="grid" aria-labelledby={headingId} className="flex flex-col">
              {group.items.map((item) => {
                const selected = item.id === selectedId;
                const editing = edit?.editing?.id === item.id ? edit.editing : null;
                const busy = edit?.busyIds.has(item.id) ?? false;
                return (
                  <div
                    key={item.id}
                    role="row"
                    data-row-id={item.id}
                    aria-selected={selected}
                    aria-busy={busy || undefined}
                    className={`border-b border-border ${selected ? "bg-muted" : "hover:bg-muted/60"}`}
                  >
                    <div role="gridcell" className="flex min-h-row flex-col gap-1 px-1 py-1.5">
                      {editing && edit ? (
                        <InlineInput
                          // A fresh input (and draft) each time editing reopens.
                          key={editing.seq}
                          label="Requirement text"
                          initial={editing.initial}
                          autoFocus={editing.autoFocus}
                          describedBy={edit.describedBy}
                          onCommit={(text, viaKey) => edit.onCommitText(item, text, viaKey)}
                          onCancel={(viaKey) => edit.onCancelEdit(item, viaKey)}
                          className="h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
                        />
                      ) : (
                        <button
                          type="button"
                          data-requirement-row=""
                          data-requirement-id={item.id}
                          tabIndex={item.id === tabStopId ? 0 : -1}
                          onFocus={() => setFocusedId(item.id)}
                          // A keyboard-activated click has no pointer clicks (detail 0).
                          onClick={(event) => onOpen?.(item, null, event.detail === 0)}
                          onDoubleClick={() => {
                            if (edit && !edit.locked && !busy) edit.onStartEdit(item);
                          }}
                          className="w-full rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-primary"
                        >
                          {item.text}
                        </button>
                      )}
                      <span className="flex flex-wrap items-center gap-1.5">
                        {item.evidence.length > 0 ? (
                          <>
                            <span className="sr-only">Evidence:</span>
                            {item.evidence.map((evidence) => (
                              <EvidenceChip
                                key={evidence.passage_id}
                                evidence={evidence}
                                tabIndex={-1}
                                onSelect={(viaKeyboard) =>
                                  onOpen?.(item, evidence.passage_id, viaKeyboard)
                                }
                              />
                            ))}
                          </>
                        ) : null}
                        {item.origin === "human" ? (
                          <span className="text-meta text-muted-foreground">
                            {originLabel(item.origin)}
                          </span>
                        ) : null}
                        {item.confirmed_at ? (
                          <ConfirmedLabel />
                        ) : edit ? (
                          <button
                            type="button"
                            tabIndex={-1}
                            disabled={edit.locked || busy}
                            aria-label={`${CONFIRM}: ${item.text}`}
                            onClick={() => edit.onConfirm(item)}
                            className={actionClass}
                          >
                            {CONFIRM}
                          </button>
                        ) : null}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

/** The extraction's state above the list: "Extracting Requirements" with a running dot while
 * queued or running ("Still extracting — reload to check." once polling has stopped);
 * "Extraction failed: <reason>" with **Retry** (only for those who may start one; never for
 * too much text, which a retry can't fix) once failed; nothing otherwise. */
export function ExtractionStatus({
  extraction,
  canStart = false,
  busy = false,
  message = null,
  stalled = false,
  onRetry,
}: {
  extraction: Extraction | null;
  canStart?: boolean;
  /** Polling has stopped while still extracting. */
  stalled?: boolean;
  /** A Retry is in flight. */
  busy?: boolean;
  /** A Retry's failure sentence. */
  message?: string | null;
  onRetry?: () => void;
}) {
  if (isExtracting(extraction) && stalled) {
    return <p className="text-label text-muted-foreground">{STILL_EXTRACTING}</p>;
  }
  if (isExtracting(extraction)) {
    return (
      <p className="flex items-center gap-2 text-label" data-status={extraction?.status}>
        <span
          aria-hidden="true"
          data-testid="running-dot"
          className="size-1.5 shrink-0 animate-pulse rounded-full bg-agent motion-reduce:animate-none"
        />
        {EXTRACTING}
      </p>
    );
  }
  if (extraction?.status !== "failed") return null;
  return (
    <div className="flex flex-col items-start gap-1">
      <p className="flex items-center gap-1.5 text-label text-blocker" data-status="failed">
        <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
        {extractionFailure(extraction.error_code)}
      </p>
      {extraction.error_code === "input_too_large" ? (
        <span className="text-meta text-muted-foreground">{TOO_MUCH_TEXT}</span>
      ) : canStart ? (
        <button type="button" disabled={busy} onClick={() => onRetry?.()} className={actionClass}>
          {RETRY}
        </button>
      ) : null}
      {message ? <span className="text-meta text-destructive">{message}</span> : null}
    </div>
  );
}

function retryMessage(result: StartExtractionResult): string {
  switch (result.kind) {
    case "forbidden":
      return RETRY_NOT_ALLOWED;
    case "not-found":
      return NO_ACCESS_TO_OPPORTUNITY;
    default:
      return RETRY_FAILED;
  }
}

/** The Requirements tab's content: the list in the main pane and the selected Requirement's
 * Evidence inspector in the right pane (opened if closed). While an extraction is queued or
 * running the list is re-read every 2 s: paused while the tab is hidden, and stopped after
 * 15 minutes. A selected Requirement that a re-run superseded leaves the pane showing
 * "Nothing selected." */
export function RequirementsSection({
  opportunityId,
  initial,
}: {
  opportunityId: string;
  initial: RequirementList;
}) {
  const announce = useAnnounce();
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [list, setList] = useState<RequirementList>(initial);
  const [selection, setSelection] = useState<{ id: string; passageId: string | null } | null>(
    null,
  );
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);
  const [syncedFrom, setSyncedFrom] = useState(initial);
  /** Polling stopped at its limit while still extracting. */
  const [stalled, setStalled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  /** Bumped after every poll, so the next one is scheduled. */
  const [pollTick, setPollTick] = useState(0);
  /** Bumped on every local change (a Retry); a poll that started before one is dropped. */
  const mutation = useRef(0);
  const extractingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const extracting = isExtracting(list.extraction);

  // Editing and confirming (Story 2.6).
  const [editing, setEditing] = useState<RequirementEditing["editing"]>(null);
  /** Numbers each opening of the inline editor, so every reopen is a fresh input. */
  const editSeq = useRef(0);
  /** A text save from the inspector that failed: its sentence and the user's text. */
  const [inspectorFailure, setInspectorFailure] = useState<{
    id: string;
    text: string;
    error: string;
  } | null>(null);
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [stale, setStale] = useState<{ changedBy: string | null } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmingAll, setConfirmingAll] = useState(false);
  const [reloading, setReloading] = useState(false);
  /** A row to move focus back to after Enter or Esc in its inline editor. */
  const [refocus, setRefocus] = useState<{ id: string } | null>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const noticeId = useId();
  const locked = stale !== null || confirmingAll || reloading;
  const canEdit = list.can_edit_requirements;

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setList(initial);
    setStalled(false);
  }

  useEffect(() => {
    if (stale) reloadRef.current?.focus();
  }, [stale]);

  // After Enter or Esc in the inline editor, focus goes back to the row (shown again in the
  // same render that closed the editor).
  useEffect(() => {
    if (refocus === null) return;
    document.querySelector<HTMLElement>(`[data-requirement-id="${refocus.id}"]`)?.focus();
  }, [refocus]);

  const selected =
    selection === null ? null : (list.items.find((item) => item.id === selection.id) ?? null);

  // The pane's content unmounts on close: reopening it must not take focus again.
  const [paneWasOpen, setPaneWasOpen] = useState(rightPaneOpen);
  if (paneWasOpen !== rightPaneOpen) {
    setPaneWasOpen(rightPaneOpen);
    if (!rightPaneOpen) setFocusRequest(0);
  }

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(`[data-requirement-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function open(item: Requirement, passageId: string | null, viaKeyboard: boolean) {
    setSelection({ id: item.id, passageId });
    returnFocusTo.current = viaKeyboard ? item.id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!extracting) {
      extractingSince.current = null;
      return;
    }
    extractingSince.current ??= Date.now();
    if (!visible || Date.now() - extractingSince.current >= EXTRACTION_POLL_LIMIT_MS) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const startedAt = mutation.current;
      try {
        const result = await loadRequirements(opportunityId);
        if (!cancelled && result.kind === "ok" && mutation.current === startedAt) {
          setList(result.list);
          if (!isExtracting(result.list.extraction)) {
            announce(
              result.list.extraction?.status === "failed"
                ? extractionFailure(result.list.extraction.error_code)
                : requirementCount(result.list.items.length),
            );
          }
        }
      } catch {
        // A failed poll is retried on the next tick.
      }
      if (cancelled) return;
      const since = extractingSince.current;
      if (since !== null && Date.now() - since >= EXTRACTION_POLL_LIMIT_MS) setStalled(true);
      setPollTick((tick) => tick + 1);
    }, EXTRACTION_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [extracting, visible, opportunityId, pollTick, announce]);

  async function retry() {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    let result: StartExtractionResult;
    try {
      result = await startExtraction(opportunityId);
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      const { extraction } = result;
      mutation.current += 1;
      extractingSince.current = null;
      setStalled(false);
      setList((current) => ({ ...current, extraction }));
      announce(EXTRACTING);
    } else if (result.kind === "conflict") {
      // One is already queued or running: show what is stored now.
      try {
        const loaded = await loadRequirements(opportunityId);
        if (loaded.kind === "ok") {
          mutation.current += 1;
          setList(loaded.list);
        }
      } catch {
        // The tab stays as it is.
      }
    } else {
      const sentence = retryMessage(result);
      setMessage(sentence);
      announce(sentence);
    }
  }

  function markBusy(id: string, on: boolean) {
    setBusyIds((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function replace(requirement: Requirement) {
    mutation.current += 1;
    setList((current) => ({
      ...current,
      items: current.items.map((item) =>
        // A poll may already have brought a newer version: keep whichever is newer.
        item.id === requirement.id && item.row_version <= requirement.row_version
          ? requirement
          : item,
      ),
    }));
  }

  function say(sentence: string) {
    setNotice(sentence);
    announce(sentence);
  }

  /** Re-read the list (after access or the Requirement itself changed). */
  async function refresh(): Promise<boolean> {
    try {
      const loaded = await loadRequirements(opportunityId);
      if (loaded.kind !== "ok") return false;
      mutation.current += 1;
      setList(loaded.list);
      return true;
    } catch {
      return false;
    }
  }

  function openEditor(id: string, initial: string, autoFocus: boolean) {
    editSeq.current += 1;
    setEditing({ id, initial, autoFocus, seq: editSeq.current });
  }

  /** A text save from the inspector failed: the sentence goes under its field, which keeps
   * the user's text. */
  function inspectorFailed(item: Requirement, text: string, sentence: string) {
    setInspectorFailure({ id: item.id, text, error: sentence });
    announce(sentence);
  }

  /** Act on a failed edit or confirmation. `draft` keeps the user's text: in the list row's
   * editor (reopened), or in the inspector's field when the save came from there. */
  function writeFailed(
    item: Requirement,
    result: Exclude<RequirementWriteResult, { kind: "ok" }>,
    draft: string | null,
    from: SaveSource,
  ) {
    const keep = draft !== null && result.kind !== "not-found" && result.kind !== "forbidden";
    if (keep && from === "inspector") {
      if (result.kind === "stale") {
        setStale({ changedBy: result.changedBy });
        inspectorFailed(item, draft, staleMessage(result.changedBy));
      } else {
        inspectorFailed(item, draft, result.kind === "invalid" ? result.detail : SAVE_FAILED);
      }
      return;
    }
    if (keep) openEditor(item.id, draft, result.kind !== "stale");
    switch (result.kind) {
      case "stale":
        setStale({ changedBy: result.changedBy });
        announce(staleMessage(result.changedBy));
        return;
      case "invalid":
        say(result.detail);
        return;
      case "forbidden":
        say(EDIT_NOT_ALLOWED);
        void refresh(); // `can_edit_requirements` changed: the controls go away
        return;
      case "not-found":
        say(REQUIREMENT_GONE);
        void refresh();
        return;
      default:
        say(SAVE_FAILED);
    }
  }

  async function save(
    item: Requirement,
    changes: { text: string } | { classification: Classification },
    from: SaveSource = "list",
  ) {
    if (locked || busyIds.has(item.id)) return;
    let body: { text?: string; classification?: Classification };
    if ("text" in changes) {
      if (from === "inspector") setInspectorFailure(null);
      const problem = requirementTextProblem(changes.text);
      if (problem) {
        if (from === "inspector") {
          inspectorFailed(item, changes.text, problem);
        } else {
          openEditor(item.id, changes.text, true);
          say(problem);
        }
        return;
      }
      const text = changes.text.trim();
      if (text === item.text) return; // unchanged: nothing is sent
      body = { text };
    } else {
      if (changes.classification === item.classification) return;
      body = { classification: changes.classification };
    }
    setNotice(null);
    markBusy(item.id, true);
    // Show the new value while it saves.
    mutation.current += 1;
    setList((current) => ({
      ...current,
      items: current.items.map((i) => (i.id === item.id ? { ...i, ...body } : i)),
    }));
    let result: RequirementWriteResult;
    try {
      result = await editRequirement({
        opportunityId,
        requirementId: item.id,
        rowVersion: item.row_version,
        ...body,
      });
    } catch {
      result = { kind: "error" };
    }
    markBusy(item.id, false);
    if (result.kind === "ok") {
      replace(result.requirement);
      announce("Requirement saved");
      return;
    }
    // Roll the shown value back; a stale view keeps the user's text in the editor.
    mutation.current += 1;
    setList((current) => ({
      ...current,
      items: current.items.map((i) =>
        i.id === item.id && i.row_version === item.row_version
          ? { ...i, text: item.text, classification: item.classification }
          : i,
      ),
    }));
    writeFailed(item, result, "text" in changes ? changes.text : null, from);
  }

  async function confirm(item: Requirement) {
    if (locked || busyIds.has(item.id) || item.confirmed_at) return;
    setNotice(null);
    markBusy(item.id, true);
    let result: RequirementWriteResult;
    try {
      result = await confirmRequirement({
        opportunityId,
        requirementId: item.id,
        rowVersion: item.row_version,
      });
    } catch {
      result = { kind: "error" };
    }
    markBusy(item.id, false);
    if (result.kind === "ok") {
      replace(result.requirement);
      announce(`${CONFIRMED}: ${result.requirement.text}`);
      return;
    }
    writeFailed(item, result, null, "list");
  }

  async function confirmAll() {
    if (locked || busyIds.size > 0) return;
    setNotice(null);
    setConfirmingAll(true);
    let result: ConfirmAllResult;
    try {
      result = await confirmAllRequirements(opportunityId);
    } catch {
      result = { kind: "error" };
    }
    if (result.kind === "ok") {
      // The new row versions come from the server.
      const reloaded = await refresh();
      setConfirmingAll(false);
      if (!reloaded) say(RELOAD_FAILED);
      announce(`${requirementCount(result.count)} confirmed`);
      return;
    }
    setConfirmingAll(false);
    if (result.kind === "forbidden") {
      say(EDIT_NOT_ALLOWED);
      void refresh();
    } else if (result.kind === "not-found") {
      say(NO_ACCESS_TO_OPPORTUNITY);
    } else {
      say(CONFIRM_FAILED);
    }
  }

  /** After a 412: read the Requirements again. The inline editor keeps the user's text. */
  async function reload() {
    if (reloading) return;
    setReloading(true);
    const reloaded = await refresh();
    setReloading(false);
    if (reloaded) {
      setStale(null);
      // The inspector keeps the user's text to save again; the 412 sentence goes.
      setInspectorFailure((failure) => failure && { ...failure, error: "" });
      setNotice(null);
      announce("Reloaded the Requirements");
    } else {
      // Keep the stale notice (and its Reload button); nothing was overwritten.
      announce(RELOAD_FAILED);
    }
  }

  const edit: RequirementEditing | undefined = canEdit
    ? {
        editing,
        busyIds,
        locked,
        describedBy: notice || stale ? noticeId : undefined,
        onStartEdit: (item) => {
          setNotice(null);
          openEditor(item.id, item.text, true);
        },
        onCommitText: (item, text, viaKey) => {
          // While stale nothing is saved: the editor stays open with the user's text.
          if (locked) return;
          setEditing(null);
          if (viaKey) setRefocus({ id: item.id });
          void save(item, { text });
        },
        onCancelEdit: (item, viaKey) => {
          setEditing(null);
          if (viaKey) setRefocus({ id: item.id });
        },
        onConfirm: (item) => void confirm(item),
      }
    : undefined;
  const toConfirm = unconfirmed(list.items).length;

  const failed = list.extraction?.status === "failed";
  const succeeded = list.extraction?.status === "succeeded";
  return (
    <div className="flex flex-col gap-4" aria-busy={confirmingAll || reloading || undefined}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <ExtractionStatus
          extraction={list.extraction}
          canStart={list.can_start_extraction}
          busy={busy}
          message={message}
          stalled={stalled}
          onRetry={() => void retry()}
        />
        {canEdit && toConfirm > 0 ? (
          <button
            type="button"
            disabled={locked || busyIds.size > 0}
            onClick={() => void confirmAll()}
            className={`${actionClass} ml-auto`}
          >
            {confirmAllLabel(toConfirm)}
          </button>
        ) : null}
      </div>
      {/* Screen readers hear these through the shell's single live region. */}
      {stale ? (
        <div
          id={noticeId}
          className="flex max-w-md items-center justify-between gap-2 rounded-md border border-border p-2"
        >
          <p className="text-meta">{staleMessage(stale.changedBy)}</p>
          <button
            type="button"
            ref={reloadRef}
            onClick={() => void reload()}
            aria-disabled={reloading || undefined}
            className={actionClass}
          >
            {RELOAD}
          </button>
        </div>
      ) : notice ? (
        <p id={noticeId} className="text-meta text-destructive">
          {notice}
        </p>
      ) : null}
      {list.items.length > 0 ? (
        <RequirementsList
          items={list.items}
          selectedId={selected?.id ?? null}
          onOpen={open}
          edit={edit}
        />
      ) : succeeded ? (
        <p className="text-muted-foreground">{noneFound(list.extraction?.source_count)}</p>
      ) : !extracting && !failed ? (
        <p className="text-muted-foreground">{NO_REQUIREMENTS}</p>
      ) : null}
      {selected ? (
        <RightPaneContent>
          <RequirementInspector
            key={selected.id}
            opportunityId={opportunityId}
            requirement={selected}
            passageId={selection?.passageId ?? null}
            onSelectPassage={(passageId) =>
              setSelection((current) => (current ? { ...current, passageId } : current))
            }
            focusRequest={focusRequest}
            edit={
              canEdit
                ? {
                    busy: busyIds.has(selected.id),
                    locked,
                    failure:
                      inspectorFailure?.id === selected.id ? inspectorFailure : null,
                    onCommitText: (text) => void save(selected, { text }, "inspector"),
                    onClassify: (classification) => void save(selected, { classification }),
                    onConfirm: () => void confirm(selected),
                  }
                : undefined
            }
          />
        </RightPaneContent>
      ) : null}
    </div>
  );
}
