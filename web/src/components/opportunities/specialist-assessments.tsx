"use client";

import {
  CalendarRangeIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  CircleDotIcon,
  CircleMinusIcon,
  ClockIcon,
  LayoutPanelLeftIcon,
  LoaderCircleIcon,
  QuoteIcon,
  ShieldCheckIcon,
  SparklesIcon,
  SwordsIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import {
  cancelAssessmentRun,
  loadAssessments,
  retryAssessmentTask,
  startAssessmentRun,
  type StartAssessmentResult,
} from "@/app/opportunities/actions";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { Pill } from "@/components/ui/pill";
import { pillToneFor } from "@/lib/pill-tone";
import { AssessmentFindingInspector } from "@/components/opportunities/assessment-finding-inspector";
import { useFindingSelection } from "@/components/opportunities/finding-selection";
import { CountChip, useRedTeam } from "@/components/opportunities/red-team-list";
import { RedTeamInspector } from "@/components/opportunities/red-team-inspector";
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
  activitySummary,
  agentLabel,
  agentRole,
  CANCEL_RUN,
  CANCEL_RUN_CONFIRM,
  CANCEL_RUN_DESCRIPTION,
  CANCEL_RUN_KEEP,
  CANCEL_RUN_TITLE,
  confidenceLabel,
  evidenceLabels,
  failureReason,
  findingKey,
  isAssessing,
  mergeFindings,
  NO_ASSESSMENT,
  NOTHING_TO_ASSESS,
  RED_TEAM_LABEL,
  RED_TEAM_ROLE,
  recommendationInfo,
  RUN_ASSESSMENT,
  runAlert,
  runStatusLabel,
  runStatusTone,
  severitySummary,
  severityTotals,
  skipNote,
  START_NEW_RUN,
  STILL_ASSESSING,
  taskCounters,
  taskElapsed,
  taskStatusLabel,
  WAITING_FOR_WORKER,
  type Assessment,
  type AssessmentAgent,
  type AssessmentRun,
  type AssessmentsView,
  type FindingRow,
  type Recommendation,
  type TaskStatus,
} from "@/lib/assessments";
import { hours } from "@/lib/estimates";
import { formatDateTime } from "@/lib/sources";
import { useOpportunityEvents } from "@/lib/opportunity-events";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import {
  findingCount,
  isReviewing,
  NO_REVIEW,
  NOTHING_TO_REVIEW,
  REVIEW_POLL_LIMIT_MS,
  REVIEW_POLL_MS,
  SEVERITIES,
  STILL_REVIEWING,
  type RedTeamReview,
  type RedTeamRun,
  type RedTeamView,
  type SeverityCounts,
} from "@/lib/red-team";
import { cn } from "@/lib/utils";

export const RETRY = "Retry";
const START_FAILED = "The assessment could not be started. Try again.";
const CANCEL_FAILED = "The run could not be cancelled. Try again.";
const NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can run an assessment.";
const ASSESSMENTS_NOT_LOADED =
  "The Specialist Assessments could not be loaded. Try again in a moment.";
const RED_TEAM_NOT_LOADED =
  "The Red Team Review could not be loaded. Try again in a moment.";
export const NO_FINDINGS = "No Findings.";
export const SHOW_EFFORT = "Show effort";
export const HIDE_EFFORT = "Hide effort";

/** Each agent's icon on its task card. */
const AGENT_ICONS: Record<AssessmentAgent, LucideIcon> = {
  engineering_agent: LayoutPanelLeftIcon,
  pm_agent: CalendarRangeIcon,
  security_agent: ShieldCheckIcon,
};

/** A recommendation: always an icon and a label, never colour alone. */
export function RecommendationPill({
  recommendation,
}: {
  recommendation: Recommendation;
}) {
  const known = recommendationInfo(recommendation);
  const Icon = known.icon;
  return (
    <Pill
      data-recommendation={known.value}
      tone={pillToneFor(known.tone)}
      icon={<Icon />}
      className="shrink-0"
    >
      {known.label}
    </Pill>
  );
}

