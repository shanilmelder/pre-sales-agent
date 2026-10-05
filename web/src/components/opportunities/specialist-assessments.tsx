"use client";

import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleDotIcon,
  CircleMinusIcon,
  ClockIcon,
  ListChecksIcon,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import {
  cancelAssessmentRun,
  loadAssessments,
  retryAssessmentTask,
  startAssessmentRun,
  type StartAssessmentResult,
} from "@/app/opportunities/actions";
import { AssessmentFindingInspector } from "@/components/opportunities/assessment-finding-inspector";
import { useFindingSelection } from "@/components/opportunities/finding-selection";
import { SeverityPill } from "@/components/opportunities/severity-pill";
import { useAnnounce } from "@/components/shell/live-region";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  agentLabel,
  CANCEL_RUN,
  CANCEL_RUN_CONFIRM,
  CANCEL_RUN_DESCRIPTION,
  CANCEL_RUN_KEEP,
  CANCEL_RUN_TITLE,
  confidenceLabel,
  failureReason,
  isAssessing,
  kindLabel,
  NO_AGENT_ASSESSMENT,
  NO_ASSESSMENT,
  NOTHING_TO_ASSESS,
  recommendationInfo,
  RUN_ASSESSMENT,
  runStatusLabel,
  STILL_ASSESSING,
  taskElapsed,
  taskStatusLabel,
  WAITING_FOR_WORKER,
  type AgentAssessment,
  type Assessment,
  type AssessmentAgent,
  type AssessmentFinding,
  type AssessmentRun,
  type AssessmentsView,
  type AssessmentTask,
  type Recommendation,
} from "@/lib/assessments";
import { hours } from "@/lib/estimates";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import {
  countsLabel,
  REVIEW_POLL_LIMIT_MS,
  REVIEW_POLL_MS,
  SEVERITIES,
  type SeverityCounts,
} from "@/lib/red-team";
import { cn } from "@/lib/utils";

export const RETRY = "Retry";
const START_FAILED = "The assessment could not be started. Try again.";
const CANCEL_FAILED = "The run could not be cancelled. Try again.";
const NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can run an assessment.";

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

const chipClass =
  "inline-flex h-5 shrink-0 items-center gap-1 rounded-sm border border-border bg-background px-1.5 text-meta text-muted-foreground";

/** A recommendation: always an icon and a label, never colour alone. */
export function RecommendationPill({
  recommendation,
}: {
  recommendation: Recommendation;
}) {
  const known = recommendationInfo(recommendation);
  const Icon = known.icon;
  return (
    <span
      data-recommendation={known.value}
      className="inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground"
    >
      <Icon className={cn("size-3 shrink-0", known.tone)} aria-hidden="true" />
      {known.label}
    </span>
  );
}

/** The severity counts as icon-and-number pairs, most severe first. */
function SeverityCountsLine({ counts }: { counts: SeverityCounts }) {
  return (
    <p className="flex flex-wrap items-center gap-3 text-label">
      <span className="sr-only">{countsLabel(counts)}</span>
      {SEVERITIES.map((s) => {
        const Icon = s.icon;
        return (
          <span
            key={s.value}
            aria-hidden="true"
            className="inline-flex items-center gap-1"
          >
            <Icon className={`size-3 shrink-0 ${s.tone}`} />
            <span className="[font-variant-numeric:tabular-nums]">
              {counts[s.value]}
            </span>
            <span className="text-muted-foreground">{s.label}</span>
          </span>
        );
      })}
    </p>
  );
}

/** An agent's Findings as dense 32px rows, in the order given (the API ranks them critical to
 * low, then by position): severity pill, kind, the specific title and the Requirement count.
 * One Tab stop (roving tabindex); j/k (with single-key shortcuts on) or the arrows move
 * between rows; Enter, Space or a click opens the row, which is then `aria-selected`. */
