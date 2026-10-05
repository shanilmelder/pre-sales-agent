"use client";

import { CircleAlertIcon, ListChecksIcon, SigmaIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import {
  loadRedTeam,
  startRedTeamReview,
  type StartRedTeamReviewResult,
} from "@/app/opportunities/actions";
import { useFindingSelection } from "@/components/opportunities/finding-selection";
import { RedTeamInspector } from "@/components/opportunities/red-team-inspector";
import { SeverityPill } from "@/components/opportunities/severity-pill";
import { useAnnounce } from "@/components/shell/live-region";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import {
  categoryLabel,
  countsLabel,
  findingCount,
  isReviewing,
  NO_REVIEW,
  NOTHING_TO_REVIEW,
  REVIEW_POLL_LIMIT_MS,
  REVIEW_POLL_MS,
  reviewFailure,
  reviewLabel,
  REVIEWING,
  SEVERITIES,
  STILL_REVIEWING,
  type RedTeamFinding,
  type RedTeamReview,
  type RedTeamRun,
  type RedTeamView,
} from "@/lib/red-team";

export const RETRY = "Retry";
const RETRY_FAILED = "The retry failed. Try again.";
const RETRY_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can start a Red Team review.";

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

const chipClass =
  "inline-flex h-5 shrink-0 items-center gap-1 rounded-sm border border-border bg-background px-1.5 text-meta text-muted-foreground";

/** A count chip: how many Requirements (or Estimate lines) the Finding challenges. */
function CountChip({ count, kind }: { count: number; kind: "requirement" | "line" }) {
  const Icon = kind === "requirement" ? ListChecksIcon : SigmaIcon;
  const noun =
    kind === "requirement"
      ? count === 1
        ? " Requirement"
        : " Requirements"
      : count === 1
        ? " Estimate line"
        : " Estimate lines";
  return (
    <span className={chipClass}>
      <Icon aria-hidden="true" className="size-3 shrink-0" />
      <span className="[font-variant-numeric:tabular-nums]">{count}</span>
      <span className="sr-only">{noun}</span>
    </span>
  );
}

/** The Findings as dense 32px rows, in the order given (the API ranks them critical to low,
 * then by position). Each row shows the severity pill, the category in meta type, the
 * specific title, and the Requirement and Estimate line count chips.
 *
 * The list is one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first row); j/k (with single-key shortcuts on) or the arrow keys move between rows, and
 * Enter, Space or a click opens the row. The selected row is `aria-selected`. */
export function RedTeamList({
  items,
  selectedId = null,
  onOpen,
}: {
  items: readonly RedTeamFinding[];
  selectedId?: string | null;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (item: RedTeamFinding, viaKeyboard: boolean) => void;
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
      container.current?.querySelectorAll<HTMLButtonElement>("button[data-finding-row]") ?? [],
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
      aria-label="Red Team Findings"
      onKeyDown={onKeyDown}
      className="flex flex-col"
    >
      {items.map((item) => {
        const selected = item.id === selectedId;
        return (
          <div
            key={item.id}
            role="row"
            aria-selected={selected}
            className={`border-b border-border ${selected ? "bg-muted" : "hover:bg-muted/60"}`}
          >
            <div role="gridcell">
              <button
                type="button"
                data-finding-row=""
                data-finding-id={item.id}
                tabIndex={item.id === tabStopId ? 0 : -1}
                onFocus={() => setFocusedId(item.id)}
                // A keyboard-activated click has no pointer clicks (detail 0).
                onClick={(event) => onOpen?.(item, event.detail === 0)}
                className="flex min-h-row w-full items-center gap-3 rounded-sm px-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <SeverityPill severity={item.severity} />
                <span className="w-44 shrink-0 truncate text-meta text-muted-foreground">
                  {categoryLabel(item.category)}
                </span>
                <span className="min-w-0 flex-1 truncate text-body">{item.title}</span>
                <CountChip count={item.requirements.length} kind="requirement" />
                <CountChip count={item.lines.length} kind="line" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** The severity counts as icon-and-number pairs, most severe first. */
function SeverityCountsLine({ review }: { review: RedTeamReview }) {
  return (
    <p className="flex flex-wrap items-center gap-3 text-label">
      <span className="sr-only">{countsLabel(review.counts)}</span>
      {SEVERITIES.map((s) => {
        const Icon = s.icon;
        return (
          <span key={s.value} aria-hidden="true" className="inline-flex items-center gap-1">
            <Icon className={`size-3 shrink-0 ${s.tone}`} />
            <span className="[font-variant-numeric:tabular-nums]">{review.counts[s.value]}</span>
            <span className="text-muted-foreground">{s.label}</span>
          </span>
        );
      })}
    </p>
  );
}

/** The header above the Findings: "Red Team v2" with the severity counts; "Red Team
 * reviewing" with a running dot while a review is queued or running ("Still reviewing —
 * reload to check." once polling has stopped); "Red Team review failed: <reason>" with
 * **Retry** (only for those who may start a review) once failed. */
export function RedTeamHeader({
  review,
  run,
  canStart = false,
  busy = false,
  message = null,
  stalled = false,
  onRetry,
}: {
  review: RedTeamReview | null;
  run: RedTeamRun | null;
  canStart?: boolean;
  /** A Retry is in flight. */
  busy?: boolean;
  /** A Retry's failure sentence. */
  message?: string | null;
  /** Polling has stopped while still reviewing. */
  stalled?: boolean;
  onRetry?: () => void;
}) {
  const reviewing = isReviewing(run);
  const failed = run?.status === "failed";
  if (!review && !reviewing && !failed) return null;
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex flex-wrap items-center gap-3">
        {review ? (
          <>
            <span className="inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full border border-border bg-background px-2 text-label text-foreground">
              {reviewLabel(review)}
            </span>
            <SeverityCountsLine review={review} />
          </>
        ) : null}
        {reviewing && stalled ? (
          <p className="text-label text-muted-foreground">{STILL_REVIEWING}</p>
        ) : reviewing ? (
          <p className="flex items-center gap-2 text-label" data-status={run?.status}>
            <span
              aria-hidden="true"
              data-testid="running-dot"
              className="size-1.5 shrink-0 animate-pulse rounded-full bg-agent motion-reduce:animate-none"
            />
            {REVIEWING}
          </p>
        ) : null}
      </div>
      {failed ? (
        <>
          <p className="flex items-center gap-1.5 text-label text-blocker" data-status="failed">
            <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
            {reviewFailure(run.error_code)}
          </p>
          {canStart ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => onRetry?.()}
              className={actionClass}
            >
              {RETRY}
            </button>
          ) : null}
        </>
      ) : null}
      {message ? <span className="text-meta text-destructive">{message}</span> : null}
    </div>
  );
}

function retryMessage(result: StartRedTeamReviewResult): string {
  switch (result.kind) {
    case "forbidden":
      return RETRY_NOT_ALLOWED;
    case "not-found":
      return NO_ACCESS_TO_OPPORTUNITY;
    default:
      return RETRY_FAILED;
  }
}

/** The Assessments tab's Red Team section: the header and the ranked Findings in the main
 * pane, and the selected Finding's inspector in the right pane (opened if closed). While a
 * review is queued or running the section is re-read every 2 s: paused while the tab is
 * hidden, and stopped after 15 minutes. A selected Finding that a newer review replaced
 * leaves the pane showing "Nothing selected." Inside a `FindingSelectionProvider` its
 * selection is shared with the tab's other sections (one Finding selected at a time).
 * Read-only for everyone; Retry only for those who may start a review. */
export function RedTeamSection({
  opportunityId,
  initial,
}: {
  opportunityId: string;
  initial: RedTeamView;
}) {
  const announce = useAnnounce();
  const headingId = useId();
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [view, setView] = useState<RedTeamView>(initial);
  const [selectedId, setSelectedId] = useFindingSelection("red-team");
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
  const reviewingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const reviewing = isReviewing(view.run);

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setView(initial);
    setStalled(false);
  }

  const findings = view.review?.findings ?? [];
  const selected =
    selectedId === null ? null : (findings.find((item) => item.id === selectedId) ?? null);

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
      document.querySelector<HTMLElement>(`[data-finding-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function open(item: RedTeamFinding, viaKeyboard: boolean) {
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
    if (!reviewing) {
      reviewingSince.current = null;
      return;
    }
    reviewingSince.current ??= Date.now();
    if (!visible) return;
    if (Date.now() - reviewingSince.current >= REVIEW_POLL_LIMIT_MS) {
      // Past the limit (e.g. hidden through it): say so instead of pulsing forever.
      setStalled(true);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const startedAt = mutation.current;
      try {
        const result = await loadRedTeam(opportunityId);
        if (!cancelled && result.kind === "ok" && mutation.current === startedAt) {
          setView(result.redTeam);
          const { run, review } = result.redTeam;
          if (!isReviewing(run)) {
            announce(
              run?.status === "failed"
                ? reviewFailure(run.error_code)
                : review
                  ? `${reviewLabel(review)}: ${findingCount(review.findings.length)}`
                  : NOTHING_TO_REVIEW,
            );
          }
        }
      } catch {
        // A failed poll is retried on the next tick.
      }
      if (cancelled) return;
      const since = reviewingSince.current;
      if (since !== null && Date.now() - since >= REVIEW_POLL_LIMIT_MS) setStalled(true);
      setPollTick((tick) => tick + 1);
    }, REVIEW_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [reviewing, visible, opportunityId, pollTick, announce]);

  async function retry() {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    let result: StartRedTeamReviewResult;
    try {
      result = await startRedTeamReview(opportunityId);
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      const { run } = result;
      mutation.current += 1;
      reviewingSince.current = null;
      setStalled(false);
      setView((current) => ({ ...current, run }));
      announce(REVIEWING);
    } else if (result.kind === "conflict") {
      // One is already queued or running: show what is stored now.
      try {
        const loaded = await loadRedTeam(opportunityId);
        if (loaded.kind === "ok") {
          mutation.current += 1;
          setView(loaded.redTeam);
        }
      } catch {
        // The section stays as it is.
      }
    } else {
      const sentence = retryMessage(result);
      setMessage(sentence);
      announce(sentence);
    }
  }

  const failed = view.run?.status === "failed";
  const succeeded = view.run?.status === "succeeded";
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <h3 id={headingId} className="text-body-strong">
        Red Team
      </h3>
      <RedTeamHeader
        review={view.review}
        run={view.run}
        canStart={view.can_start}
        busy={busy}
        message={message}
        stalled={stalled}
        onRetry={() => void retry()}
      />
      {findings.length > 0 ? (
        <RedTeamList items={findings} selectedId={selected?.id ?? null} onOpen={open} />
      ) : succeeded && !view.review ? (
        <p className="text-muted-foreground">{NOTHING_TO_REVIEW}</p>
      ) : !reviewing && !failed ? (
        <p className="text-muted-foreground">{NO_REVIEW}</p>
      ) : null}
      {selected ? (
        <RightPaneContent>
          <RedTeamInspector key={selected.id} finding={selected} focusRequest={focusRequest} />
        </RightPaneContent>
      ) : null}
    </section>
  );
}
