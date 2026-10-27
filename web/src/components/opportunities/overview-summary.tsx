import {
  ArrowUpIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  ClipboardListIcon,
  ClockIcon,
  OctagonAlertIcon,
  QuoteIcon,
  SparklesIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { KpiTile } from "@/components/ui/kpi-tile";
import { Chip } from "@/components/ui/chip";
import { Pill, type PillTone } from "@/components/ui/pill";
import { ActorTile } from "@/components/opportunities/actor-tile";
import { ConflictsKpiPill, SubmissionPipeline } from "@/components/opportunities/overview-pipeline";
import { SubmissionBlockersCard } from "@/components/opportunities/submission";
import {
  RecommendationPill,
  TaskStatusPill,
  WaitingForYouPill,
} from "@/components/opportunities/specialist-assessments";
import {
  agentLabel,
  confidenceLabel,
  decisionSentence,
  evidenceLabels,
  failureReason,
  isWaiting,
  openDecision,
  skipNote,
  type AssessmentRun,
  type AssessmentsView,
  type Confidence,
} from "@/lib/assessments";
import { hours, type EstimateView } from "@/lib/estimates";
import {
  assessmentsStarted,
  ATTENTION_INCOMPLETE,
  attentionIncomplete,
  attentionItems,
  awaitingLabel,
  conflictCounts,
  couldNotLoad,
  cutAttention,
  estimateKpiLabel,
  estimatePending,
  gapCounts,
  isStepStatus,
  itemCountLabel,
  latestDecision,
  moreLabel,
  NOT_RUN,
  NOTHING_NEEDS_ATTENTION,
  requirementCounts,
  roleHoursLabel,
  sourceRunLabel,
  tasksCompleteLabel,
  type AttentionKind,
  type OverviewReads,
} from "@/lib/overview";
import { formatDateTime } from "@/lib/sources";
import { absoluteTime, eventLabel, NO_EVENTS, relativeTime, type TraceEvent } from "@/lib/trace";
import { cn } from "@/lib/utils";
import { tabHref } from "@/lib/workspace";

/** One read's outcome: its data, or `null` when it failed. */
export type OverviewData = OverviewReads;

const RECENT_ACTIVITY_LIMIT = 5;

const linkClass =
  "rounded-sm text-control text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary";

const outlineLink = `${buttonVariants({ variant: "outline", size: "sm" })} text-control`;

const Muted = ({ children }: { children: ReactNode }) => (
  <p className="text-muted-foreground">{children}</p>
);

/** A summary card: `ui/card` with a 16px-semibold header row over a bottom border. */
function SummaryCard({
  id,
  title,
  extra,
  children,
  footer,
}: {
  id: string;
  title: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Card role="region" aria-labelledby={id} className="min-w-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-[18px]">
        <h3 id={id} className="min-w-0 flex-1 text-section">
          {title}
        </h3>
        {extra}
      </div>
      {children}
      {footer ? <div className="border-t border-border px-5 py-3">{footer}</div> : null}
    </Card>
  );
}

// --- KPI row ---------------------------------------------------------------------------------

const KpiNote = ({ children }: { children: ReactNode }) => (
  <span className="mt-2 text-meta text-muted-foreground">{children}</span>
);

function RequirementsKpi({ id, data }: { id: string; data: OverviewData }) {
  const href = tabHref(id, "requirements");
  const label = "Requirements confirmed";
  if (data.requirements === null)
    return (
      <KpiTile label={label} href={href} value={NOT_RUN}>
        <KpiNote>{couldNotLoad("Requirements")}</KpiNote>
      </KpiTile>
    );
  const counts = requirementCounts(data.requirements);
  if (counts === null || isStepStatus(counts))
    return (
      <KpiTile label={label} href={href} value={NOT_RUN}>
        {counts ? <KpiNote>{counts.status}</KpiNote> : null}
      </KpiTile>
    );
  const pct = counts.active === 0 ? 0 : Math.round((counts.confirmed / counts.active) * 100);
  return (
    <KpiTile label={label} href={href} value={counts.confirmed} unit={` of ${counts.active}`}>
      <span aria-hidden="true" className="mt-2 block h-1.5 rounded-full bg-surface-alt">
        <span className="block h-1.5 rounded-full bg-resolved" style={{ width: `${pct}%` }} />
      </span>
      <KpiNote>{awaitingLabel(counts.unconfirmed)}</KpiNote>
    </KpiTile>
  );
}

function GapsKpi({ id, data }: { id: string; data: OverviewData }) {
  const href = tabHref(id, "gaps");
  const label = "Open Gaps";
  if (data.gaps === null)
    return (
      <KpiTile label={label} href={href} value={NOT_RUN}>
        <KpiNote>{couldNotLoad("Open Gaps")}</KpiNote>
      </KpiTile>
    );
  const counts = gapCounts(data.gaps);
  if (counts === null || isStepStatus(counts))
    return (
      <KpiTile label={label} href={href} value={NOT_RUN}>
        {counts ? <KpiNote>{counts.status}</KpiNote> : null}
      </KpiTile>
    );
  return (
    <KpiTile label={label} href={href} value={counts.open}>
      {counts.high > 0 || counts.medium > 0 ? (
        <span className="mt-2 flex flex-wrap gap-1.5">
          {counts.high > 0 ? (
            <Pill tone="blocker" icon={<CircleAlertIcon />}>
              {counts.high} High
            </Pill>
          ) : null}
          {counts.medium > 0 ? (
            <Pill tone="gap" icon={<TriangleAlertIcon />}>
              {counts.medium} Medium
            </Pill>
          ) : null}
        </span>
      ) : null}
      <KpiNote>{counts.low} Low</KpiNote>
    </KpiTile>
  );
}

function ConflictsKpi({ id, data }: { id: string; data: OverviewData }) {
  const href = tabHref(id, "conflicts");
  const label = "Open Conflicts";
  if (!data.conflicts)
    return (
      <KpiTile label={label} href={href} value={NOT_RUN}>
        <KpiNote>{couldNotLoad("The Conflicts")}</KpiNote>
      </KpiTile>
    );
  if (data.conflicts.conflicts.length === 0 && !assessmentsStarted(data.assessments))
    return <KpiTile label={label} href={href} value={NOT_RUN} />;
  const { unresolved, escalated } = conflictCounts(data.conflicts);
  return (
    <KpiTile label={label} href={href} value={unresolved}>
      {unresolved > 0 ? <ConflictsKpiPill fallback={data.blockers} /> : null}
      {escalated > 0 ? <KpiNote>{escalated} escalated</KpiNote> : null}
    </KpiTile>
  );
}

function EstimateKpi({ id, estimate }: { id: string; estimate: EstimateView | null }) {
  const href = tabHref(id, "estimate");
  const version = estimate?.version ?? null;
  const label = estimateKpiLabel(version);
  if (estimate === null)
    return (
      <KpiTile label={label} href={href} value={NOT_RUN}>
        <KpiNote>{couldNotLoad("The Estimate")}</KpiNote>
      </KpiTile>
    );
  if (version === null)
    return (
      <KpiTile label={label} href={href} value={NOT_RUN}>
        <KpiNote>{estimatePending(estimate)}</KpiNote>
      </KpiTile>
    );
  return (
    <KpiTile label={label} href={href} value={hours(version.totals.total_hours)} unit=" h">
      <KpiNote>{roleHoursLabel(version.totals.role_hours)}</KpiNote>
      {version.source_run != null ? (
        <span className="text-meta text-muted-foreground">{sourceRunLabel(version.source_run)}</span>
      ) : null}
    </KpiTile>
  );
}

function KpiRow({ id, data }: { id: string; data: OverviewData }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <RequirementsKpi id={id} data={data} />
      <GapsKpi id={id} data={data} />
      <ConflictsKpi id={id} data={data} />
      <EstimateKpi id={id} estimate={data.estimate} />
    </div>
  );
}