/** The severity counts as icon-and-number pairs, most severe first. */
function SeverityCountsLine({ counts }: { counts: SeverityCounts }) {
  return (
    <p className="flex flex-wrap items-center gap-3 text-label">
      <span className="sr-only">{severitySummary(counts)}</span>
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

/** The columns of the Findings table, shared by its header and its rows (from `md`). */
const FINDING_COLUMNS =
  "md:grid-cols-[5.5rem_9rem_minmax(0,1fr)_9rem_6.5rem]";

/** Every agent's and the Red Team's Findings in one table, in the order given (ranked
 * critical to low): severity, type, the specific title, who raised it and the evidence counts.
 * Critical rows are tinted red. One Tab stop (roving tabindex); j/k (with single-key shortcuts
 * on) or the arrows move between rows; Enter, Space or a click opens the row, which is then
 * `aria-selected`. */
export function FindingsTable({
  rows,
  selectedKey = null,
  onOpen,
}: {
  rows: readonly FindingRow[];
  selectedKey?: string | null;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (row: FindingRow, viaKeyboard: boolean) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedKey, setFocusedKey] = useState<string | null>(null);
  const keys = rows.map(findingKey);
  const tabStopKey =
    [focusedKey, selectedKey].find((k) => k !== null && keys.includes(k)) ??
    keys[0];

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
    <Card className="gap-0 overflow-hidden p-0">
      <div
        aria-hidden="true"
        className={cn(
          "hidden gap-4 bg-surface-alt px-5 py-2.5 text-label text-muted-foreground md:grid",
          FINDING_COLUMNS,
        )}
      >
        <span>Severity</span>
        <span>Type</span>
        <span>Finding</span>
        <span>Raised by</span>
        <span className="text-right">Evidence</span>
      </div>
      <div
        ref={container}
        role="grid"
        aria-label="Findings"
        onKeyDown={onKeyDown}
        className="flex flex-col"
      >
        {rows.map((row) => {
          const key = findingKey(row);
          const selected = key === selectedKey;
          return (
            <div
              key={key}
              role="row"
              aria-selected={selected}
              data-severity-row={row.severity}
              className={cn(
                "border-t border-border first:border-t-0 md:first:border-t",
                row.severity === "critical" && "bg-blocker-tint",
                selected ? "bg-muted" : "hover:brightness-[.97]",
              )}
            >
              <div role="gridcell">
                <button
                  type="button"
                  data-finding-row=""
                  data-finding-id={key}
                  tabIndex={key === tabStopKey ? 0 : -1}
                  onFocus={() => setFocusedKey(key)}
                  // A keyboard-activated click has no pointer clicks (detail 0).
                  onClick={(event) => onOpen?.(row, event.detail === 0)}
                  className={cn(
                    "grid min-h-row w-full grid-cols-[5.5rem_minmax(0,1fr)] items-center gap-x-4 gap-y-1 px-5 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset",
                    FINDING_COLUMNS,
                  )}
                >
                  <SeverityPill severity={row.severity} />
                  <span className="truncate text-meta text-muted-foreground">
                    {row.type}
                  </span>
                  <span className="col-span-2 min-w-0 text-body-strong md:col-span-1">
                    {row.finding.title}
                  </span>
                  <span className="truncate text-body">{row.raisedBy}</span>
                  <span className="flex items-center gap-1 md:justify-end">
                    <CountChip count={row.requirements} kind="requirement" />
                    {row.lines !== null ? (
                      <CountChip count={row.lines} kind="line" />
                    ) : null}
                  </span>
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
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
            <td className="py-1 pr-3 text-meta text-muted-foreground">
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

/** The Requirement evidence chips of a result card. */
function EvidenceChips({
  items,
}: {
  items: readonly { id: string; label: string }[];
}) {
  if (items.length === 0) return null;
  return (
    <ul aria-label="Evidence" className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <li key={item.label}>
          <Chip>
            <QuoteIcon aria-hidden="true" className="size-3 shrink-0" />
            {item.label}
          </Chip>
        </li>
      ))}
    </ul>
  );
}

/** The frame of a result card: the name as its heading, then the rest. */
function ResultCard({
  name,
  badges,
  children,
}: {
  name: string;
  badges: ReactNode;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <Card role="article" aria-labelledby={headingId} className="gap-2.5 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h4 id={headingId} className="text-body-strong">
          {name}
        </h4>
        {badges}
      </div>
      {children}
    </Card>
  );
}

/** One agent's result card: its name, version, recommendation, confidence, the confidence
 * basis as its summary, up to three Requirement evidence chips and **Show effort**, which
 * reveals the per-Requirement effort table. */
export function AssessmentCard({ assessment }: { assessment: Assessment }) {
  const effortId = useId();
  const [showEffort, setShowEffort] = useState(false);
  return (
    <ResultCard
      name={agentLabel(assessment.agent)}
      badges={
        <>
          <span className="text-meta text-muted-foreground">
            v{assessment.version}
          </span>
          <RecommendationPill recommendation={assessment.recommendation} />
          <span className="text-meta text-muted-foreground">
            {confidenceLabel(assessment.confidence)}
          </span>
        </>
      }
    >
      <p className="text-body">{assessment.confidence_basis}</p>
      <EvidenceChips
        items={evidenceLabels(assessment.findings, assessment.effort)}
      />
      <div>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          aria-expanded={showEffort}
          aria-controls={effortId}
          aria-label={`${showEffort ? HIDE_EFFORT : SHOW_EFFORT}: ${agentLabel(assessment.agent)}`}
          onClick={() => setShowEffort((open) => !open)}
        >
          <ChevronDownIcon
            aria-hidden="true"
            className={cn(
              "transition-transform motion-reduce:transition-none",
              showEffort && "rotate-180",
            )}
          />
          {showEffort ? HIDE_EFFORT : SHOW_EFFORT}
        </Button>
      </div>
      <div id={effortId} hidden={!showEffort}>
        {showEffort ? <EffortTable assessment={assessment} /> : null}
      </div>
    </ResultCard>
  );
}

/** The Red Team's result card: its version, severity counts, Finding count and up to three
 * Requirement evidence chips. */
export function RedTeamResultCard({ review }: { review: RedTeamReview }) {
  return (
    <ResultCard
      name={RED_TEAM_LABEL}
      badges={
        <>
          <span className="text-meta text-muted-foreground">
            v{review.version}
          </span>
          <SeverityCountsLine counts={review.counts} />
        </>
      }
    >
      <p className="text-body">
        {findingCount(review.findings.length)}
        {review.estimate_version
          ? ` against Estimate v${review.estimate_version}`
          : ""}
      </p>
      <EvidenceChips items={evidenceLabels(review.findings)} />
    </ResultCard>
  );
}

const TASK_PILL_ICONS: Record<TaskStatus, { icon: LucideIcon; tone: string }> =
  {
    queued: { icon: ClockIcon, tone: "text-muted-foreground" },
    running: { icon: CircleDotIcon, tone: "text-agent" },
    succeeded: { icon: CircleCheckIcon, tone: "text-resolved" },
    failed: { icon: CircleAlertIcon, tone: "text-blocker" },
    skipped: { icon: CircleMinusIcon, tone: "text-muted-foreground" },
  };

/** A task's status: always an icon and a label, never colour alone (Queued neutral, Running
 * agent colour, Done green, Failed red, Skipped neutral). */
export function TaskStatusPill({ status }: { status: TaskStatus }) {
  const known = TASK_PILL_ICONS[status] ?? TASK_PILL_ICONS.queued;
  const Icon = known.icon;
  return (
    <Pill
      data-task-pill={status}
      tone={pillToneFor(known.tone)}
      icon={<Icon />}
      className="w-[5.5rem] shrink-0"
    >
      {taskStatusLabel(status)}
    </Pill>
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

/** A task's state bar, decorative (the pill carries the meaning) and never a percentage:
 * full green once done, an indeterminate indigo sweep while running (a still, pale full bar
 * under reduced motion or once polling has stalled), empty while queued or skipped, full red
 * once failed. */
function StateBar({ status, still }: { status: TaskStatus; still: boolean }) {
  return (
    <div
      aria-hidden="true"
      data-testid="state-bar"
      data-state={status}
      className="relative h-1.5 w-full overflow-hidden rounded-full bg-surface-alt"
    >
      {status === "succeeded" ? (
        <div className="h-full w-full rounded-full bg-resolved" />
      ) : status === "failed" ? (
        <div className="h-full w-full rounded-full bg-blocker" />
      ) : status === "running" ? (
        still ? (
          <div className="h-full w-full rounded-full bg-primary opacity-40" />
        ) : (
          <div className="h-full w-full animate-in duration-[1.6s] ease-in-out slide-in-from-left-full repeat-infinite motion-reduce:animate-none">
            <div className="ml-[60%] h-full w-2/5 rounded-full bg-primary motion-reduce:ml-0 motion-reduce:w-full motion-reduce:opacity-40" />
          </div>
        )
      ) : null}
    </div>
  );
}

/** The card border (and tint) for a task's status. */
function taskCardTone(status: TaskStatus): string {
  switch (status) {
    case "succeeded":
      return "border-resolved";
    case "running":
      return "border-primary";
    case "failed":
      return "border-blocker bg-blocker-tint";
    default:
      return "";
  }
}

/** One task card of the Agent tasks grid. */
function TaskCard({
  status,
  icon: Icon,
  name,
  role,
  stalled,
  elapsed,
  note,
  action,
}: {
  status: TaskStatus;
  icon: LucideIcon;
  name: string;
  role: string;
  stalled: boolean;
  /** Undefined when the task has no timestamps (the Red Team's). */
  elapsed?: string;
  note: string | null;
  action: ReactNode;
}) {
  const failed = status === "failed";
  const runningDot = status === "running" && !stalled;
  const StatusIcon = (TASK_PILL_ICONS[status] ?? TASK_PILL_ICONS.queued).icon;
  return (
    <Card className={cn("h-full gap-3 p-4", taskCardTone(status))}>
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-tint text-primary-text"
        >
          <Icon className="size-5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col">
          <span data-part="name" className="truncate text-body-strong">
            {name}
          </span>
          <span className="text-meta text-muted-foreground">{role}</span>
        </div>
        <span aria-hidden="true" className="flex shrink-0">
          {runningDot ? (
            <LoaderCircleIcon
              data-testid="running-dot"
              className="size-5 text-agent"
            />
          ) : (
            <StatusIcon
              className={cn(
                "size-5",
                (TASK_PILL_ICONS[status] ?? TASK_PILL_ICONS.queued).tone,
              )}
            />
          )}
        </span>
      </div>
      <StateBar status={status} still={stalled} />
      <div className="flex items-center justify-between gap-2 text-label">
        <TaskStatusPill status={status} />
        {elapsed !== undefined ? (
          <span
            data-testid="elapsed"
            suppressHydrationWarning
            className="text-numeric text-muted-foreground"
          >
            {elapsed}
          </span>
        ) : null}
      </div>
      {note ? (
        <p
          data-part="note"
          className={cn(
            "text-label",
            failed ? "text-blocker" : "text-muted-foreground",
          )}
        >
          {note}
        </p>
      ) : null}
      {action ? <div className="flex gap-2">{action}</div> : null}
    </Card>
  );
}

/** The Red Team run as a task of the Agent tasks grid. */
export type RedTeamTask = {
  run: RedTeamRun;
  /** The caller may start a review (Retry). */
  canRetry?: boolean;
  /** A Retry is in flight. */
  busy?: boolean;
  /** Polling has stopped while still reviewing. */
  stalled?: boolean;
  onRetry?: () => void;
};

/** The Agent tasks grid: one card per task of the latest run (in any status), then the Red
 * Team's run. Each card has the agent's icon, name and role, a status icon, a state bar, the
 * status pill, the elapsed time in tabular figures (`m:ss`, ticking each second while it
 * runs, its final duration once done or failed, blank before it starts; none for the Red
 * Team, whose run has no timestamps), a note and **Retry**. Queued tasks say "Waiting for the
 * worker"; failed tasks give the reason and **Retry** for those who may start one (never in
 * a cancelled run); a task skipped because its Agent is disabled says "Agent disabled —
 * assess manually". Elapsed time comes from the task's timestamps and the browser's clock, so
 * it ticks without a fetch. */
export function AgentRunPanel({
  run,
  redTeam = null,
  canStart = false,
  busy = false,
  stalled = false,
  onRetry,
}: {
  run: AssessmentRun | null;
  redTeam?: RedTeamTask | null;
  canStart?: boolean;
  busy?: boolean;
  stalled?: boolean;
  onRetry?: (agent: AssessmentAgent) => void;
}) {
  const assessing = isAssessing(run);
  const now = useNow(assessing && !stalled);
  const redStatus = redTeam?.run.status;
  const redStalled = !!redTeam?.stalled && isReviewing(redTeam.run);
  return (
    <ul
      aria-label="Agent progress"
      className="grid w-full grid-cols-1 gap-4 md:grid-cols-3"
    >
      {(run?.tasks ?? []).map((task) => {
        const failed = task.status === "failed";
        const note =
          task.status === "queued"
            ? WAITING_FOR_WORKER
            : failed
              ? failureReason(task.error_code)
              : skipNote(task);
        return (
          <li key={task.agent} data-task-status={task.status}>
            <TaskCard
              status={task.status}
              icon={AGENT_ICONS[task.agent] ?? SparklesIcon}
              name={agentLabel(task.agent)}
              role={agentRole(task.agent)}
              stalled={stalled}
              elapsed={taskElapsed(task, now)}
              note={note}
              action={
                failed &&
                canStart &&
                !assessing &&
                run?.status !== "cancelled" ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    disabled={busy}
                    aria-label={`${RETRY} ${agentLabel(task.agent)}`}
                    onClick={() => onRetry?.(task.agent)}
                  >
                    {RETRY}
                  </Button>
                ) : null
              }
            />
          </li>
        );
      })}
      {redTeam && redStatus ? (
        <li key="red_team" data-task-status={redStatus}>
          <TaskCard
            status={redStatus}
            icon={SwordsIcon}
            name={RED_TEAM_LABEL}
            role={RED_TEAM_ROLE}
            stalled={redStalled}
            note={
              redStalled
                ? STILL_REVIEWING
                : redStatus === "queued"
                  ? WAITING_FOR_WORKER
                  : redStatus === "failed"
                    ? failureReason(redTeam.run.error_code)
                    : null
            }
            action={
              redStatus === "failed" && redTeam.canRetry ? (
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  disabled={redTeam.busy}
                  aria-label={`${RETRY} ${RED_TEAM_LABEL}`}
                  onClick={() => redTeam.onRetry?.()}
                >
                  {RETRY}
                </Button>
              ) : null
            }
          />
        </li>
      ) : null}
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
        render={<Button type="button" variant="outline" />}
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

/** The tone of a counter's number. */
const COUNTER_TONES: Record<string, string> = {
  complete: "text-primary-text",
  failed: "text-blocker",
  running: "text-agent",
};

/** The run header: a card with the run's status, when it started, its counters (over the
 * run's tasks plus `extraStatuses`, e.g. the Red Team's) and, for those who may start one,
 * **Cancel run** (while queued or running) over **Start new run**; then an alert when the run
 * stopped early. Before any run, only **Run assessment** (for those who may start one).
 * "Still assessing — reload to check." once polling has stopped. */
export function SpecialistAssessmentsHeader({
  run,
  extraStatuses = [],
  canStart = false,
  busy = false,
  message = null,
  stalled = false,
  focusStartRequest = 0,
  onStart,
  onCancel,
}: {
  run: AssessmentRun | null;
  /** Statuses of other tasks the counters cover (the Red Team run's). */
  extraStatuses?: readonly TaskStatus[];
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
  onCancel?: () => void;
}) {
  const assessing = isAssessing(run);
  const startRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (focusStartRequest > 0) startRef.current?.focus();
  }, [focusStartRequest]);
  const start = canStart ? (
    <Button
      ref={startRef}
      type="button"
      disabled={busy || assessing}
      onClick={() => onStart?.()}
    >
      {run ? START_NEW_RUN : RUN_ASSESSMENT}
    </Button>
  ) : null;
  const statuses = [...(run?.tasks.map((t) => t.status) ?? []), ...extraStatuses];
  const alert = run ? runAlert(run) : null;
  return (
    <div className="flex flex-col items-stretch gap-3">
      {run ? (
        <Card
          className="flex-row flex-wrap items-center gap-x-6 gap-y-4 p-6"
          data-testid="run-header"
        >
          <span
            aria-hidden="true"
            className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground"
          >
            <SparklesIcon className="size-6" />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <p className="text-section">Assessments</p>
              <Pill
                data-status={run.status}
                tone={pillToneFor(runStatusTone(run.status))}
              >
                {runStatusLabel(run)}
              </Pill>
            </div>
            <p className="text-meta text-muted-foreground">
              Started {formatDateTime(run.queued_at || run.created_at)}
            </p>
          </div>
          {statuses.length > 0 ? (
            <ul
              aria-label="Task counters"
              className="flex flex-wrap gap-7 text-center"
            >
              {taskCounters(statuses).map((counter) => (
                <li
                  key={counter.key}
                  data-counter={counter.key}
                  className="flex flex-col"
                >
                  <span
                    className={cn(
                      "text-title [font-variant-numeric:tabular-nums]",
                      COUNTER_TONES[counter.key],
                    )}
                  >
                    {counter.value}
                  </span>
                  <span className="text-meta text-muted-foreground">
                    {" "}
                    {counter.label}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {canStart ? (
            <div className="flex flex-col gap-2">
              {assessing ? (
                <CancelRunButton busy={busy} onConfirm={onCancel} />
              ) : null}
              {start}
            </div>
          ) : null}
        </Card>
      ) : start ? (
        <div className="flex">{start}</div>
      ) : null}
      {alert ? (
        <div
          data-testid="run-alert"
          className="flex items-start gap-3 rounded-lg bg-gap-tint px-4 py-3 text-gap"
        >
          <TriangleAlertIcon
            aria-hidden="true"
            className="mt-0.5 size-4 shrink-0"
          />
          <div className="flex flex-col">
            <p className="text-body-strong">{alert.title}</p>
            <p className="text-body text-foreground">{alert.detail}</p>
          </div>
        </div>
      ) : null}
      {assessing && stalled ? (
        <p className="text-label text-muted-foreground">{STILL_ASSESSING}</p>
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

/** A subsection with its heading and, on the right, a summary. */
function Subsection({
  title,
  summary,
  children,
}: {
  title: string;
  summary?: ReactNode;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className="flex-1 text-section">
          {title}
        </h3>
        {summary}
      </div>
      {children}
    </section>
  );
}

/** The Assessments tab body: the run header and alert, the Agent tasks (each specialist task
 * of the latest run, then the Red Team's run), Results so far (one card per agent with an
 * Assessment, then the Red Team review) and one Findings table across all of them; the
 * selected Finding's inspector goes in the right pane (opened if closed). It follows the
 * Opportunity's event stream (Story 5.2) and is re-read as each task starts and ends, a run
 * is queued or ends, and whenever the stream (re)connects. While the stream is not connected
 * and a run is queued or running, it falls back to re-reading every 2 s: paused while the tab
 * is hidden, and stopped after 15 minutes. The Red Team is re-read the same way while it
 * reviews (`useRedTeam`). Inside a `FindingSelectionProvider` its selection is shared with
 * the tab's other sections. Read-only for sales representatives (no Run assessment, Retry or
 * Cancel run). `redTeam` null says the Red Team could not be loaded; left out, the Red Team
 * is not shown. */
export function SpecialistAssessmentsSection({
  opportunityId,
  initial,
  redTeam: redTeamInitial,
  assessmentsFailed = false,
}: {
  opportunityId: string;
  initial: AssessmentsView;
  redTeam?: RedTeamView | null;
  /** The Assessments read failed (`initial` is an empty view): say so instead of the
   * no-Assessment text. */
  assessmentsFailed?: boolean;
}) {
  const announce = useAnnounce();
  const router = useRouter();
  /** The router for the polling effect, kept out of its dependencies. */
  const routerRef = useRef(router);
  useEffect(() => {
    routerRef.current = router;
  });
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [view, setView] = useState<AssessmentsView>(initial);
  const redTeam = useRedTeam(opportunityId, redTeamInitial ?? null);
  const [selectedKey, setSelectedKey] = useFindingSelection("assessments");
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
  /** Whether the shown run is in progress, for re-reads that land later. */
  const assessingRef = useRef(assessing);
  useEffect(() => {
    assessingRef.current = assessing;
  });

  /** Numbers each re-read; the newest one applied, so an older answer landing later is
   * dropped (stream events can start re-reads that overlap). */
  const readSeq = useRef(0);
  const appliedSeq = useRef(0);

  /** Re-read the section; a read that started before a local change, or before a re-read
   * already applied, is dropped. When the
   * run it showed in progress has finished, the tab's server reads (e.g. the Effort
   * comparison) re-render with its results and the outcome is announced. */
  const reload = useRef(async (): Promise<boolean> => false);
  useEffect(() => {
    reload.current = async () => {
      const startedAt = mutation.current;
      readSeq.current += 1;
      const seq = readSeq.current;
      const result = await loadAssessments(opportunityId);
      if (result.kind !== "ok" || mutation.current !== startedAt) return false;
      if (seq < appliedSeq.current) return false;
      appliedSeq.current = seq;
      const wasAssessing = assessingRef.current;
      setView(result.assessments);
      const { run, assessments } = result.assessments;
      if (wasAssessing && run && !isAssessing(run)) {
        routerRef.current.refresh();
        announce(
          run.status === "succeeded" &&
            assessments.every((s) => s.assessment === null)
            ? NOTHING_TO_ASSESS
            : runStatusLabel(run),
        );
      }
      return true;
    };
  });

  const live = useOpportunityEvents(opportunityId, () => {
    reload.current().catch(() => {
      // A failed re-read is retried on the next event (or poll).
    });
  });

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setView(initial);
    setStalled(false);
  }

  const review = redTeam.view?.review ?? null;
  const rows = mergeFindings(view.assessments, review);
  const selected =
    selectedKey === null
      ? null
      : (rows.find((row) => findingKey(row) === selectedKey) ?? null);

  // The pane's content unmounts on close: reopening it must not take focus again.
  const [paneWasOpen, setPaneWasOpen] = useState(rightPaneOpen);
  if (paneWasOpen !== rightPaneOpen) {
    setPaneWasOpen(rightPaneOpen);
    if (!rightPaneOpen) setFocusRequest(0);
  }

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const key = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (
      key &&
      (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)
    ) {
      document
        .querySelector<HTMLElement>(`[data-finding-id="${key}"]`)
        ?.focus();
    }
  }, [rightPaneOpen]);

  function open(row: FindingRow, viaKeyboard: boolean) {
    const key = findingKey(row);
    setSelectedKey(key);
    returnFocusTo.current = viaKeyboard ? key : null;
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
    const elapsed = Date.now() - assessingSince.current;
    if (elapsed >= REVIEW_POLL_LIMIT_MS) {
      // Past the limit (e.g. hidden through it): say so instead of pulsing forever.
      setStalled(true);
      return;
    }
    if (live) {
      // The stream re-reads on events, but a lost run sends none: keep the same limit.
      const limit = setTimeout(
        () => setStalled(true),
        REVIEW_POLL_LIMIT_MS - elapsed,
      );
      return () => clearTimeout(limit);
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        await reload.current();
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
  }, [assessing, visible, live, pollTick]);

  const sectionRef = useRef<HTMLDivElement>(null);

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
  const redRun = redTeam.view?.run ?? null;
  const results = view.assessments.flatMap((slot) =>
    slot.assessment ? [slot.assessment] : [],
  );
  const anyResult = results.length > 0 || review !== null;
  const taskStatuses: TaskStatus[] = [
    ...(view.run?.tasks.map((t) => t.status) ?? []),
    ...(redRun ? [redRun.status] : []),
  ];
  const activity = activitySummary(taskStatuses);
  const emptyNotes = [
    results.length === 0 && view.run?.status === "succeeded"
      ? NOTHING_TO_ASSESS
      : null,
    assessmentsFailed
      ? ASSESSMENTS_NOT_LOADED
      : results.length === 0 && !view.run
        ? NO_ASSESSMENT
        : null,
    redTeam.view && !review && redRun?.status === "succeeded"
      ? NOTHING_TO_REVIEW
      : null,
    redTeam.view && !review && !redRun ? NO_REVIEW : null,
  ].filter((note): note is string => note !== null);
  return (
    <div ref={sectionRef} className="flex flex-col gap-6">
      <SpecialistAssessmentsHeader
        run={view.run}
        extraStatuses={redRun ? [redRun.status] : []}
        canStart={view.can_start}
        busy={busy}
        message={message}
        stalled={stalled}
        onStart={() => void act(() => startAssessmentRun(opportunityId))}
        focusStartRequest={focusStartRequest}
        onCancel={() =>
          void act(
            () => cancelAssessmentRun(opportunityId, runId),
            CANCEL_FAILED,
            true,
          )
        }
      />
      {view.run || redRun ? (
        <Subsection
          title="Agent tasks"
          summary={
            activity ? (
              <span className="inline-flex items-center gap-1.5 text-meta text-muted-foreground">
                {(assessing && stalled) ||
                (redTeam.stalled && isReviewing(redRun)) ? null : (
                  <LoaderCircleIcon
                    aria-hidden="true"
                    data-testid="activity-icon"
                    className="size-3.5"
                  />
                )}
                {activity}
              </span>
            ) : null
          }
        >
          <AgentRunPanel
            run={view.run}
            canStart={view.can_start}
            busy={busy}
            stalled={assessing && stalled}
            onRetry={(agent) =>
              void act(() => retryAssessmentTask(opportunityId, runId, agent))
            }
            redTeam={
              redRun
                ? {
                    run: redRun,
                    canRetry: redTeam.view?.can_start ?? false,
                    busy: redTeam.busy,
                    stalled: redTeam.stalled,
                    onRetry: redTeam.retry,
                  }
                : null
            }
          />
          {redTeam.message ? (
            <span className="text-meta text-destructive">
              {redTeam.message}
            </span>
          ) : null}
        </Subsection>
      ) : null}
      {emptyNotes.map((note) => (
        <p key={note} className="text-muted-foreground">
          {note}
        </p>
      ))}
      {redTeamInitial === null ? <p>{RED_TEAM_NOT_LOADED}</p> : null}
      {anyResult ? (
        <Subsection title="Results so far">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {results.map((assessment) => (
              <AssessmentCard key={assessment.agent} assessment={assessment} />
            ))}
            {review ? <RedTeamResultCard review={review} /> : null}
          </div>
        </Subsection>
      ) : null}
      {anyResult ? (
        <Subsection
          title="Findings"
          summary={
            rows.length > 0 ? (
              <span className="text-meta text-muted-foreground">
                {severitySummary(severityTotals(rows))}
              </span>
            ) : null
          }
        >
          {rows.length > 0 ? (
            <FindingsTable
              rows={rows}
              selectedKey={selected ? findingKey(selected) : null}
              onOpen={open}
            />
          ) : (
            <p className="text-muted-foreground">{NO_FINDINGS}</p>
          )}
        </Subsection>
      ) : null}
      {selected ? (
        <RightPaneContent>
          {selected.source === "specialist" ? (
            <AssessmentFindingInspector
              key={findingKey(selected)}
              finding={selected.finding}
              agent={selected.agent}
              focusRequest={focusRequest}
            />
          ) : (
            <RedTeamInspector
              key={findingKey(selected)}
              finding={selected.finding}
              focusRequest={focusRequest}
            />
          )}
        </RightPaneContent>
      ) : null}
    </div>
  );
}
