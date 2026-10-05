"use client";

import { CircleAlertIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import {
  approveAllClarificationQuestions,
  approveClarificationQuestion,
  editClarificationQuestion,
  loadGaps,
  startGapDetection,
  type ApproveAllQuestionsResult,
  type QuestionWriteResult,
  type StartGapDetectionResult,
} from "@/app/opportunities/actions";
import {
  GapInspector,
  QuestionPill,
  type QuestionField,
} from "@/components/opportunities/gap-inspector";
import { ImpactBar } from "@/components/opportunities/impact-bar";
import { isEditableTarget } from "@/components/shell/keyboard-shortcuts";
import { useAnnounce } from "@/components/shell/live-region";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import {
  approveAllLabel,
  approvedCount,
  APPROVED,
  categoryLabel,
  DETECTING,
  DETECTION_POLL_LIMIT_MS,
  DETECTION_POLL_MS,
  detectionFailure,
  gapCount,
  isDetecting,
  NO_GAPS,
  NONE_FOUND,
  questionTextProblem,
  questionTopicProblem,
  STILL_DETECTING,
  toApprove,
  type ClarificationQuestion,
  type Detection,
  type Gap,
  type GapList,
} from "@/lib/gaps";
import { convertedLabel } from "@/lib/estimates";
import { NO_ACCESS_TO_OPPORTUNITY, staleMessage } from "@/lib/opportunities";

export const RETRY = "Retry";
const RETRY_FAILED = "The retry failed. Try again.";
const RETRY_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can detect Gaps.";
export const RELOAD = "Reload";
const SAVE_FAILED = "The change could not be saved. Try again.";
const APPROVE_FAILED = "The question could not be approved. Try again.";
const APPROVE_ALL_FAILED = "The questions could not be approved. Try again.";
export const EDIT_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can edit and approve questions.";
export const GAP_NOT_OPEN =
  "This Gap is no longer open: it was converted or replaced by a newer Gap detection.";
const QUESTION_GONE = "This Clarification Question is no longer available.";
const RELOAD_FAILED = "The Gaps could not be reloaded. Try again.";
const FIELD_NAMES: Record<QuestionField, string> = { text: "Question", topic: "Topic" };

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

/** The Gaps as 32px card rows, in the order given (the API ranks the open ones high, medium,
 * low, and lists converted ones after them). Each row shows the impact label with its
 * 3-segment bar, the category in meta type, the title and the question's "Draft" or
 * "Approved" pill (none when the viewer may not see the question). A
 * converted Gap's row is greyed out and labelled "Converted to Condition" or "Converted to
 * Contingency" (Story 8.4) instead of the pill.
 *
 * The list is one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first row); j/k (with single-key shortcuts on) or the arrow keys move between rows, and
 * Enter, Space or a click opens the row. With `onEdit`, `e` (single-key shortcuts on) on a
 * row opens it with its question text being edited. The selected row is `aria-selected`. */
export function GapsList({
  items,
  selectedId = null,
  onOpen,
  onEdit,
}: {
  items: readonly Gap[];
  selectedId?: string | null;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (item: Gap, viaKeyboard: boolean) => void;
  /** `e` on a row; left out for those who may not edit questions. */
  onEdit?: (item: Gap) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && items.some((i) => i.id === id)) ??
    items[0]?.id;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (isEditableTarget(event.target)) return;
    if (onEdit && singleKeyShortcuts && event.key === "e") {
      const rowId =
        event.target instanceof Element
          ? event.target.closest("[data-gap-id]")?.getAttribute("data-gap-id")
          : null;
      const item = items.find((i) => i.id === rowId);
      if (item && item.status === "open" && item.question) {
        event.preventDefault();
        onEdit(item);
      }
      return;
    }
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      container.current?.querySelectorAll<HTMLButtonElement>("button[data-gap-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === event.target);
    const next =
      index === -1 ? 0 : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <div
      ref={container}
      role="grid"
      aria-label="Gaps"
      onKeyDown={onKeyDown}
      className="flex flex-col"
    >
      {items.map((item) => {
        const selected = item.id === selectedId;
        const converted = item.status === "converted";
        return (
          <div
            key={item.id}
            role="row"
            aria-selected={selected}
            data-converted={converted ? "" : undefined}
            className={`border-b border-border ${selected ? "bg-muted" : "hover:bg-muted/60"} ${
              converted ? "text-muted-foreground" : ""
            }`}
          >
            <div role="gridcell">
              <button
                type="button"
                data-gap-row=""
                data-gap-id={item.id}
                tabIndex={item.id === tabStopId ? 0 : -1}
                onFocus={() => setFocusedId(item.id)}
                // A keyboard-activated click has no pointer clicks (detail 0).
                onClick={(event) => onOpen?.(item, event.detail === 0)}
                className="flex min-h-row w-full items-center gap-3 rounded-sm px-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <span className={converted ? "opacity-60" : undefined}>
                  <ImpactBar impact={item.impact} />
                </span>
                <span className="w-40 shrink-0 truncate text-meta text-muted-foreground">
                  {categoryLabel(item.category)}
                </span>
                <span
                  className={`min-w-0 flex-1 truncate text-body ${converted ? "text-muted-foreground" : ""}`}
                >
                  {item.title}
                </span>
                {converted ? (
                  <span className="inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full border border-border px-2 text-label text-muted-foreground">
                    {convertedLabel(item.converted_to)}
                  </span>
                ) : item.question ? (
                  <QuestionPill status={item.question.status} />
                ) : null}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** The detection's state above the list: "Detecting Gaps" with a running dot while queued
 * or running ("Still detecting — reload to check." once polling has stopped); "Gap
 * detection failed: <reason>" with **Retry** (only for those who may start one) once
 * failed; nothing otherwise. */
export function DetectionStatus({
  detection,
  canStart = false,
  busy = false,
  message = null,
  stalled = false,
  onRetry,
}: {
  detection: Detection | null;
  canStart?: boolean;
  /** A Retry is in flight. */
  busy?: boolean;
  /** A Retry's failure sentence. */
  message?: string | null;
  /** Polling has stopped while still detecting. */
  stalled?: boolean;
  onRetry?: () => void;
}) {
  if (isDetecting(detection) && stalled) {
    return <p className="text-label text-muted-foreground">{STILL_DETECTING}</p>;
  }
  if (isDetecting(detection)) {
    return (
      <p className="flex items-center gap-2 text-label" data-status={detection?.status}>
        <span
          aria-hidden="true"
          data-testid="running-dot"
          className="size-1.5 shrink-0 animate-pulse rounded-full bg-agent motion-reduce:animate-none"
        />
        {DETECTING}
      </p>
    );
  }
  if (detection?.status !== "failed") return null;
  return (
    <div className="flex flex-col items-start gap-1">
      <p className="flex items-center gap-1.5 text-label text-blocker" data-status="failed">
        <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
        {detectionFailure(detection.error_code)}
      </p>
      {canStart ? (
        <button type="button" disabled={busy} onClick={() => onRetry?.()} className={actionClass}>
          {RETRY}
        </button>
      ) : null}
      {message ? <span className="text-meta text-destructive">{message}</span> : null}
    </div>
  );
}

function retryMessage(result: StartGapDetectionResult): string {
  switch (result.kind) {
    case "forbidden":
      return RETRY_NOT_ALLOWED;
    case "not-found":
      return NO_ACCESS_TO_OPPORTUNITY;
    default:
      return RETRY_FAILED;
  }
}

/** The Gaps tab's content: the ranked list in the main pane and the selected Gap's inspector
 * in the right pane (opened if closed). While a detection is queued or running the list is
 * re-read every 2 s: paused while the tab is hidden, and stopped after 15 minutes. A selected
 * Gap that a re-run superseded leaves the pane showing "Nothing selected." Retry only for
 * those who may start a detection.
 *
 * Story 4.5: for those who may edit questions (`can_edit_questions`), the inspector's question
 * topic and text are click-to-edit and a drafted question has **Approve**; the header has
 * **Approve all (N)** for the drafted questions of open Gaps. Each write sends `If-Match` with
 * the last `row_version` seen; a 412 shows who changed it with Reload (nothing is
 * overwritten), a 422 the reason under the field, and a 409 that the Gap is no longer open.
 * Everyone else (sales representatives see only approved questions) reads them as they are. */
export function GapsSection({
  opportunityId,
  initial,
}: {
  opportunityId: string;
  initial: GapList;
}) {
  const announce = useAnnounce();
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [list, setList] = useState<GapList>(initial);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);
  const [syncedFrom, setSyncedFrom] = useState(initial);
  const [stalled, setStalled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  /** Bumped after every poll, so the next one is scheduled. */
  const [pollTick, setPollTick] = useState(0);
  /** Bumped on every local change (a Retry or a question write); a poll that started before
   * one is dropped. */
  const mutation = useRef(0);
  const detectingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const detecting = isDetecting(list.detection);

  // Editing and approving questions (Story 4.5).
  const [busyIds, setBusyIds] = useState<ReadonlySet<string>>(new Set());
  const [stale, setStale] = useState<{ changedBy: string | null } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<{
    questionId: string;
    field: QuestionField;
    text: string;
    error: string;
  } | null>(null);
  const [approvingAll, setApprovingAll] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [editRequest, setEditRequest] = useState(0);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const noticeId = useId();
  const locked = stale !== null || approvingAll || reloading;
  const canEdit = list.can_edit_questions;

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setList(initial);
    setStalled(false);
  }

  useEffect(() => {
    if (stale) reloadRef.current?.focus();
  }, [stale]);

  const selected =
    selectedId === null ? null : (list.items.find((item) => item.id === selectedId) ?? null);

  // The pane's content unmounts on close: reopening it must not take focus again.
  const [paneWasOpen, setPaneWasOpen] = useState(rightPaneOpen);
  if (paneWasOpen !== rightPaneOpen) {
    setPaneWasOpen(rightPaneOpen);
    if (!rightPaneOpen) {
      setFocusRequest(0);
      setEditRequest(0);
    }
  }

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(`[data-gap-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function open(item: Gap, viaKeyboard: boolean) {
    setSelectedId(item.id);
    returnFocusTo.current = viaKeyboard ? item.id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    setEditRequest(0);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  /** `e` on a row: open it with its question text being edited. */
  function startEdit(item: Gap) {
    if (locked) return;
    setSelectedId(item.id);
    returnFocusTo.current = item.id;
    setFocusRequest(0);
    setNotice(null);
    setEditRequest((n) => n + 1);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!detecting) {
      detectingSince.current = null;
      return;
    }
    detectingSince.current ??= Date.now();
    if (!visible || Date.now() - detectingSince.current >= DETECTION_POLL_LIMIT_MS) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const startedAt = mutation.current;
      try {
        const result = await loadGaps(opportunityId);
        if (!cancelled && result.kind === "ok" && mutation.current === startedAt) {
          setList(result.list);
          if (!isDetecting(result.list.detection)) {
            announce(
              result.list.detection?.status === "failed"
                ? detectionFailure(result.list.detection.error_code)
                : gapCount(result.list.items.filter((g) => g.status === "open").length),
            );
          }
        }
      } catch {
        // A failed poll is retried on the next tick.
      }
      if (cancelled) return;
      const since = detectingSince.current;
      if (since !== null && Date.now() - since >= DETECTION_POLL_LIMIT_MS) setStalled(true);
      setPollTick((tick) => tick + 1);
    }, DETECTION_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [detecting, visible, opportunityId, pollTick, announce]);

  async function retry() {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    let result: StartGapDetectionResult;
    try {
      result = await startGapDetection(opportunityId);
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      const { detection } = result;
      mutation.current += 1;
      detectingSince.current = null;
      setStalled(false);
      setList((current) => ({ ...current, detection }));
      announce(DETECTING);
    } else if (result.kind === "conflict") {
      // One is already queued or running: show what is stored now.
      try {
        const loaded = await loadGaps(opportunityId);
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

  /** Show `question` on its Gap (unless a newer version is already shown, or `force`). */
  function replaceQuestion(gapId: string, question: ClarificationQuestion, force = false) {
    mutation.current += 1;
    setList((current) => ({
      ...current,
      items: current.items.map((item) =>
        item.id === gapId &&
        item.question &&
        (force || item.question.row_version <= question.row_version)
          ? { ...item, question }
          : item,
      ),
    }));
  }

  function say(sentence: string) {
    setNotice(sentence);
    announce(sentence);
  }

  /** Re-read the list (after access, the Gap or the question changed). */
  async function refresh(): Promise<boolean> {
    try {
      const loaded = await loadGaps(opportunityId);
      if (loaded.kind !== "ok") return false;
      mutation.current += 1;
      setList(loaded.list);
      return true;
    } catch {
      return false;
    }
  }

  /** Act on a failed edit or approval. `kept` keeps the user's text under its field. */
  function writeFailed(
    result: Exclude<QuestionWriteResult, { kind: "ok" }>,
    kept: { questionId: string; field: QuestionField; text: string } | null,
    fallback: string,
  ) {
    switch (result.kind) {
      case "stale":
        setStale({ changedBy: result.changedBy });
        if (kept) setFailure({ ...kept, error: staleMessage(result.changedBy) });
        announce(staleMessage(result.changedBy));
        return;
      case "invalid":
        if (kept) {
          setFailure({ ...kept, error: result.detail });
          announce(`${FIELD_NAMES[kept.field]} not saved. ${result.detail}`);
        } else {
          say(result.detail);
        }
        return;
      case "gap-not-open":
        say(GAP_NOT_OPEN);
        void refresh();
        return;
      case "forbidden":
        say(EDIT_NOT_ALLOWED);
        void refresh(); // `can_edit_questions` changed: the controls go away
        return;
      case "not-found":
        say(QUESTION_GONE);
        void refresh();
        return;
      default:
        if (kept) {
          setFailure({ ...kept, error: fallback });
          announce(fallback);
        } else {
          say(fallback);
        }
    }
  }

  async function save(item: Gap, field: QuestionField, raw: string) {
    const question = item.question;
    if (!question || locked || busyIds.has(question.id)) return;
    setFailure(null);
    const problem = field === "text" ? questionTextProblem(raw) : questionTopicProblem(raw);
    if (problem) {
      setFailure({ questionId: question.id, field, text: raw, error: problem });
      announce(`${FIELD_NAMES[field]} not saved. ${problem}`);
      return;
    }
    const value = raw.trim();
    if (value === question[field]) return; // unchanged: nothing is sent
    setNotice(null);
    markBusy(question.id, true);
    // Show the new value while it saves.
    replaceQuestion(item.id, { ...question, [field]: value }, true);
    let result: QuestionWriteResult;
    try {
      result = await editClarificationQuestion({
        opportunityId,
        questionId: question.id,
        rowVersion: question.row_version,
        [field]: value,
      });
    } catch {
      result = { kind: "error" };
    }
    markBusy(question.id, false);
    if (result.kind === "ok") {
      replaceQuestion(item.id, result.question, true);
      announce(`${FIELD_NAMES[field]} saved`);
      return;
    }
    // Roll the shown value back (unless something newer came in meanwhile).
    mutation.current += 1;
    setList((current) => ({
      ...current,
      items: current.items.map((i) =>
        i.id === item.id && i.question?.row_version === question.row_version
          ? { ...i, question }
          : i,
      ),
    }));
    writeFailed(result, { questionId: question.id, field, text: raw }, SAVE_FAILED);
  }

  async function approve(item: Gap) {
    const question = item.question;
    if (!question || locked || busyIds.has(question.id) || question.status === "approved") return;
    setNotice(null);
    markBusy(question.id, true);
    let result: QuestionWriteResult;
    try {
      result = await approveClarificationQuestion({
        opportunityId,
        questionId: question.id,
        rowVersion: question.row_version,
      });
    } catch {
      result = { kind: "error" };
    }
    markBusy(question.id, false);
    if (result.kind === "ok") {
      replaceQuestion(item.id, result.question);
      announce(`${APPROVED}: ${item.title}`);
      return;
    }
    writeFailed(result, null, APPROVE_FAILED);
  }

  async function approveAll() {
    if (locked || busyIds.size > 0) return;
    setNotice(null);
    setApprovingAll(true);
    let result: ApproveAllQuestionsResult;
    try {
      result = await approveAllClarificationQuestions(
        opportunityId,
        toApprove(list.items).map((g) => ({
          id: g.question!.id,
          row_version: g.question!.row_version,
        })),
      );
    } catch {
      result = { kind: "error" };
    }
    if (result.kind === "ok") {
      // The new row versions come from the server.
      const reloaded = await refresh();
      setApprovingAll(false);
      // Without the new versions the next write would be refused: offer Reload now.
      if (!reloaded) setStale({ changedBy: null });
      announce(approvedCount(result.count));
      return;
    }
    setApprovingAll(false);
    if (result.kind === "stale") {
      setStale({ changedBy: result.changedBy });
      announce(staleMessage(result.changedBy));
    } else if (result.kind === "forbidden") {
      say(EDIT_NOT_ALLOWED);
      void refresh();
    } else if (result.kind === "not-found") {
      say(NO_ACCESS_TO_OPPORTUNITY);
    } else {
      say(APPROVE_ALL_FAILED);
    }
  }

  /** After a 412: read the Gaps again. The field keeps the user's text to save again. */
  async function reload() {
    if (reloading) return;
    setReloading(true);
    const reloaded = await refresh();
    setReloading(false);
    if (reloaded) {
      setStale(null);
      setFailure((current) => current && { ...current, error: "" });
      setNotice(null);
      announce("Reloaded the Gaps");
    } else {
      // Keep the stale notice (and its Reload button); nothing was overwritten.
      announce(RELOAD_FAILED);
    }
  }

  const failed = list.detection?.status === "failed";
  const succeeded = list.detection?.status === "succeeded";
  const approvable = canEdit ? toApprove(list.items).length : 0;
  return (
    <div className="flex flex-col gap-4" aria-busy={approvingAll || reloading || undefined}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <DetectionStatus
          detection={list.detection}
          canStart={list.can_start_detection}
          busy={busy}
          message={message}
          stalled={stalled}
          onRetry={() => void retry()}
        />
        {approvable > 0 ? (
          <button
            type="button"
            disabled={locked || busyIds.size > 0}
            onClick={() => void approveAll()}
            className={`${actionClass} ml-auto`}
          >
            {approveAllLabel(approvable)}
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
        <GapsList
          items={list.items}
          selectedId={selected?.id ?? null}
          onOpen={open}
          onEdit={canEdit ? startEdit : undefined}
        />
      ) : succeeded ? (
        <p className="text-muted-foreground">{NONE_FOUND}</p>
      ) : !detecting && !failed ? (
        <p className="text-muted-foreground">{NO_GAPS}</p>
      ) : null}
      {selected ? (
        <RightPaneContent>
          <GapInspector
            key={selected.id}
            gap={selected}
            focusRequest={focusRequest}
            edit={
              canEdit && selected.question
                ? {
                    busy: busyIds.has(selected.question.id),
                    locked,
                    failure: failure?.questionId === selected.question.id ? failure : null,
                    editRequest,
                    onCommit: (field, value) => void save(selected, field, value),
                    onApprove: () => void approve(selected),
                  }
                : undefined
            }
          />
        </RightPaneContent>
      ) : null}
    </div>
  );
}