// --- Needs you -------------------------------------------------------------------------------

/** Each kind's icon, state line and action. Blocker red only for critical; amber for the rest. */
const ATTENTION_DISPLAY: Record<
  AttentionKind,
  { state: string; icon: LucideIcon; tone: string; action: string }
> = {
  "critical-finding": {
    state: "Critical",
    icon: OctagonAlertIcon,
    tone: "text-blocker",
    action: "Review",
  },
  "escalated-conflict": {
    state: "Escalated",
    icon: ArrowUpIcon,
    tone: "text-gap",
    action: "Resolve",
  },
  "waiting-run": {
    state: "Waiting for you",
    icon: ClockIcon,
    tone: "text-gap",
    action: "Resolve",
  },
  "high-finding": { state: "High", icon: TriangleAlertIcon, tone: "text-gap", action: "Review" },
  gap: { state: "High impact", icon: CircleAlertIcon, tone: "text-gap", action: "Resolve" },
  assumption: { state: "Not accepted", icon: ClipboardListIcon, tone: "text-gap", action: "Open" },
};

/** Needs you: up to 8 rows, most severe first, each an icon, its title, a state line and a
 * link to its tab. Read-only; it blocks nothing. */
function NeedsYou({ id, data }: { id: string; data: OverviewData }) {
  const items = attentionItems(data);
  const { shown, more, moreTab } = cutAttention(items);
  const incomplete = attentionIncomplete(data);
  return (
    <SummaryCard
      id="overview-attention"
      title="Needs you"
      extra={items.length > 0 ? <Pill tone="gap">{itemCountLabel(items.length)}</Pill> : null}
      footer={
        <p className="text-control text-muted-foreground">
          In your queue <b className="text-numeric text-foreground">{items.length}</b>
        </p>
      }
    >
      {shown.length > 0 ? (
        <ul className="flex flex-col">
          {shown.map((item) => {
            const display = ATTENTION_DISPLAY[item.kind];
            const Icon = display.icon;
            return (
              <li
                key={item.key}
                data-kind={item.kind}
                className={cn(
                  "flex items-start gap-3 border-t border-border px-5 py-3 first:border-t-0",
                  item.kind === "critical-finding" && "bg-blocker-tint",
                )}
              >
                <Icon aria-hidden="true" className={cn("mt-0.5 size-4.5 shrink-0", display.tone)} />
                <div className="min-w-0 flex-1">
                  <div title={item.label} className="truncate text-body-strong">
                    {item.label}
                  </div>
                  <div className={cn("text-label", display.tone)}>{display.state}</div>
                </div>
                <Link
                  href={tabHref(id, item.tab)}
                  aria-label={`${display.action} ${item.label}`}
                  className={outlineLink}
                >
                  {display.action}
                </Link>
              </li>
            );
          })}
        </ul>
      ) : null}
      {shown.length === 0 && !incomplete ? (
        <div className="px-5 py-4">
          <Muted>{NOTHING_NEEDS_ATTENTION}</Muted>
        </div>
      ) : null}
      {more > 0 || incomplete ? (
        <div className="flex flex-col gap-1 border-t border-border px-5 py-3">
          {more > 0 && moreTab ? (
            <Link href={tabHref(id, moreTab)} className={cn(linkClass, "self-start")}>
              {moreLabel(more)}
            </Link>
          ) : more > 0 ? (
            <p className="text-control text-muted-foreground">{moreLabel(more)}</p>
          ) : null}
          {incomplete ? <Muted>{ATTENTION_INCOMPLETE}</Muted> : null}
        </div>
      ) : null}
    </SummaryCard>
  );
}

