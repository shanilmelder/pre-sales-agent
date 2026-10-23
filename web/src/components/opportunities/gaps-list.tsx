"use client";

import { CheckIcon, CircleAlertIcon, LoaderCircleIcon } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import {
  approveAllClarificationQuestions,
  approveClarificationQuestion,
  approveSelectedClarificationQuestions,
  changeGapImpact,
  confirmAnswerMatch,
  dismissGap,
  editClarificationQuestion,
  loadGaps,
  markClarificationQuestionsSent,
  markClarificationQuestionUnanswered,
  recordAnswer,
  rejectAnswerMatch,
  reopenGap,
  startGapDetection,
  type AnswerWriteResult,
  type ApproveAllQuestionsResult,
  type GapWriteResult,
  type MarkSentResult,
  type QuestionWriteResult,
  type StartGapDetectionResult,
} from "@/app/opportunities/actions";
import {
  GapInspector,
  MarkSentForm,
  QuestionPill,
  TriggerPill,
  type GapFormOutcome,
  type QuestionField,
} from "@/components/opportunities/gap-inspector";
import { GapsFilters } from "@/components/opportunities/gaps-filters";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyTabCard } from "@/components/ui/empty-tab-card";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Pill } from "@/components/ui/pill";
import { ImpactBar } from "@/components/opportunities/impact-bar";
import { QuestionsExport } from "@/components/opportunities/questions-export";
import { isEditableTarget } from "@/components/shell/keyboard-shortcuts";
import { useAnnounce } from "@/components/shell/live-region";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import {
  answeredLabel,
  approveAllLabel,
  approvedCount,
  approveSelectedLabel,
  APPROVED,
  categoryLabel,
  CLARIFICATION_AGENT,
  CLEAR_FILTERS,
  dismissReasonLabel,
  DETECTING,
  DETECTION_POLL_LIMIT_MS,
  DETECTION_POLL_MS,
  detectionFailure,
  filterGaps,
  gapCount,
  gapsChangedAnnouncement,
  GAPS_FALLBACK_POLL_MS,
  gapsSummary,
  gapStatus,
  hasGapFilters,
  impactLabel,
  isDetecting,
  isSent,
  markAllSentLabel,
  markSelectedSentLabel,
  NO_ANSWER,
  NO_GAPS,
  NO_FILTER_MATCH,
  NO_GAP_FILTERS,
  NO_GAPS_BODY,
  OPEN_REQUIREMENTS,
  NONE_FOUND,
  possibleAnswerLabel,
  questionTextProblem,
  questionTopicProblem,
  rankGaps,
  sentCount,
  STILL_DETECTING,
  toApprove,
  toSend,
  type AnswerSuggestion,
  type ClarificationQuestion,
  type Detection,
  type DismissReasonKind,
  type Gap,
  type GapFilters,
  type GapList,
  type Impact,
} from "@/lib/gaps";
import { tabHref } from "@/lib/workspace";
import { convertedLabel } from "@/lib/estimates";
import { NO_ACCESS_TO_OPPORTUNITY, staleMessage } from "@/lib/opportunities";
import { useGapsEvents } from "@/lib/opportunity-events";

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
  "This Gap is no longer open: it was dismissed, converted or replaced by a newer Gap detection.";
export const GAP_NOT_DISMISSED =
  "This Gap is no longer dismissed or answered: someone reopened it.";
export const GAP_EDIT_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can change, dismiss and reopen Gaps.";
const GAP_GONE = "This Gap is no longer available.";
export const SAME_IMPACT = "Choose a different impact.";
const APPROVE_SELECTED_FAILED = "The selected questions could not be approved. Try again.";
const QUESTION_GONE = "This Clarification Question is no longer available.";
const RELOAD_FAILED = "The Gaps could not be reloaded. Try again.";
export const QUESTION_SENT =
  "This Clarification Question was sent: it can no longer be edited or approved.";
export const QUESTION_NOT_SENT = "This Clarification Question is no longer sent.";
export const SEND_NOT_ALLOWED =
  "Only the owner and collaborators can mark questions sent or “No answer”.";
