"use client";

import {
  CheckIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  ClockIcon,
  LoaderCircleIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { Card } from "@/components/ui/card";
import { Pill, type PillTone } from "@/components/ui/pill";
import { useSubmission } from "@/components/opportunities/submission-context";
import { daysUntil } from "@/lib/opportunities";
import {
  conflictsBlockSubmit,
  dueLabel,
  pipelineProgress,
  pipelineSteps,
  stepsBlockedLabel,
  stepsCompleteLabel,
  type OverviewReads,
  type PipelineState,
} from "@/lib/overview";
import type { SubmissionBlockersView } from "@/lib/submission";
import { cn } from "@/lib/utils";
import { tabHref } from "@/lib/workspace";

/** The submission blockers the Overview reads: the workspace provider's live view when one is
 * above and loaded (the same view the card, badge and header read), else the server's read. */
export function useOverviewBlockers(
  fallback: SubmissionBlockersView | null | undefined,
): SubmissionBlockersView | null {
  const submission = useSubmission();
  return submission?.view ?? fallback ?? null;
}

/** Each state's pill (icon plus text, never colour alone) and its node. */
const STEP_DISPLAY: Record<
  PipelineState,
  { label: string; tone: PillTone; icon: LucideIcon; circle: string }
> = {
  complete: {
    label: "Complete",
    tone: "resolved",
    icon: CircleCheckIcon,
    circle: "border-resolved bg-resolved text-resolved-foreground",
  },
  "in-progress": {
    label: "In progress",
    tone: "agent",
    icon: LoaderCircleIcon,
    circle: "border-primary bg-primary-tint text-primary-text",
  },
  blocked: {
    label: "Blocked",
    tone: "blocker",
    icon: CircleAlertIcon,
    circle: "border-blocker bg-blocker-tint text-blocker",
  },
  pending: {
    label: "Pending",
    tone: "neutral",
    icon: ClockIcon,
    circle: "border-border-strong bg-surface text-muted-foreground",
  },
};

const titleLink =
  "rounded-sm underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary";

/** The Submission pipeline card (Story 8.9): eight steps, each a node, its title linking to
 * its tab, a one-line state and a status pill, over the "2 of 8 steps complete · 3 steps
 * blocked" footer. A status tracker: no step is disabled or waits on an earlier one. Blocked
 * comes only from the submission blockers view, so it changes on the same frame as the card. */
export function SubmissionPipeline({
  opportunityId,
  data,
  proposalDate,
  today,
}: {
  opportunityId: string;
  data: OverviewReads;
  proposalDate: string;
  today: string;
}) {
  const blockers = useOverviewBlockers(data.blockers);
  const steps = pipelineSteps(data, blockers);
  const progress = pipelineProgress(steps);
  const due = dueLabel(daysUntil(proposalDate, today));
  const pct = (n: number) => `${(n / progress.total) * 100}%`;
  const complete = stepsCompleteLabel(progress.done, progress.total);
  const blocked = stepsBlockedLabel(progress.blocked);
  return (
    <Card role="region" aria-labelledby="overview-pipeline" className="min-w-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-[18px]">
        <h3 id="overview-pipeline" className="min-w-0 flex-1 text-section">
          Submission pipeline
        </h3>
        {due ? (
          <span
            className={cn(
              "inline-flex items-center gap-1 text-control",
              due.overdue ? "text-blocker" : "text-muted-foreground",
            )}
          >
            {due.overdue ? <TriangleAlertIcon aria-hidden="true" className="size-3.5" /> : null}
            {due.text}
          </span>
        ) : null}
      </div>
      <ol className="px-5 py-2">
        {steps.map((step, i) => {
          const display = STEP_DISPLAY[step.state];
          const Icon = display.icon;
          const last = i === steps.length - 1;
          return (
            <li key={step.key} data-step-state={step.state} className="flex items-stretch gap-3.5">
              <div aria-hidden="true" className="flex flex-col items-center">
                <span
                  className={cn(
                    "mt-2 flex size-7 shrink-0 items-center justify-center rounded-full border-2 text-label",
                    display.circle,
                  )}
                >
                  {step.state === "complete" ? <CheckIcon className="size-3.5" /> : i + 1}
                </span>
                {last ? null : (
                  <span
                    className={cn(
                      "min-h-2 w-0.5 flex-1",
                      step.state === "complete" ? "bg-resolved" : "bg-border",
                    )}
                  />
                )}
              </div>
              <div
                className={cn(
                  "flex min-w-0 flex-1 items-center gap-3 py-2.5",
                  last ? null : "border-b border-border",
                )}
              >
                <div className="min-w-0 flex-1">
                  <Link
                    href={tabHref(opportunityId, step.tab)}
                    className={cn(
                      titleLink,
                      step.state === "pending" ? "text-body" : "text-body-strong",
                    )}
                  >
                    {step.title}
                  </Link>
                  <div className="text-meta text-muted-foreground">{step.sub}</div>
                </div>
                <Pill tone={display.tone} icon={<Icon />}>
                  {display.label}
                </Pill>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="border-t border-border px-5 py-3">
        <div className="flex flex-col gap-1.5 pt-0.5 pb-1.5">
          <p className="sr-only">{`${complete} · ${blocked}`}</p>
          <div aria-hidden="true" className="flex justify-between gap-2 text-control">
            <span className="text-body-strong">{complete}</span>
            <span className="text-muted-foreground">{blocked}</span>
          </div>
          <div aria-hidden="true" className="flex h-2 overflow-hidden rounded-full bg-surface-alt">
            <div className="bg-resolved" style={{ width: pct(progress.done) }} />
            <div className="bg-primary" style={{ width: pct(progress.inProgress) }} />
            <div className="bg-blocker" style={{ width: pct(progress.blocked) }} />
          </div>
        </div>
      </div>
    </Card>
  );
}

/** The Conflicts KPI pill while Conflicts are open: "Blocks submit" when the blockers view has
 * Conflict items, else "Needs a decision". */
export function ConflictsKpiPill({
  fallback,
}: {
  fallback: SubmissionBlockersView | null | undefined;
}) {
  const blockers = useOverviewBlockers(fallback);
  return (
    <span className="mt-2 flex">
      {conflictsBlockSubmit(blockers) ? (
        <Pill tone="blocker" icon={<CircleAlertIcon />}>
          Blocks submit
        </Pill>
      ) : (
        <Pill tone="gap" icon={<TriangleAlertIcon />}>
          Needs a decision
        </Pill>
      )}
    </span>
  );
}