// --- Recent activity -------------------------------------------------------------------------

/** The five newest trace events: who (an initials tile), what in plain words, and when. */
function RecentActivity({ id, trace }: { id: string; trace: TraceEvent[] | null }) {
  const items = trace?.slice(0, RECENT_ACTIVITY_LIMIT) ?? [];
  return (
    <SummaryCard
      id="overview-activity"
      title="Recent activity"
      extra={
        <Link href={tabHref(id, "trace")} className={linkClass}>
          Open Trace
        </Link>
      }
    >
      <div className="px-5 pt-3 pb-4">
        {trace === null ? (
          <p>{couldNotLoad("The recent activity")}</p>
        ) : items.length === 0 ? (
          <Muted>{NO_EVENTS}</Muted>
        ) : (
          <ul className="flex flex-col">
            {items.map((item) => (
              <li key={item.id} data-actor-type={item.actor.type} className="flex gap-3 py-2.5">
                <ActorTile actor={item.actor} />
                <div className="min-w-0 flex-1">
                  <div className="text-control font-normal">{eventLabel(item.event_type)}</div>
                  <div className="text-meta text-muted-foreground">
                    {item.actor.name} ·{" "}
                    <time
                      dateTime={item.occurred_at}
                      title={absoluteTime(item.occurred_at)}
                      className="text-numeric"
                    >
                      {relativeTime(item.occurred_at)}
                    </time>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </SummaryCard>
  );
}

// --- Latest agent decision -------------------------------------------------------------------

const CONFIDENCE_DISPLAY: Record<Confidence, { tone: PillTone; icon: LucideIcon }> = {
  high: { tone: "resolved", icon: CircleCheckIcon },
  medium: { tone: "neutral", icon: CircleCheckIcon },
  low: { tone: "gap", icon: TriangleAlertIcon },
};

/** The newest specialist Assessment: its most severe Finding, the reasoning, the evidence, the
 * recommendation and the confidence. Hidden when there is no Assessment. */
function LatestDecision({ id, assessments }: { id: string; assessments: AssessmentsView | null }) {
  const latest = latestDecision(assessments);
  if (latest === null) return null;
  const { assessment, finding } = latest;
  const reasons = [finding?.detail, assessment.confidence_basis].filter(
    (r): r is string => !!r && r.trim() !== "",
  );
  const evidence = evidenceLabels(assessment.findings, assessment.effort);
  const confidence = CONFIDENCE_DISPLAY[assessment.confidence] ?? CONFIDENCE_DISPLAY.medium;
  const ConfidenceIcon = confidence.icon;
  return (
    <SummaryCard
      id="overview-decision"
      title="Latest agent decision"
      extra={
        <Pill tone="agent" icon={<SparklesIcon />}>
          {agentLabel(assessment.agent)}
        </Pill>
      }
    >
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3.5 border-border p-5 max-lg:border-b lg:border-r">
          <p className="flex items-center gap-3 rounded-[10px] border border-primary bg-primary-tint px-4 py-3.5 text-section text-primary-text">
            <SparklesIcon aria-hidden="true" className="size-5 shrink-0" />
            {finding ? finding.title : "No Findings."}
          </p>
          {reasons.length > 0 ? (
            <>
              <h4 className="text-eyebrow text-muted-foreground uppercase">Reasoning</h4>
              <ul className="flex flex-col gap-2">
                {reasons.map((reason, i) => (
                  <li key={i} className="flex items-start gap-2.5">
                    <CircleCheckIcon
                      aria-hidden="true"
                      className="mt-0.5 size-4 shrink-0 text-resolved"
                    />
                    <span className="min-w-0 flex-1">{reason}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {evidence.length > 0 ? (
            <ul aria-label="Evidence" className="flex flex-wrap gap-1.5">
              {evidence.map((e) => (
                <li key={e.id}>
                  <Chip className="border-transparent bg-primary-tint">
                    <QuoteIcon aria-hidden="true" className="size-3" />
                    {e.label}
                  </Chip>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="flex flex-col gap-3.5 p-5">
          <div className="flex flex-wrap gap-2">
            <RecommendationPill recommendation={assessment.recommendation} />
            <Pill tone={confidence.tone} icon={<ConfidenceIcon />}>
              {confidenceLabel(assessment.confidence)}
            </Pill>
          </div>
          <div className="flex-1" />
          <Link href={tabHref(id, "assessments")} className={cn(outlineLink, "self-start")}>
            Open Assessments
          </Link>
        </div>
      </div>
    </SummaryCard>
  );
}

// --- Agent run -------------------------------------------------------------------------------

function taskNote(task: AssessmentRun["tasks"][number]): string | null {
  return task.status === "failed" ? failureReason(task.error_code) : skipNote(task);
}

/** The latest Assessment run: when it started, how many tasks are done, and a compact card per
 * task (a task the run waits on shows **Waiting for you** and why, Story 5.5). Shown only when
 * a run exists; read-only (no Cancel or Resolve here: Needs you links to the tab). */
function AgentRun({ id, assessments }: { id: string; assessments: AssessmentsView | null }) {
  const run = assessments?.run ?? null;
  if (run === null) return null;
  const done = run.tasks.filter((t) => t.status === "succeeded").length;
  return (
    <SummaryCard
      id="overview-run"
      title="Agent run"
      extra={
        <>
          <span className="min-w-0 flex-1 text-control font-normal text-muted-foreground">
            Assessments · started{" "}
            <time dateTime={run.created_at} className="text-numeric">
              {formatDateTime(run.created_at)}
            </time>{" "}
            · {tasksCompleteLabel(done, run.tasks.length)}
          </span>
          <Link href={tabHref(id, "assessments")} className={outlineLink}>
            Open Assessments
          </Link>
        </>
      }
    >
      {run.tasks.length > 0 ? (
        <ul aria-label="Agent tasks" className="grid grid-cols-1 gap-3 p-5 lg:grid-cols-3">
          {run.tasks.map((task) => {
            const decision = isWaiting(run) ? openDecision(run, task.agent) : null;
            const note = decision ? decisionSentence(decision) : taskNote(task);
            return (
              <li
                key={task.agent}
                data-task-status={task.status}
                className={cn(
                  "flex flex-col gap-2.5 rounded-[10px] border border-border p-3.5",
                  task.status === "failed" && "bg-blocker-tint",
                )}
              >
                <div className="flex items-center gap-2.5">
                  <span
                    aria-hidden="true"
                    className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary-tint text-primary-text"
                  >
                    <SparklesIcon className="size-3.5" />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-body-strong">
                    {agentLabel(task.agent)}
                  </span>
                </div>
                <div className="flex">
                  {decision ? <WaitingForYouPill /> : <TaskStatusPill status={task.status} />}
                </div>
                {note ? (
                  <p
                    className={cn(
                      "text-control font-normal",
                      task.status === "failed" ? "text-blocker" : "text-muted-foreground",
                    )}
                  >
                    {note}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </SummaryCard>
  );
}

// --- The summary -----------------------------------------------------------------------------

const ROW = "grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]";

/** The Overview's read-only summary (Story 1.8, redesigned to the new mockups): the KPI row,
 * the Submission pipeline beside Needs you, the Submission blockers beside Recent activity,
 * then the Latest agent decision and the Agent run. Each card stands alone: a failed read only
 * affects its own card. Same for every role that can read the Opportunity. The pipeline and
 * the blockers card follow the workspace's live blockers; `OverviewLiveRefresh` re-renders
 * the rest over the event stream. */
export function OverviewSummary({
  opportunityId,
  data,
  proposalDate,
  today,
}: {
  opportunityId: string;
  data: OverviewData;
  /** The target proposal date (`YYYY-MM-DD`). */
  proposalDate: string;
  /** Today in UTC (`YYYY-MM-DD`), from the server so server and client agree. */
  today: string;
}) {
  return (
    <>
      <KpiRow id={opportunityId} data={data} />
      <div className={ROW}>
        <SubmissionPipeline
          opportunityId={opportunityId}
          data={data}
          proposalDate={proposalDate}
          today={today}
        />
        <NeedsYou id={opportunityId} data={data} />
      </div>
      <div className={ROW}>
        <SubmissionBlockersCard opportunityId={opportunityId} initial={data.blockers ?? null} />
        <RecentActivity id={opportunityId} trace={data.trace} />
      </div>
      <LatestDecision id={opportunityId} assessments={data.assessments} />
      <AgentRun id={opportunityId} assessments={data.assessments} />
    </>
  );
}