const MARK_SENT_FAILED = "The questions could not be marked sent. Try again.";
const NO_ANSWER_FAILED = "The question could not be marked “No answer”. Try again.";
const ANSWER_FAILED = "The answer could not be recorded. Try again.";
const DECIDE_FAILED = "The suggested answer could not be decided. Try again.";
export const ANSWER_NOT_ALLOWED = "Only the owner and collaborators can record answers.";
export const SUGGESTION_GONE = "This suggested answer is no longer available.";
const FIELD_NAMES: Record<QuestionField, string> = { text: "Question", topic: "Topic" };

/** The table's columns: the checkbox (only with select rights), impact, the Gap, the
 * question. Below `md` the rows stack (the checkbox keeps its own column). */
const GRID_SELECTABLE =
  "grid-cols-[28px_minmax(0,1fr)] md:grid-cols-[28px_112px_minmax(0,1fr)_120px]";
const GRID_PLAIN = "grid-cols-1 md:grid-cols-[112px_minmax(0,1fr)_120px]";

/** The Gaps as a table card (Gaps tab redesign): a header row of meta labels on the alt
 * surface, then one grid row per Gap, in the order given (the API ranks the open ones high,
 * medium, low, then lists answered, converted and dismissed ones in the same order). Each row
 * shows the checkbox (with `onToggle`), the impact bar coloured by impact, the title with a meta
 * line "{category} · Clarification Agent" (and the answer or possible-answer hint), and the
 * question's pill (none when the viewer may not see the question). A converted Gap's row is
 * greyed out and labelled "Converted to Condition" or "Converted to Contingency" (Story 8.4)
 * instead of the pill; a dismissed Gap's row is greyed out with "Dismissed · {reason}" (Story
 * 4.4). The opened row has the primary tint; otherwise an open High-impact Gap has the blocker
 * tint and a 3px blocker bar on its left.
 *
 * The list is one Tab stop (roving tabindex: the last focused, else the opened, else the
 * first row); each row's open button has a stretched hit area, so a click anywhere opens it.
 * j/k (with single-key shortcuts on) or the arrow keys move between rows, and Enter, Space or a
 * click opens the row (`aria-current`). With `onEdit`, `e` (single-key shortcuts on) on a row
 * opens it with its question text being edited. With `onToggle` (Story 4.4), a checkbox column
 * appears and `x` (single-key shortcuts on) toggles the focused row's selection
 * (`aria-selected`); Esc clears the selection while the inspector is closed. With `empty`, it
 * shows in the card instead of rows when `items` is empty (a filter matched nothing). */
