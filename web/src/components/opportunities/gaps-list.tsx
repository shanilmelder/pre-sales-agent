"use client";

import { CircleAlertIcon } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import {
  loadGaps,
  startGapDetection,
  type StartGapDetectionResult,
} from "@/app/opportunities/actions";
import { GapInspector, QuestionPill } from "@/components/opportunities/gap-inspector";
import { ImpactBar } from "@/components/opportunities/impact-bar";
import { useAnnounce } from "@/components/shell/live-region";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import {
  categoryLabel,
  DETECTING,
  DETECTION_POLL_LIMIT_MS,
  DETECTION_POLL_MS,
  detectionFailure,
  gapCount,
  isDetecting,
  NO_GAPS,
  NONE_FOUND,
  STILL_DETECTING,
  type Detection,
  type Gap,
  type GapList,
} from "@/lib/gaps";
import { convertedLabel } from "@/lib/estimates";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";

export const RETRY = "Retry";
const RETRY_FAILED = "The retry failed. Try again.";
const RETRY_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can detect Gaps.";

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

/** The Gaps as 32px card rows, in the order given (the API ranks the open ones high, medium,
 * low, and lists converted ones after them). Each row shows the impact label with its
 * 3-segment bar, the category in meta type, the title and the question's "Draft" pill. A
 * converted Gap's row is greyed out and labelled "Converted to Condition" or "Converted to
 * Contingency" (Story 8.4) instead of the pill.
 *
 * The list is one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first row); j/k (with single-key shortcuts on) or the arrow keys move between rows, and
 * Enter, Space or a click opens the row. The selected row is `aria-selected`. */
export function GapsList({
  items,
  selectedId = null,
  onOpen,
}: {
  items: readonly Gap[];
  selectedId?: string | null;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (item: Gap, viaKeyboard: boolean) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && items.some((i) => i.id === id)) ??
    items[0]?.id;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
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
                  <QuestionPill />
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
 * Gap that a re-run superseded leaves the pane showing "Nothing selected." Read-only for
 * everyone; Retry only for those who may start a detection. */
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
  /** Bumped on every local change (a Retry); a poll that started before one is dropped. */
  const mutation = useRef(0);
  const detectingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const detecting = isDetecting(list.detection);

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setList(initial);
    setStalled(false);
  }

  const selected =
    selectedId === null ? null : (list.items.find((item) => item.id === selectedId) ?? null);

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
      document.querySelector<HTMLElement>(`[data-gap-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function open(item: Gap, viaKeyboard: boolean) {
    setSelectedId(item.id);
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

  const failed = list.detection?.status === "failed";
  const succeeded = list.detection?.status === "succeeded";
  return (
    <div className="flex flex-col gap-4">
      <DetectionStatus
        detection={list.detection}
        canStart={list.can_start_detection}
        busy={busy}
        message={message}
        stalled={stalled}
        onRetry={() => void retry()}
      />
      {list.items.length > 0 ? (
        <GapsList items={list.items} selectedId={selected?.id ?? null} onOpen={open} />
      ) : succeeded ? (
        <p className="text-muted-foreground">{NONE_FOUND}</p>
      ) : !detecting && !failed ? (
        <p className="text-muted-foreground">{NO_GAPS}</p>
      ) : null}
      {selected ? (
        <RightPaneContent>
          <GapInspector key={selected.id} gap={selected} focusRequest={focusRequest} />
        </RightPaneContent>
      ) : null}
    </div>
  );
}
