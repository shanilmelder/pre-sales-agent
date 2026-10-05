import {
  CircleAlertIcon,
  CircleCheckIcon,
  ClipboardListIcon,
  OctagonAlertIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { RecommendationPill } from "@/components/opportunities/specialist-assessments";
import {
  agentLabel,
  confidenceLabel,
  isAssessing,
  NO_AGENT_ASSESSMENT,
  runStatusLabel,
  type AssessmentsView,
} from "@/lib/assessments";
import { hours, versionStatusLabel, type EstimateView } from "@/lib/estimates";
import type { GapList } from "@/lib/gaps";
import {
  ATTENTION_INCOMPLETE,
  attentionItems,
  byTypeLabel,
  couldNotLoad,
  criticalHighLabel,
  cutAttention,
  estimateTitle,
  gapCounts,
  highImpactLabel,
  isStepStatus,
  itemCountLabel,
  moreLabel,
  NO_ASSESSMENT_YET,
  NO_ESTIMATE_YET,
  noAssessmentYet,
  NOT_RUN,
  NOTHING_NEEDS_ATTENTION,
  parsedLabel,
  requirementCounts,
  sourceCounts,
  type AttentionKind,
} from "@/lib/overview";
import { isReviewing, REVIEWING, type RedTeamView } from "@/lib/red-team";
import type { RequirementList } from "@/lib/requirements";
import type { Source } from "@/lib/sources";
import { absoluteTime, eventLabel, NO_EVENTS, relativeTime, type TraceEvent } from "@/lib/trace";
import { cn } from "@/lib/utils";
import { tabHref, WORKSPACE_TABS, type WorkspaceTabSlug } from "@/lib/workspace";

/** One read's outcome: its data, or `null` when it failed. */
export type OverviewData = {
  sources: Source[] | null;
  requirements: RequirementList | null;
  gaps: GapList | null;
  estimate: EstimateView | null;
  assessments: AssessmentsView | null;
  redTeam: RedTeamView | null;
  trace: TraceEvent[] | null;
};

const RECENT_ACTIVITY_LIMIT = 5;

const linkClass =
  "rounded-sm text-primary underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary";

function tabLabel(slug: WorkspaceTabSlug) {
  return WORKSPACE_TABS.find((t) => t.slug === slug)!;
}

/** "Open Estimate" with the tab's key as a visual hint. */
function OpenTab({ id, tab }: { id: string; tab: WorkspaceTabSlug }) {
  const known = tabLabel(tab);
  return (
    <Link href={tabHref(id, tab)} className={cn(linkClass, "ml-auto text-label")}>
      Open {known.label}
      <kbd aria-hidden="true" className="ml-1 text-meta text-muted-foreground">
        {known.key}
      </kbd>
    </Link>
  );
}

function Card({
  id,
  title,
  extra,
  children,
}: {
  id: string;
  title: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={id} className="text-section">
          {title}
        </h3>
        {extra}
      </div>
      {children}
    </section>
  );
}

const Muted = ({ children }: { children: ReactNode }) => (
  <p className="text-muted-foreground">{children}</p>
);

/** Each kind's icon and type label (none for an Assumption: its row text already says
 * "Unaccepted Assumption"). Blocker red only for critical; amber for the rest. */
const ATTENTION_DISPLAY: Record<
  AttentionKind,
  { type: string | null; icon: LucideIcon; tone: string }
> = {
  "critical-finding": { type: "Critical", icon: OctagonAlertIcon, tone: "text-blocker" },
  "high-finding": { type: "High", icon: TriangleAlertIcon, tone: "text-gap" },
  gap: { type: "High impact", icon: CircleAlertIcon, tone: "text-gap" },
  assumption: { type: null, icon: ClipboardListIcon, tone: "text-gap" },
};

/** Needs attention: up to 8 rows, most severe first, each an icon plus a label and a link to
 * its tab. Read-only; it blocks nothing. */
function NeedsAttention({ id, data }: { id: string; data: OverviewData }) {
  const items = attentionItems(data);
  const { shown, more, moreTab } = cutAttention(items);
  const incomplete =
    data.redTeam === null || data.assessments === null || data.gaps === null || data.estimate === null;
  return (
    <Card
      id="overview-attention"
      title="Needs attention"
      extra={
        items.length > 0 ? (
          <span
            role="img"
            aria-label={itemCountLabel(items.length)}
            className="text-label text-numeric text-muted-foreground"
          >
            {items.length}
          </span>
        ) : null
      }
    >
      {shown.length > 0 ? (
        <ul className="flex flex-col">
          {shown.map((item) => {
            const display = ATTENTION_DISPLAY[item.kind];
            const Icon = display.icon;
            return (
              <li key={item.key} className="border-t border-border first:border-t-0">
                <Link
                  href={tabHref(id, item.tab)}
                  className="flex min-h-row items-center gap-2 rounded-sm px-1 outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-primary"
                >
                  <Icon aria-hidden="true" className={cn("size-3.5 shrink-0", display.tone)} />
                  <span className="w-24 shrink-0 text-label">{display.type}</span>
                  <span title={item.label} className="min-w-0 flex-1 truncate text-body">
                    {item.label}
                  </span>
                  <span className="shrink-0 text-meta text-muted-foreground">
                    {tabLabel(item.tab).label}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : incomplete ? null : (
        <Muted>{NOTHING_NEEDS_ATTENTION}</Muted>
      )}
      {more > 0 && moreTab ? (
        <Link href={tabHref(id, moreTab)} className={cn(linkClass, "self-start text-label")}>
          {moreLabel(more)}
        </Link>
      ) : more > 0 ? (
        <p className="text-label text-muted-foreground">{moreLabel(more)}</p>
      ) : null}
      {incomplete ? <Muted>{ATTENTION_INCOMPLETE}</Muted> : null}
    </Card>
  );
}

function Stat({
  label,
  value,
  detail,
  href,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  href?: string;
}) {
  const body = (
    <>
      <span className="text-meta text-muted-foreground">{label}</span>
      <span className="text-title text-numeric">{value}</span>
      {detail ? <span className="text-meta text-muted-foreground">{detail}</span> : null}
    </>
  );
  return href ? (
    <Link
      href={href}
      className="flex min-w-32 flex-col gap-0.5 rounded-sm text-foreground outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-primary"
    >
      {body}
    </Link>
  ) : (
    <div className="flex min-w-32 flex-col gap-0.5">{body}</div>
  );
}

/** Pipeline: Sources, Requirements and open Gaps, each linking to its tab ("—" before the
 * step has run). */
function Pipeline({ id, data }: { id: string; data: OverviewData }) {
  const sources = data.sources === null ? null : sourceCounts(data.sources);
  const requirements = data.requirements === null ? null : requirementCounts(data.requirements);
  const gaps = data.gaps === null ? null : gapCounts(data.gaps);
  return (
    <Card id="overview-pipeline" title="Pipeline">
      <div className="flex flex-wrap gap-6">
        <PipelineStat
          label="Sources"
          failed={data.sources === null}
          href={tabHref(id, "sources")}
          value={sources?.total}
          detail={sources ? parsedLabel(sources) : null}
        />
        <PipelineStat
          label="Requirements"
          failed={data.requirements === null}
          href={tabHref(id, "requirements")}
          value={requirements && !isStepStatus(requirements) ? requirements.active : undefined}
          detail={
            requirements === null
              ? null
              : isStepStatus(requirements)
                ? requirements.status
                : requirements.byType.length > 0
                  ? byTypeLabel(requirements.byType)
                  : null
          }
        />
        <PipelineStat
          label="Open Gaps"
          failed={data.gaps === null}
          href={tabHref(id, "gaps")}
          value={gaps && !isStepStatus(gaps) ? gaps.open : undefined}
          detail={
            gaps === null ? null : isStepStatus(gaps) ? gaps.status : highImpactLabel(gaps.high)
          }
        />
      </div>
    </Card>
  );
}

function PipelineStat({
  label,
  failed,
  href,
  value,
  detail,
}: {
  label: string;
  failed: boolean;
  href: string;
  value: number | undefined;
  detail: string | null;
}) {
  if (failed) {
    return <Stat label={label} value={NOT_RUN} detail={couldNotLoad(label)} href={href} />;
  }
  return <Stat label={label} value={value ?? NOT_RUN} detail={detail} href={href} />;
}

/** The current Estimate Version's server totals and its Assumptions. */
function EstimateCard({ id, estimate }: { id: string; estimate: EstimateView | null }) {
  const version = estimate?.version ?? null;
  return (
    <Card
      id="overview-estimate"
      title={version ? estimateTitle(version.version) : "Estimate"}
      extra={
        <>
          {version ? (
            <span className="inline-flex h-5 items-center rounded-full border border-border bg-background px-2 text-label">
              {versionStatusLabel(version.status)}
            </span>
          ) : null}
          {version ? (
            <span className="text-meta text-muted-foreground">totals calculated by the platform</span>
          ) : null}
          <OpenTab id={id} tab="estimate" />
        </>
      }
    >
      {estimate === null ? (
        <p>{couldNotLoad("The Estimate")}</p>
      ) : version === null ? (
        <Muted>{NO_ESTIMATE_YET}</Muted>
      ) : (
        <div className="flex flex-wrap gap-6">
          <Stat label="Effort" value={`${hours(version.totals.effort_hours)} h`} />
          <Stat label="Contingency" value={`${hours(version.totals.contingency_hours)} h`} />
          <Stat label="Total" value={`${hours(version.totals.total_hours)} h`} />
          <Stat
            label="Assumptions"
            value={version.counts.total}
            detail={
              <span className="inline-flex flex-wrap items-center gap-1">
                <CircleCheckIcon aria-hidden="true" className="size-3 text-resolved" />
                <span className="text-numeric">{version.counts.accepted}</span> accepted ·{" "}
                <ClipboardListIcon aria-hidden="true" className="size-3 text-blocker" />
                <span className="text-numeric">{version.counts.not_accepted}</span> not accepted
              </span>
            }
          />
        </div>
      )}
    </Card>
  );
}

/** One line per specialist agent with its recommendation and confidence, the Red Team's
 * critical/high counts, and the latest run's status while it is queued or running. */
function AssessmentsCard({
  id,
  assessments,
  redTeam,
}: {
  id: string;
  assessments: AssessmentsView | null;
  redTeam: RedTeamView | null;
}) {
  const bothFailed = assessments === null && redTeam === null;
  const empty = assessments !== null && redTeam !== null && noAssessmentYet(assessments, redTeam);
  const running = assessments && isAssessing(assessments.run) ? assessments.run : null;
  return (
    <Card
      id="overview-assessments"
      title="Assessments"
      extra={
        <>
          {running ? (
            <span className="text-label text-muted-foreground" data-status={running.status}>
              {runStatusLabel(running)}
            </span>
          ) : null}
          {redTeam && isReviewing(redTeam.run) ? (
            <span className="text-label text-muted-foreground">{REVIEWING}</span>
          ) : null}
          <OpenTab id={id} tab="assessments" />
        </>
      }
    >
      {bothFailed ? (
        <p>{couldNotLoad("The Assessments")}</p>
      ) : empty ? (
        <Muted>{NO_ASSESSMENT_YET}</Muted>
      ) : (
        <ul className="flex flex-col">
          {assessments === null ? (
            <li className="min-h-row-compact py-1">{couldNotLoad("The Specialist Assessments")}</li>
          ) : (
            assessments.assessments.map((slot) => (
              <li key={slot.agent} className="flex min-h-row-compact flex-wrap items-center gap-3">
                <span className="w-36 shrink-0 text-label">{agentLabel(slot.agent)}</span>
                {slot.assessment ? (
                  <>
                    <RecommendationPill recommendation={slot.assessment.recommendation} />
                    <span className="text-meta text-muted-foreground">
                      {confidenceLabel(slot.assessment.confidence)}
                    </span>
                  </>
                ) : (
                  <span className="text-meta text-muted-foreground">{NO_AGENT_ASSESSMENT}</span>
                )}
              </li>
            ))
          )}
          {redTeam === null ? (
            <li className="min-h-row-compact py-1">{couldNotLoad("The Red Team Review")}</li>
          ) : (
            <li className="flex min-h-row-compact flex-wrap items-center gap-3">
              <span className="w-36 shrink-0 text-label">Red Team</span>
              {redTeam.review ? (
                <span className="text-meta text-numeric">
                  {criticalHighLabel(redTeam.review.counts)}
                </span>
              ) : (
                <span className="text-meta text-muted-foreground">No review yet.</span>
              )}
            </li>
          )}
        </ul>
      )}
    </Card>
  );
}

/** The five newest trace events: time, actor and the event in plain words. */
function RecentActivity({ id, trace }: { id: string; trace: TraceEvent[] | null }) {
  const items = trace?.slice(0, RECENT_ACTIVITY_LIMIT) ?? [];
  return (
    <Card id="overview-activity" title="Recent activity" extra={<OpenTab id={id} tab="trace" />}>
      {trace === null ? (
        <p>{couldNotLoad("The recent activity")}</p>
      ) : items.length === 0 ? (
        <Muted>{NO_EVENTS}</Muted>
      ) : (
        <ul className="flex flex-col">
          {items.map((item) => (
            <li key={item.id} className="flex min-h-row-compact items-center gap-3">
              <time
                dateTime={item.occurred_at}
                title={absoluteTime(item.occurred_at)}
                className="w-24 shrink-0 truncate text-meta text-muted-foreground text-numeric"
              >
                {relativeTime(item.occurred_at)}
              </time>
              <span
                title={item.actor.name}
                className="w-40 shrink-0 truncate text-meta text-muted-foreground"
              >
                {item.actor.name}
              </span>
              <span title={eventLabel(item.event_type)} className="min-w-0 flex-1 truncate text-body">
                {eventLabel(item.event_type)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** The Overview's read-only summary (Story 1.8, demo slice): Needs attention, the Pipeline
 * counts, the Estimate, the Assessments and the recent activity, each linking to its tab.
 * Each card stands alone: a failed read only affects its own card. Same for every role that
 * can read the Opportunity. Rendered on navigation; no polling. */
export function OverviewSummary({ opportunityId, data }: { opportunityId: string; data: OverviewData }) {
  return (
    <div className="flex flex-col gap-4">
      <NeedsAttention id={opportunityId} data={data} />
      <Pipeline id={opportunityId} data={data} />
      <div className="grid gap-4 xl:grid-cols-2">
        <EstimateCard id={opportunityId} estimate={data.estimate} />
        <AssessmentsCard id={opportunityId} assessments={data.assessments} redTeam={data.redTeam} />
      </div>
      <RecentActivity id={opportunityId} trace={data.trace} />
    </div>
  );
}