export function GapsList({
  items,
  selectedId = null,
  checkedIds,
  inspectorOpen = false,
  onOpen,
  onEdit,
  onToggle,
  onClearSelection,
  empty,
}: {
  items: readonly Gap[];
  /** The opened Gap. */
  selectedId?: string | null;
  /** The multi-selected Gaps (with `onToggle`). */
  checkedIds?: ReadonlySet<string>;
  /** Whether the inspector is open: Esc then closes it instead of clearing the selection. */
  inspectorOpen?: boolean;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (item: Gap, viaKeyboard: boolean) => void;
  /** `e` on a row; left out for those who may not edit questions. */
  onEdit?: (item: Gap) => void;
  /** `x` on a row or its checkbox; left out for those who may not approve questions. */
  onToggle?: (item: Gap) => void;
  onClearSelection?: () => void;
  /** Shown in the card when there are no rows. */
  empty?: ReactNode;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && items.some((i) => i.id === id)) ??
    items[0]?.id;
  const selectable = onToggle !== undefined;
  const grid = selectable ? GRID_SELECTABLE : GRID_PLAIN;
  // Below `md` the cells after the checkbox stack in its second column.
  const cell = selectable ? "col-start-2 md:col-start-auto" : "";

  function rowItem(target: EventTarget): Gap | undefined {
    const rowId =
      target instanceof Element
        ? target.closest("[data-gap-id]")?.getAttribute("data-gap-id")
        : null;
    return items.find((i) => i.id === rowId);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (isEditableTarget(event.target)) return;
    if (event.key === "Escape") {
      if (onClearSelection && !inspectorOpen && checkedIds && checkedIds.size > 0) {
        event.preventDefault();
        onClearSelection();
      }
      return;
    }
    if (onToggle && singleKeyShortcuts && event.key === "x") {
      const item = rowItem(event.target);
      if (item) {
        event.preventDefault();
        onToggle(item);
      }
      return;
    }
    if (onEdit && singleKeyShortcuts && event.key === "e") {
      const item = rowItem(event.target);
      if (item && item.status === "open" && item.question && !isSent(item.question.status)) {
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
    <Card className="overflow-hidden">
      <div
        aria-hidden="true"
        className={`hidden gap-3 border-b border-border bg-surface-alt px-4 py-2 text-label text-text-secondary md:grid ${grid}`}
      >
        {selectable ? <span /> : null}
        <span>Impact</span>
        <span>Gap · affected area · trigger</span>
        <span>Question</span>
      </div>
      {items.length === 0 && empty ? (
        empty
      ) : (
        <div
          ref={container}
          role="grid"
          aria-label="Gaps"
          aria-multiselectable={selectable || undefined}
          onKeyDown={onKeyDown}
          className="flex flex-col"
        >
          {items.map((item, index) => {
            const opened = item.id === selectedId;
            const checked = checkedIds?.has(item.id) ?? false;
            const converted = item.status === "converted";
            const dismissed = item.status === "dismissed";
            const greyed = converted || dismissed;
            const urgent = item.status === "open" && item.impact === "high";
            const state = opened
              ? "bg-primary-tint"
              : checked
                ? "bg-muted/40"
                : urgent
                ? "bg-blocker-tint shadow-[inset_3px_0_0_var(--color-blocker)]"
                : "hover:bg-muted/60";
            return (
              <div
                key={item.id}
                role="row"
                aria-selected={selectable ? checked : undefined}
                aria-current={opened || undefined}
                data-converted={converted ? "" : undefined}
                data-dismissed={dismissed ? "" : undefined}
                data-urgent={urgent && !opened && !checked ? "" : undefined}
                className={`relative grid items-start gap-x-3 gap-y-2 px-4 py-3 ${grid} ${
                  index > 0 ? "border-t border-border" : ""
                } ${state} ${greyed ? "text-muted-foreground" : ""}`}
              >
                {selectable ? (
                  <div
                    role="gridcell"
                    className="relative z-10 row-span-3 flex pt-0.5 md:row-span-1"
                  >
                    <span className="relative inline-flex size-[18px]">
                      <input
                        type="checkbox"
                        tabIndex={-1}
                        checked={checked}
                        onChange={() => onToggle?.(item)}
                        aria-label={`Select ${item.title}`}
                        className="peer size-[18px] cursor-pointer appearance-none rounded-[5px] border-[1.5px] border-border-strong bg-transparent outline-none checked:border-primary checked:bg-primary focus-visible:ring-2 focus-visible:ring-primary"
                      />
                      <CheckIcon
                        aria-hidden="true"
                        strokeWidth={3}
                        className="pointer-events-none absolute inset-0 m-auto size-3 text-primary-foreground opacity-0 peer-checked:opacity-100"
                      />
                    </span>
                  </div>
                ) : null}
                <div role="gridcell" className={`flex pt-px ${cell} ${greyed ? "opacity-60" : ""}`}>
                  <ImpactBar impact={item.impact} coloured />
                </div>
                <div role="gridcell" className={`min-w-0 ${cell}`}>
                  <button
                    type="button"
                    data-gap-row=""
                    data-gap-id={item.id}
                    tabIndex={item.id === tabStopId ? 0 : -1}
                    onFocus={() => setFocusedId(item.id)}
                    // A keyboard-activated click has no pointer clicks (detail 0).
                    onClick={(event) => onOpen?.(item, event.detail === 0)}
                    className={`text-left text-body-strong [overflow-wrap:anywhere] outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset ${
                      greyed ? "text-muted-foreground" : ""
                    }`}
                  >
                    <span className="sr-only">{gapStatus(item.status).label} </span>
                    {item.title}
                  </button>
                  <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-meta text-text-secondary">
                    <span>{categoryLabel(item.category)}</span>
                    <span aria-hidden="true">·</span>
                    <TriggerPill>{CLARIFICATION_AGENT}</TriggerPill>
                    {item.answer ? (
                      <span>{answeredLabel(item.answer.answered_on)}</span>
                    ) : item.answer_suggestions[0] ? (
                      <span>{possibleAnswerLabel(item.answer_suggestions[0])}</span>
                    ) : null}
                  </p>
                </div>
                <div role="gridcell" className={`flex min-w-0 ${cell}`}>
                  {/* The longer neutral labels wrap inside the 120px column. */}
                  {converted ? (
                    <Pill tone="neutral" className="min-w-0 whitespace-normal">
                      {convertedLabel(item.converted_to)}
                    </Pill>
                  ) : dismissed && item.dismissal ? (
                    <Pill tone="neutral" className="min-w-0 whitespace-normal">
                      {`Dismissed · ${dismissReasonLabel(item.dismissal.reason_kind)}`}
                    </Pill>
                  ) : item.question ? (
                    <QuestionPill status={item.question.status} />
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

/** The key hints under the card, as one meta line: "j / k move · x select · Enter open · e edit
 * question · ] inspector", leaving out what the viewer may not do. `canSelect` (default
 * `canEdit`): `x` selects rows (Story 4.6: those who may send questions select too). */
export function gapsKeyHints(canEdit: boolean, canSelect: boolean = canEdit): string {
  return [
    "j / k move",
    canSelect ? "x select" : null,
    "Enter open",
    canEdit ? "e edit question" : null,
    "] inspector",
  ]
    .filter(Boolean)
    .join(" · ");
}

export function GapsKeyHints({
  canEdit,
  canSelect = canEdit,
}: {
  canEdit: boolean;
  canSelect?: boolean;
}) {
  return <p className="text-meta text-text-secondary">{gapsKeyHints(canEdit, canSelect)}</p>;
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
        <LoaderCircleIcon aria-hidden="true" data-testid="running-dot" className="size-3 shrink-0 text-agent" />
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
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => onRetry?.()}>
          {RETRY}
        </Button>
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
 * Gap that a re-run superseded leaves the pane showing the empty Inspector text. Retry only for
 * those who may start a detection.
 *
 * Story 4.5: for those who may edit questions (`can_edit_questions`), the inspector's question
 * topic and text are click-to-edit and a drafted question has **Approve**; the header has
 * **Approve all (N)** for the drafted questions of open Gaps. Each write sends `If-Match` with
 * the last `row_version` seen; a 412 shows who changed it with Reload (nothing is
 * overwritten), a 422 the reason under the field, and a 409 that the Gap is no longer open.
 * Everyone else (sales representatives see only approved questions) reads them as they are.
 *
 * Story 4.4: the header reads "N Gaps · M open · ranked by impact". For those who may approve
 * questions, `x` selects rows and the header offers **Approve N selected** while the selection
 * holds drafted questions of open Gaps (else **Approve all (N)**). For those who may change
 * Gaps (`can_edit_gaps`), the inspector changes an open Gap's impact or dismisses it, and
 * reopens a dismissed one, each with a reason and `If-Match` (a 412 shows the stale notice
 * with Reload). The list keeps the API's order after a change.
 *
 * Story 4.6: for those who may send questions (`can_send_questions`, sales representatives
 * included), the header has an **Export** menu (Copy, Word, Email draft) while approved
 * questions of open Gaps exist, and **Mark N selected sent** while the selection holds approved
 * questions (else **Mark all sent (N)**); either opens a small form with the date sent (today by
 * default) and a confirm button. The inspector marks one approved question sent and a sent one
 * "No answer". A 412 shows the stale notice with Reload.
 *
 * Story 4.7: the inspector records a customer's answer to a sent question and confirms or
 * rejects suggested answers (same people as sending). The list re-reads on the event stream's
 * `gaps.changed` frames (detection polling stays while it runs) and announces "N Gaps answered,
 * M open" through the throttled live region when those counts change. */
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
  const canEditGaps = list.can_edit_gaps;
  const canSend = list.can_send_questions;
  const canSelect = canEdit || canSend;
  // Story 4.6: the questions the open "date sent" form will mark (null while it is closed).
  const [markSentFor, setMarkSentFor] = useState<Gap[] | null>(null);
  // Multi-select (Story 4.4): Gap ids; ids no longer listed drop out.
  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
  // Client-side filters (not persisted). A change drops checked rows it hides.
  const [filters, setFilters] = useState<GapFilters>(NO_GAP_FILTERS);
  const shown = filterGaps(list.items, filters);
  // Only shown rows count as checked (a list change may hide a checked row).
  const checkedIds = new Set(shown.filter((g) => checked.has(g.id)).map((g) => g.id));

  function changeFilters(next: GapFilters) {
    setFilters(next);
    const visible = new Set(filterGaps(list.items, next).map((g) => g.id));
    setChecked((current) => new Set([...current].filter((id) => visible.has(id))));
  }

  // Story 4.7: another person's change arrives over the event stream; the list is read again
  // (unless a local change happened meanwhile) and a count change is announced.
  const listRef = useRef(list);
  useEffect(() => {
    listRef.current = list;
  });
  const reread = useRef(() => {});
  useEffect(() => {
    reread.current = () => {
    const startedAt = mutation.current;
    void loadGaps(opportunityId).then(
      (result) => {
        if (result.kind !== "ok" || mutation.current !== startedAt) return;
        const before = listRef.current.items;
        setList(result.list);
        const sentence = gapsChangedAnnouncement(before, result.list.items);
        if (sentence) announce(sentence);
      },
      () => undefined,
    );
    };
  });
  const live = useGapsEvents(opportunityId, () => reread.current());
  // While the stream is not connected, polling is the fallback (the detection's own polling
  // covers a running detection); it stops once the stream connects or the tab unmounts.
  useEffect(() => {
    if (live || detecting || !visible) return;
    const timer = setInterval(() => reread.current(), GAPS_FALLBACK_POLL_MS);
    return () => clearInterval(timer);
  }, [live, detecting, visible]);

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
      // A filtered-out row isn't rendered: fall back to the grid's tab-stop row.
      (
        document.querySelector<HTMLElement>(`[data-gap-id="${id}"]`) ??
        document.querySelector<HTMLElement>('button[data-gap-row][tabindex="0"]')
      )?.focus();
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
      case "question-not-editable":
        say(QUESTION_SENT);
        void refresh();
        return;
      case "question-not-sent":
        say(QUESTION_NOT_SENT);
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

  function toggle(item: Gap) {
    const next = new Set(checkedIds);
    if (next.has(item.id)) next.delete(item.id);
    else next.add(item.id);
    setChecked(next);
    announce(`${next.size} selected`);
  }

  function clearSelection() {
    setChecked(new Set());
    announce("Selection cleared");
  }

  async function approveSelected(selection: Gap[]) {
    if (locked || busyIds.size > 0 || selection.length === 0) return;
    setNotice(null);
    setApprovingAll(true);
    let result: ApproveAllQuestionsResult;
    try {
      result = await approveSelectedClarificationQuestions(
        opportunityId,
        selection.map((g) => ({ id: g.question!.id, row_version: g.question!.row_version })),
      );
    } catch {
      result = { kind: "error" };
    }
    if (result.kind === "ok") {
      const reloaded = await refresh();
      setApprovingAll(false);
      setChecked(new Set());
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
      say(APPROVE_SELECTED_FAILED);
    }
  }

  /** Mark these approved questions sent on `sentOn` (Story 4.6); what the form does next. */
  async function markSent(selection: Gap[], sentOn: string): Promise<GapFormOutcome> {
    if (locked || busyIds.size > 0 || selection.length === 0) return "failed";
    setNotice(null);
    setApprovingAll(true);
    let result: MarkSentResult;
    try {
      result = await markClarificationQuestionsSent(
        opportunityId,
        sentOn,
        selection.map((g) => ({ id: g.question!.id, row_version: g.question!.row_version })),
      );
    } catch {
      result = { kind: "error" };
    }
    if (result.kind === "ok") {
      const reloaded = await refresh();
      setApprovingAll(false);
      setChecked(new Set());
      setMarkSentFor(null);
      if (!reloaded) setStale({ changedBy: null });
      announce(sentCount(result.count));
      return "ok";
    }
    setApprovingAll(false);
    switch (result.kind) {
      case "invalid":
        announce(result.detail);
        return { invalid: result.detail };
      case "stale":
        setMarkSentFor(null);
        setStale({ changedBy: result.changedBy });
        announce(staleMessage(result.changedBy));
        return "failed";
      case "forbidden":
        setMarkSentFor(null);
        say(SEND_NOT_ALLOWED);
        void refresh();
        return "failed";
      case "not-found":
        setMarkSentFor(null);
        say(NO_ACCESS_TO_OPPORTUNITY);
        return "failed";
      default:
        say(MARK_SENT_FAILED);
        return "failed";
    }
  }

  async function noAnswer(item: Gap) {
    const question = item.question;
    if (!question || locked || busyIds.has(question.id) || question.status !== "sent") return;
    setNotice(null);
    markBusy(question.id, true);
    let result: QuestionWriteResult;
    try {
      result = await markClarificationQuestionUnanswered({
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
      announce(`${NO_ANSWER}: ${item.title}`);
      return;
    }
    if (result.kind === "forbidden") {
      say(SEND_NOT_ALLOWED);
      void refresh();
      return;
    }
    writeFailed(result, null, NO_ANSWER_FAILED);
  }

  /** Run a Gap write (Story 4.4) and act on its result; what the inspector's form does next. */
  async function writeGap(
    item: Gap,
    call: () => Promise<GapWriteResult>,
    done: (gap: Gap) => string,
  ): Promise<GapFormOutcome> {
    if (locked || busyIds.has(item.id)) return "failed";
    setNotice(null);
    markBusy(item.id, true);
    let result: GapWriteResult;
    try {
      result = await call();
    } catch {
      result = { kind: "error" };
    }
    markBusy(item.id, false);
    switch (result.kind) {
      case "ok": {
        const updated = result.gap;
        mutation.current += 1;
        setList((current) => ({
          ...current,
          items: rankGaps(
            current.items.map((g) =>
              g.id === updated.id && g.row_version <= updated.row_version ? updated : g,
            ),
          ),
        }));
        announce(done(updated));
        return "ok";
      }
      case "stale":
        setStale({ changedBy: result.changedBy });
        announce(staleMessage(result.changedBy));
        return "failed";
      case "invalid":
        announce(result.detail);
        return { invalid: result.detail };
      case "gap-not-open":
        say(GAP_NOT_OPEN);
        void refresh();
        return "failed";
      case "gap-not-reopenable":
        say(GAP_NOT_DISMISSED);
        void refresh();
        return "failed";
      case "forbidden":
        say(GAP_EDIT_NOT_ALLOWED);
        void refresh(); // `can_edit_gaps` changed: the controls go away
        return "failed";
      case "not-found":
        say(GAP_GONE);
        void refresh();
        return "failed";
      default:
        say(SAVE_FAILED);
        return "failed";
    }
  }

  function changeImpact(item: Gap, impact: Impact, reason: string): Promise<GapFormOutcome> {
    // Unchanged: nothing is sent, and the reason stays with a message under the form.
    if (impact === item.impact) return Promise.resolve({ invalid: SAME_IMPACT });
    return writeGap(
      item,
      () =>
        changeGapImpact({
          opportunityId,
          gapId: item.id,
          rowVersion: item.row_version,
          impact,
          reason,
        }),
      (gap) => `Impact changed to ${impactLabel(gap.impact)}: ${gap.title}`,
    );
  }

  function dismiss(item: Gap, kind: DismissReasonKind, note: string): Promise<GapFormOutcome> {
    return writeGap(
      item,
      () =>
        dismissGap({
          opportunityId,
          gapId: item.id,
          rowVersion: item.row_version,
          reasonKind: kind,
          ...(note ? { note } : {}),
        }),
      (gap) => `Dismissed as ${dismissReasonLabel(kind)}: ${gap.title}`,
    );
  }

  function reopen(item: Gap, reason: string): Promise<GapFormOutcome> {
    return writeGap(
      item,
      () => reopenGap({ opportunityId, gapId: item.id, rowVersion: item.row_version, reason }),
      (gap) => `Reopened: ${gap.title}`,
    );
  }

  /** Run an answer write (Story 4.7) and act on its result; what the form does next. */
  async function writeAnswer(
    item: Gap,
    busyId: string,
    call: () => Promise<AnswerWriteResult>,
    done: (gap: Gap) => string,
    fallback: string,
  ): Promise<GapFormOutcome> {
    if (locked || busyIds.has(busyId)) return "failed";
    setNotice(null);
    markBusy(busyId, true);
    let result: AnswerWriteResult;
    try {
      result = await call();
    } catch {
      result = { kind: "error" };
    }
    markBusy(busyId, false);
    switch (result.kind) {
      case "ok": {
        const updated = result.gap;
        mutation.current += 1;
        setList((current) => ({
          ...current,
          items: rankGaps(current.items.map((g) => (g.id === updated.id ? updated : g))),
        }));
        announce(done(updated));
        return "ok";
      }
      case "stale":
        setStale({ changedBy: null });
        announce(staleMessage(null));
        return "failed";
      case "invalid":
        announce(result.detail);
        return { invalid: result.detail };
      case "gap-not-open":
        say(GAP_NOT_OPEN);
        void refresh();
        return "failed";
      case "question-not-sent":
        say(QUESTION_NOT_SENT);
        void refresh();
        return "failed";
      case "forbidden":
        say(ANSWER_NOT_ALLOWED);
        void refresh();
        return "failed";
      case "not-found":
        say(item.answer_suggestions.length > 0 ? SUGGESTION_GONE : QUESTION_GONE);
        void refresh();
        return "failed";
      default:
        say(fallback);
        return "failed";
    }
  }

  function answer(
    item: Gap,
    text: string,
    answeredOn: string,
    settlesGap: boolean,
  ): Promise<GapFormOutcome> {
    const question = item.question;
    if (!question) return Promise.resolve("failed");
    return writeAnswer(
      item,
      question.id,
      () =>
        recordAnswer({
          opportunityId,
          questionId: question.id,
          rowVersion: question.row_version,
          text,
          answeredOn,
          settlesGap,
        }),
      (gap) => `${answeredLabel(gap.answer?.answered_on ?? answeredOn)}: ${gap.title}`,
      ANSWER_FAILED,
    );
  }

  function decide(item: Gap, suggestion: AnswerSuggestion, confirm: boolean) {
    const target = { opportunityId, matchId: suggestion.id, rowVersion: suggestion.row_version };
    void writeAnswer(
      item,
      item.question?.id ?? item.id,
      () => (confirm ? confirmAnswerMatch(target) : rejectAnswerMatch(target)),
      (gap) =>
        confirm
          ? `${answeredLabel(gap.answer?.answered_on ?? "")}: ${gap.title}`
          : `Not an answer: ${gap.title}`,
      DECIDE_FAILED,
    );
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
  const selectedToApprove = canEdit ? toApprove(list.items.filter((g) => checkedIds.has(g.id))) : [];
  const sendable = canSend ? toSend(list.items) : [];
  const selectedToSend = canSend ? toSend(list.items.filter((g) => checkedIds.has(g.id))) : [];
  const toMark = selectedToSend.length > 0 ? selectedToSend : sendable;
  const filtering = hasGapFilters(filters);
  const hasActions = selectedToApprove.length > 0 || approvable > 0 || toMark.length > 0;
  return (
    <div className="flex flex-col gap-4" aria-busy={approvingAll || reloading || undefined}>
      <div className="flex flex-wrap items-center gap-2">
        {/* With no Gaps the empty card speaks for the tab; the heading stays for structure. */}
        <h2 className={list.items.length > 0 ? "mr-2 text-section" : "sr-only"}>Gaps</h2>
        {list.items.length > 0 ? (
          <p className="text-control font-normal text-text-secondary">
            {gapsSummary(list.items, filtering ? shown.length : undefined)}
          </p>
        ) : null}
        <div className="flex-1" />
        {list.items.length > 0 ? (
          <GapsFilters items={list.items} filters={filters} onChange={changeFilters} />
        ) : null}
        {filtering ? (
          <Button type="button" variant="ghost" size="sm" onClick={() => changeFilters(NO_GAP_FILTERS)}>
            {CLEAR_FILTERS}
          </Button>
        ) : null}
        {hasActions ? (
          <div className="flex flex-wrap items-center gap-2">
            {selectedToApprove.length > 0 ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={locked || busyIds.size > 0}
                onClick={() => void approveSelected(selectedToApprove)}
              >
                {approveSelectedLabel(selectedToApprove.length)}
              </Button>
            ) : approvable > 0 ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={locked || busyIds.size > 0}
                onClick={() => void approveAll()}
              >
                {approveAllLabel(approvable)}
              </Button>
            ) : null}
            {toMark.length > 0 ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-expanded={markSentFor !== null}
                disabled={locked || busyIds.size > 0}
                onClick={() => setMarkSentFor((current) => (current ? null : toMark))}
              >
                {selectedToSend.length > 0
                  ? markSelectedSentLabel(selectedToSend.length)
                  : markAllSentLabel(sendable.length)}
              </Button>
            ) : null}
            {sendable.length > 0 ? <QuestionsExport opportunityId={opportunityId} /> : null}
          </div>
        ) : null}
      </div>
      <DetectionStatus
        detection={list.detection}
        canStart={list.can_start_detection}
        busy={busy}
        message={message}
        stalled={stalled}
        onRetry={() => void retry()}
      />
      {markSentFor && markSentFor.length > 0 ? (
        <MarkSentForm
          label="Mark questions sent"
          confirm={`Mark ${markSentFor.length} sent`}
          disabled={locked || busyIds.size > 0}
          onSubmit={(sentOn) => {
            // The questions as they are now (one may have been marked sent meanwhile).
            const ids = new Set(markSentFor.map((g) => g.id));
            const current = toSend(list.items.filter((g) => ids.has(g.id)));
            if (current.length === 0) {
              setMarkSentFor(null);
              return Promise.resolve<GapFormOutcome>("failed");
            }
            return markSent(current, sentOn);
          }}
          onCancel={() => setMarkSentFor(null)}
        />
      ) : null}
      {/* Screen readers hear these through the shell's single live region. */}
      {stale ? (
        <InlineAlert
          id={noticeId}
          lead={staleMessage(stale.changedBy)}
          onReload={() => void reload()}
          reloading={reloading}
          reloadRef={reloadRef}
        />
      ) : notice ? (
        <p id={noticeId} className="text-meta text-destructive">
          {notice}
        </p>
      ) : null}
      {list.items.length > 0 ? (
        <>
          <GapsList
            items={shown}
            selectedId={selected?.id ?? null}
            checkedIds={checkedIds}
            inspectorOpen={rightPaneOpen && selected !== null}
            onOpen={open}
            onEdit={canEdit ? startEdit : undefined}
            onToggle={canSelect ? toggle : undefined}
            onClearSelection={clearSelection}
            empty={
              <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
                <p className="text-body text-text-secondary">{NO_FILTER_MATCH}</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => changeFilters(NO_GAP_FILTERS)}
                >
                  {CLEAR_FILTERS}
                </Button>
              </div>
            }
          />
          <GapsKeyHints canEdit={canEdit} canSelect={canSelect} />
        </>
      ) : succeeded ? (
        <p className="text-muted-foreground">{NONE_FOUND}</p>
      ) : !detecting && !failed ? (
        <EmptyTabCard
          title={NO_GAPS}
          body={NO_GAPS_BODY}
          actionLabel={OPEN_REQUIREMENTS}
          href={tabHref(opportunityId, "requirements")}
        />
      ) : null}
      {selected ? (
        <RightPaneContent>
          <GapInspector
            key={selected.id}
            gap={selected}
            opportunityId={opportunityId}
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
            gapEdit={
              canEditGaps
                ? {
                    busy: busyIds.has(selected.id),
                    locked,
                    onImpact: (impact, reason) => changeImpact(selected, impact, reason),
                    onDismiss: (kind, note) => dismiss(selected, kind, note),
                    onReopen: (reason) => reopen(selected, reason),
                  }
                : undefined
            }
            send={
              canSend && selected.question
                ? {
                    busy: busyIds.has(selected.question.id),
                    locked,
                    onMarkSent: (sentOn) => markSent([selected], sentOn),
                    onNoAnswer: () => void noAnswer(selected),
                    onRecordAnswer: (text, answeredOn, settlesGap) =>
                      answer(selected, text, answeredOn, settlesGap),
                    onConfirmSuggestion: (suggestion) => decide(selected, suggestion, true),
                    onRejectSuggestion: (suggestion) => decide(selected, suggestion, false),
                  }
                : undefined
            }
          />
        </RightPaneContent>
      ) : null}
    </div>
  );
}