export function AssessmentFindingList({
  agent,
  items,
  selectedId = null,
  onOpen,
}: {
  agent: AssessmentAgent;
  items: readonly AssessmentFinding[];
  selectedId?: string | null;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (item: AssessmentFinding, viaKeyboard: boolean) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find(
      (id) => id !== null && items.some((i) => i.id === id),
    ) ?? items[0]?.id;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down =
      event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up =
      event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      container.current?.querySelectorAll<HTMLButtonElement>(
        "button[data-finding-row]",
      ) ?? [],
    );
    const index = buttons.findIndex((button) => button === event.target);
    const next =
      index === -1
        ? 0
        : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <div
      ref={container}
      role="grid"
      aria-label={`${agentLabel(agent)} Findings`}
      onKeyDown={onKeyDown}
      className="flex flex-col"
    >
      {items.map((item) => {
        const selected = item.id === selectedId;
        const count = item.requirements.length;
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
                <span className="w-24 shrink-0 truncate text-meta text-muted-foreground">
                  {kindLabel(item.kind)}
                </span>
                <span className="min-w-0 flex-1 truncate text-body">
                  {item.title}
                </span>
                <span className={chipClass}>
                  <ListChecksIcon
                    aria-hidden="true"
                    className="size-3 shrink-0"
                  />
                  <span className="[font-variant-numeric:tabular-nums]">
                    {count}
                  </span>
                  <span className="sr-only">
                    {count === 1 ? " Requirement" : " Requirements"}
                  </span>
                </span>
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** The agent's effort per Requirement with the server-calculated total. */
function EffortTable({ assessment }: { assessment: Assessment }) {
  if (assessment.effort.length === 0) {
    return <p className="text-meta text-muted-foreground">No effort sized.</p>;
  }
  return (
    <table className="w-full border-collapse text-left">
      <caption className="sr-only">
        {agentLabel(assessment.agent)} effort
      </caption>
      <thead>
        <tr className="border-b border-border text-label text-muted-foreground">
          <th scope="col" className="w-24 py-1 pr-3 font-normal">
            Requirement
          </th>
          <th scope="col" className="w-20 py-1 pr-3 text-right font-normal">
            Hours
          </th>
          <th scope="col" className="py-1 font-normal">
            Basis
          </th>
        </tr>
      </thead>
      <tbody>
        {assessment.effort.map((row) => (
          <tr
            key={row.requirement.id}
            className="border-b border-border align-baseline"
          >
            <td className="py-1 pr-3 font-mono text-meta text-muted-foreground">
              {row.requirement.label}
            </td>
            <td className="py-1 pr-3 text-right text-numeric">
              {hours(row.hours)}
            </td>
            <td className="py-1 text-body">{row.basis}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="text-body-strong">
          <th scope="row" className="py-1 pr-3 text-left font-semibold">
            Total
          </th>
          <td className="py-1 pr-3 text-right text-numeric">
            {hours(assessment.total_hours)}
          </td>
          <td />
        </tr>
      </tfoot>
    </table>
  );
}

/** One agent's card: its name, version, recommendation, confidence with its basis, severity
 * counts, Findings and effort table ("No Assessment yet." before its first). */
export function AssessmentCard({
  slot,
  selectedId = null,
  onOpen,
}: {
  slot: AgentAssessment;
  selectedId?: string | null;
  onOpen?: (
    item: AssessmentFinding,
    agent: AssessmentAgent,
    viaKeyboard: boolean,
  ) => void;
}) {
  const headingId = useId();
  const assessment = slot.assessment;
  return (
    <article
      aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-md border border-border p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h4 id={headingId} className="text-body-strong">
          {agentLabel(slot.agent)}
        </h4>
        {assessment ? (
          <>
            <span className="inline-flex h-5 shrink-0 items-center rounded-full border border-border bg-background px-2 text-label text-foreground">
              v{assessment.version}
            </span>
            <RecommendationPill recommendation={assessment.recommendation} />
          </>
        ) : null}
      </div>
      {assessment ? (
        <>
          <p className="text-body">
            <span className="text-label">
              {confidenceLabel(assessment.confidence)}
            </span>
            <span className="text-muted-foreground">
              : {assessment.confidence_basis}
            </span>
          </p>
          <SeverityCountsLine counts={assessment.counts} />
          <AssessmentFindingList
            agent={slot.agent}
            items={assessment.findings}
            selectedId={selectedId}
            onOpen={(item, viaKeyboard) =>
              onOpen?.(item, slot.agent, viaKeyboard)
            }
          />
          <EffortTable assessment={assessment} />
        </>
      ) : (
        <p className="text-muted-foreground">{NO_AGENT_ASSESSMENT}</p>
      )}
    </article>
  );
}

const TASK_PILL_ICONS: Record<
  AssessmentTask["status"],
  { icon: LucideIcon; tone: string }
> = {
  queued: { icon: ClockIcon, tone: "text-muted-foreground" },
  running: { icon: CircleDotIcon, tone: "text-agent" },
  succeeded: { icon: CircleCheckIcon, tone: "text-resolved" },
  failed: { icon: CircleAlertIcon, tone: "text-blocker" },
  skipped: { icon: CircleMinusIcon, tone: "text-muted-foreground" },
};

/** A task's status: always an icon and a label, never colour alone (Queued neutral, Running
 * agent colour, Done green, Failed red, Skipped neutral). */
function TaskStatusPill({ status }: { status: AssessmentTask["status"] }) {
  const known = TASK_PILL_ICONS[status] ?? TASK_PILL_ICONS.queued;
  const Icon = known.icon;
  return (
    <span
      data-task-pill={status}
      className="inline-flex h-5 w-[5.5rem] shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground"
    >
      <Icon className={cn("size-3 shrink-0", known.tone)} aria-hidden="true" />
      {taskStatusLabel(status)}
    </span>
  );
}

/** The browser's clock, re-read every second while `ticking`. */
function useNow(ticking: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!ticking) return;
    // Re-read at once (not a second later): the clock may be from long before it ticked.
    const refresh = setTimeout(() => setNow(Date.now()), 0);
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearTimeout(refresh);
      clearInterval(timer);
    };
  }, [ticking]);
  return now;
}

/** The agent run panel: one 28px row per task of the latest run (in any status) with the
 * agent's role, a status pill, the elapsed time in tabular figures (`m:ss`, ticking each
 * second while it runs, its final duration once done or failed, blank before it starts) and a
 * running dot (static under reduced motion). Queued rows say "Waiting for the worker"; failed
 * rows give the reason and **Retry** for those who may start one (never in a cancelled run;
 * skipped rows keep a duration if they had started). Elapsed time comes from the
 * task's timestamps and the browser's clock, so it ticks without a fetch. */
export function AgentRunPanel({
  run,
  canStart = false,
  busy = false,
  stalled = false,
  onRetry,
}: {
  run: AssessmentRun;
  canStart?: boolean;
  busy?: boolean;
  stalled?: boolean;
  onRetry?: (agent: AssessmentAgent) => void;
}) {
  const assessing = isAssessing(run);
  const now = useNow(assessing && !stalled);
  return (
    <ul aria-label="Agent progress" className="flex w-full flex-col">
      {run.tasks.map((task) => {
        const failed = task.status === "failed";
        const runningDot = task.status === "running" && !stalled;
        const note =
          task.status === "queued"
            ? WAITING_FOR_WORKER
            : failed
              ? failureReason(task.error_code)
              : null;
        return (
          <li
            key={task.agent}
            data-task-status={task.status}
            className="flex min-h-row-compact flex-wrap items-center gap-x-3 gap-y-1 text-label"
          >
            <span className="w-36 shrink-0 truncate">
              {agentLabel(task.agent)}
            </span>
            <TaskStatusPill status={task.status} />
            <span
              data-testid="elapsed"
              suppressHydrationWarning
              className="w-12 shrink-0 text-right text-numeric"
            >
              {taskElapsed(task, now)}
            </span>
            <span className="flex size-1.5 shrink-0" aria-hidden="true">
              {runningDot ? (
                <span
                  data-testid="running-dot"
                  className="size-1.5 animate-pulse rounded-full bg-agent motion-reduce:animate-none"
                />
              ) : null}
            </span>
            {note ? (
              <span
                className={cn(
                  "min-w-0 flex-1 truncate",
                  failed ? "text-blocker" : "text-muted-foreground",
                )}
              >
                {note}
              </span>
            ) : null}
            {failed && canStart && !assessing && run.status !== "cancelled" ? (
              <button
                type="button"
                disabled={busy}
                aria-label={`${RETRY} ${agentLabel(task.agent)}`}
                onClick={() => onRetry?.(task.agent)}
                className={actionClass}
              >
                {RETRY}
              </button>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/** **Cancel run**, confirmed first ("Cancel this run? Completed results are kept."). Focus
 * goes back to the button when the dialog closes. */
function CancelRunButton({
  busy = false,
  onConfirm,
}: {
  /** A start, retry or cancel is in flight: the cancel would be dropped. */
  busy?: boolean;
  onConfirm?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        disabled={busy}
        render={<button type="button" className={actionClass} />}
      >
        {CANCEL_RUN}
      </DialogTrigger>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{CANCEL_RUN_TITLE}</DialogTitle>
          <DialogDescription>{CANCEL_RUN_DESCRIPTION}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>
            {CANCEL_RUN_KEEP}
          </DialogClose>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={() => {
              setOpen(false);
              onConfirm?.();
            }}
          >
            {CANCEL_RUN_CONFIRM}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The section header: **Run assessment** and, while the run is queued or running, **Cancel
 * run** (both only for those who may start one), the latest run's status and the agent run
 * panel for that run ("Still assessing — reload to check." once polling has stopped). */
export function SpecialistAssessmentsHeader({
  run,
  canStart = false,
  busy = false,
  message = null,
  stalled = false,
  focusStartRequest = 0,
  onStart,
  onRetry,
  onCancel,
}: {
  run: AssessmentRun | null;
  canStart?: boolean;
  /** A start or retry is in flight. */
  busy?: boolean;
  /** A start or retry's failure sentence. */
  message?: string | null;
  /** Polling has stopped while still assessing. */
  stalled?: boolean;
  /** Bumped to move focus to **Run assessment** (after a cancel removed **Cancel run**). */
  focusStartRequest?: number;
  onStart?: () => void;
  onRetry?: (agent: AssessmentAgent) => void;
  onCancel?: () => void;
}) {
  const assessing = isAssessing(run);
  const startRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (focusStartRequest > 0) startRef.current?.focus();
  }, [focusStartRequest]);
  return (
    <div className="flex flex-col items-start gap-1.5">
      <div className="flex flex-wrap items-center gap-3">
        {canStart ? (
          <button
            ref={startRef}
            type="button"
            disabled={busy || assessing}
            onClick={() => onStart?.()}
            className={actionClass}
          >
            {RUN_ASSESSMENT}
          </button>
        ) : null}
        {canStart && assessing ? (
          <CancelRunButton busy={busy} onConfirm={onCancel} />
        ) : null}
        {run ? (
          <p
            className="text-label text-muted-foreground"
            data-status={run.status}
          >
            {runStatusLabel(run)}
          </p>
        ) : null}
      </div>
      {assessing && stalled ? (
        <p className="text-label text-muted-foreground">{STILL_ASSESSING}</p>
      ) : null}
      {run ? (
        <AgentRunPanel
          run={run}
          canStart={canStart}
          busy={busy}
          stalled={assessing && stalled}
          onRetry={onRetry}
        />
      ) : null}
      {message ? (
        <span className="text-meta text-destructive">{message}</span>
      ) : null}
    </div>
  );
}

function failureMessage(
  result: StartAssessmentResult,
  failed: string = START_FAILED,
): string {
  switch (result.kind) {
    case "forbidden":
      return NOT_ALLOWED;
    case "not-found":
      return NO_ACCESS_TO_OPPORTUNITY;
    default:
      return failed;
  }
}

/** The Assessments tab's Specialist Assessments section: the header, then one card per
 * agent; the selected Finding's inspector goes in the right pane (opened if closed). While a
 * run is queued or running the section is re-read every 2 s: paused while the tab is
 * hidden, and stopped after 15 minutes. Inside a `FindingSelectionProvider` its selection is
 * shared with the tab's other sections. Read-only for sales representatives (no Run
 * assessment, Retry or Cancel run). */
export function SpecialistAssessmentsSection({
  opportunityId,
  initial,
}: {
  opportunityId: string;
  initial: AssessmentsView;
}) {
  const announce = useAnnounce();
  const headingId = useId();
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [view, setView] = useState<AssessmentsView>(initial);
  const [selectedId, setSelectedId] = useFindingSelection("specialist");
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);
  const [syncedFrom, setSyncedFrom] = useState(initial);
  const [stalled, setStalled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [focusStartRequest, setFocusStartRequest] = useState(0);
  /** Bumped after every poll, so the next one is scheduled. */
  const [pollTick, setPollTick] = useState(0);
  /** Bumped on every local change (a start or retry); a poll that started before is dropped. */
  const mutation = useRef(0);
  const assessingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const assessing = isAssessing(view.run);

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setView(initial);
    setStalled(false);
  }

  let selected: { finding: AssessmentFinding; agent: AssessmentAgent } | null =
    null;
  for (const slot of view.assessments) {
    const found = slot.assessment?.findings.find((f) => f.id === selectedId);
    if (found) selected = { finding: found, agent: slot.agent };
  }

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
    if (
      id &&
      (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)
    ) {
      document.querySelector<HTMLElement>(`[data-finding-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function open(item: AssessmentFinding, viaKeyboard: boolean) {
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
    if (!assessing) {
      assessingSince.current = null;
      return;
    }
    assessingSince.current ??= Date.now();
    if (!visible) return;
    if (Date.now() - assessingSince.current >= REVIEW_POLL_LIMIT_MS) {
      // Past the limit (e.g. hidden through it): say so instead of pulsing forever.
      setStalled(true);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const startedAt = mutation.current;
      try {
        const result = await loadAssessments(opportunityId);
        if (
          !cancelled &&
          result.kind === "ok" &&
          mutation.current === startedAt
        ) {
          setView(result.assessments);
          const { run, assessments } = result.assessments;
          if (run && !isAssessing(run)) {
            announce(
              run.status === "succeeded" &&
                assessments.every((s) => s.assessment === null)
                ? NOTHING_TO_ASSESS
                : runStatusLabel(run),
            );
          }
        }
      } catch {
        // A failed poll is retried on the next tick.
      }
      if (cancelled) return;
      const since = assessingSince.current;
      if (since !== null && Date.now() - since >= REVIEW_POLL_LIMIT_MS)
        setStalled(true);
      setPollTick((tick) => tick + 1);
    }, REVIEW_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [assessing, visible, opportunityId, pollTick, announce]);

  const sectionRef = useRef<HTMLElement>(null);

  /** After a cancel removed Cancel run: focus Run assessment, unless the user has moved
   * focus out of this section. */
  function focusStartAfterCancel() {
    const active = document.activeElement;
    if (
      !active ||
      active === document.body ||
      sectionRef.current?.contains(active)
    )
      setFocusStartRequest((n) => n + 1);
  }

  async function act(
    request: () => Promise<StartAssessmentResult>,
    failed: string = START_FAILED,
    cancelling = false,
  ) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    let result: StartAssessmentResult;
    try {
      result = await request();
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      const { run } = result;
      mutation.current += 1;
      assessingSince.current = null;
      setStalled(false);
      setView((current) => ({ ...current, run }));
      announce(runStatusLabel(run));
      // Cancel run is gone: keep focus in the header, on the way to a new run.
      if (run.status === "cancelled") focusStartAfterCancel();
    } else if (result.kind === "conflict") {
      // One is already queued or running (or the task changed): show what is stored now.
      try {
        const loaded = await loadAssessments(opportunityId);
        if (loaded.kind === "ok") {
          mutation.current += 1;
          setView(loaded.assessments);
          const { run } = loaded.assessments;
          if (cancelling && run) {
            // The run finished meanwhile: say how, and keep focus off <body>.
            announce(runStatusLabel(run));
            if (!isAssessing(run)) focusStartAfterCancel();
          }
        }
      } catch {
        // The section stays as it is.
      }
    } else {
      const sentence = failureMessage(result, failed);
      setMessage(sentence);
      announce(sentence);
    }
  }

  const runId = view.run?.id;
  const anyAssessment = view.assessments.some(
    (slot) => slot.assessment !== null,
  );
  return (
    <section
      ref={sectionRef}
      aria-labelledby={headingId}
      className="flex flex-col gap-4"
    >
      <h3 id={headingId} className="text-body-strong">
        Specialist Assessments
      </h3>
      <SpecialistAssessmentsHeader
        run={view.run}
        canStart={view.can_start}
        busy={busy}
        message={message}
        stalled={stalled}
        onStart={() => void act(() => startAssessmentRun(opportunityId))}
        focusStartRequest={focusStartRequest}
        onRetry={(agent) =>
          void act(() => retryAssessmentTask(opportunityId, runId, agent))
        }
        onCancel={() =>
          void act(
            () => cancelAssessmentRun(opportunityId, runId),
            CANCEL_FAILED,
            true,
          )
        }
      />
      {anyAssessment ? (
        <div className="flex flex-col gap-3">
          {view.assessments.map((slot) => (
            <AssessmentCard
              key={slot.agent}
              slot={slot}
              selectedId={selected?.finding.id ?? null}
              onOpen={(item, _agent, viaKeyboard) => open(item, viaKeyboard)}
            />
          ))}
        </div>
      ) : view.run?.status === "succeeded" ? (
        <p className="text-muted-foreground">{NOTHING_TO_ASSESS}</p>
      ) : !view.run ? (
        <p className="text-muted-foreground">{NO_ASSESSMENT}</p>
      ) : null}
      {selected ? (
        <RightPaneContent>
          <AssessmentFindingInspector
            key={selected.finding.id}
            finding={selected.finding}
            agent={selected.agent}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </section>
  );
}
