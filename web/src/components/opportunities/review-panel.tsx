"use client";

import { ExternalLinkIcon, GitCompareArrowsIcon, QuoteIcon, RedoIcon } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";

import {
  decideReviewRequest,
  loadReviewPanel,
  type DecideResult,
} from "@/app/opportunities/actions";
import type { ReviewPanelResult } from "@/app/opportunities/data";
import { ReasonInput } from "@/components/opportunities/reason-input";
import { ReviewOutcomes } from "@/components/opportunities/review-outcomes";
import {
  NewVersionButton,
  ReplyComposer,
  outlineButtonClass,
} from "@/components/opportunities/review-reply";
import { RequestStatusPill } from "@/components/opportunities/review-requests-card";
import { RisksCard } from "@/components/opportunities/risks-card";
import {
  BaselinePill,
  SetBaseline,
  type BaselineTarget,
} from "@/components/opportunities/set-baseline";
import { SeverityPill } from "@/components/opportunities/severity-pill";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Pill } from "@/components/ui/pill";
import { Select } from "@/components/ui/select";
import { agentLabel, confidenceLabel, kindLabel, type Assessment } from "@/lib/assessments";
import {
  assumptionId,
  hours,
  sectionLabel,
  versionStatusLabel,
  type EstimateVersion,
} from "@/lib/estimates";
import { useReviewEvents } from "@/lib/opportunity-events";
import { codePointLength } from "@/lib/opportunities";
import {
  ACTIONS_LABEL,
  ALL_APPROVED,
  APPROVE,
  CANCEL,
  CHALLENGE,
  CHALLENGE_LATER,
  CHOOSE_REVIEWER,
  DECISION_FAILED,
  DECISION_FORBIDDEN,
  DECISION_REASON_MAX,
  DECISION_STYLES,
  ESCALATE,
  HIDE_DIFF,
  NO_CHANGES,
  OPEN_IN_TAB,
  LOADING_PANEL,
  PANEL_NOT_LOADED,
  REJECT,
  REQUEST_ALTERNATIVE,
  REQUEST_EVIDENCE,
  VIEW_DIFF,
  alternativeToLabel,
  confirmLabel,
  decisionAnnouncement,
  decisionLine,
  deltaLabel,
  diffHeading,
  escalatedLabel,
  isSupersededPanel,
  panelEyebrow,
  panelTitle,
  reasonLabel,
  reviewPanelHref,
  supersededLabel,
  type Decision,
  type ReasonedDecision,
  type RecordedDecision,
  type RecordedReply,
  type ReviewDecision,
  type ReviewPanel,
  type VersionDiff,
} from "@/lib/reviews";
import { cn } from "@/lib/utils";
import { tabHref } from "@/lib/workspace";

/** Where the panel is shown: the right-pane Inspector, the Inbox detail card, or the full-width
 * **Open in tab** page. */
export type PanelLayout = "inspector" | "inbox" | "page";

const outlineClass = outlineButtonClass;

/** A Review Decision as a pill: its icon and label, never colour alone. */
export function DecisionPill({ decision }: { decision: Decision }) {
  const style = DECISION_STYLES[decision];
  const Icon = style.icon;
  return (
    <Pill tone={style.tone} icon={<Icon />} data-decision={decision} className="shrink-0">
      {style.label}
    </Pill>
  );
}

/** A decision: its pill, "{who} · {decision} · {when}" and its reason. */
export function DecisionEntry({ decision }: { decision: ReviewDecision }) {
  return (
    <div className="flex flex-col gap-0.5" data-decision-entry={decision.id}>
      <div className="flex flex-wrap items-center gap-2">
        <DecisionPill decision={decision.decision} />
        <span className="text-meta text-muted-foreground">{decisionLine(decision)}</span>
      </div>
      {decision.reason ? (
        <p className="whitespace-pre-wrap break-words text-body">{decision.reason}</p>
      ) : null}
    </div>
  );
}

function SubHeading({ children }: { children: ReactNode }) {
  return (
    <h4 className="text-label tracking-[.04em] text-text-secondary uppercase">{children}</h4>
  );
}

/** The version diff: added, removed and changed lines with their hours delta, and the total
 * delta; "First version" when there is none before. */
function DiffView({ diff }: { diff: VersionDiff }) {
  if (diff.first || diff.previous_version == null) {
    return <p className="text-meta text-muted-foreground">{diffHeading(diff)}</p>;
  }
  return (
    <div className="flex flex-col gap-2" data-version-diff="">
      <p className="text-meta text-muted-foreground">
        {`${diffHeading(diff)}: total ${deltaLabel(diff.total_delta)} `}
        {`(${hours(diff.total_before ?? 0)} h to ${hours(diff.total_after)} h)`}
      </p>
      {diff.lines.length === 0 ? (
        <p className="text-meta text-muted-foreground">{NO_CHANGES}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {diff.lines.map((line, i) => (
            <li
              key={`${i}-${line.change}-${line.section}-${line.title}`}
              data-diff-change={line.change}
              className="flex items-baseline gap-2 text-meta"
            >
              <span className="w-16 shrink-0 font-medium capitalize">{line.change}</span>
              <span className="min-w-0 flex-1 break-words">
                {line.title}
                <span className="text-muted-foreground">{` · ${sectionLabel(line.section)}`}</span>
              </span>
              <span className="shrink-0 text-numeric">{deltaLabel(line.delta_hours)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The Estimate Version under review: totals, lines, the Assumptions Register and the Risks. */
function EstimateTarget({ version }: { version: EstimateVersion }) {
  const lines = version.sections.flatMap((section) => section.lines);
  const assumptions = [...version.assumptions.conditions, ...version.assumptions.contingencies];
  return (
    <div className="flex flex-col gap-3" data-review-target="estimate_version">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-meta">
        <span>
          <span className="text-muted-foreground">Total </span>
          <span className="text-body-strong text-numeric">
            {`${hours(version.totals.total_hours)} h`}
          </span>
        </span>
        <span className="text-muted-foreground text-numeric">
          {`Effort ${hours(version.totals.effort_hours)} h · Contingency `}
          {`${hours(version.totals.contingency_hours)} h`}
        </span>
        <span className="text-muted-foreground">{versionStatusLabel(version.status)}</span>
      </div>
      <section className="flex flex-col gap-1.5" aria-label="Estimate lines">
        <SubHeading>{`Lines · ${lines.length}`}</SubHeading>
        <ul className="flex flex-col">
          {lines.map((line) => (
            <li
              key={line.id}
              className="flex items-baseline gap-2 border-t border-border py-1.5 first:border-t-0"
            >
              <span className="min-w-0 flex-1 break-words">
                {line.title}
                <span className="text-meta text-muted-foreground">
                  {` · ${sectionLabel(line.section)}`}
                </span>
              </span>
              <span className="shrink-0 text-numeric">{`${hours(line.total_hours)} h`}</span>
            </li>
          ))}
        </ul>
      </section>
      <section className="flex flex-col gap-1.5" aria-label="Assumptions Register">
        <SubHeading>{`Assumptions · ${assumptions.length}`}</SubHeading>
        {assumptions.length === 0 ? (
          <p className="text-meta text-muted-foreground">No Assumptions.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {assumptions.map((a) => (
              <li key={a.id} className="flex items-baseline gap-2 text-meta">
                <span className="w-8 shrink-0 font-medium">{assumptionId(a)}</span>
                <span className="min-w-0 flex-1 break-words">{a.wording}</span>
                {a.amount_hours != null ? (
                  <span className="shrink-0 text-numeric">{`${hours(a.amount_hours)} h`}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      {version.risks.length > 0 ? <RisksCard risks={version.risks} /> : null}
    </div>
  );
}

/** The Assessment under review: status, confidence and basis, and its Findings by severity,
 * each with its cited-Requirement Evidence chips. */
function AssessmentTarget({ assessment }: { assessment: Assessment }) {
  return (
    <div className="flex flex-col gap-3" data-review-target="assessment">
      <p className="text-meta">
        <span className="text-body-strong">
          {`${agentLabel(assessment.agent).replace(/ Agent$/, "")} Assessment v${assessment.version}`}
        </span>
        <span className="text-muted-foreground">
          {` · ${assessment.status === "current" ? "Current" : "Superseded"} · `}
          {confidenceLabel(assessment.confidence)}
        </span>
      </p>
      <p className="text-body">{assessment.confidence_basis}</p>
      <section className="flex flex-col gap-1.5" aria-label="Findings">
        <SubHeading>{`Findings · ${assessment.findings.length}`}</SubHeading>
        <ul className="flex flex-col gap-2">
          {assessment.findings.map((finding) => (
            <li
              key={finding.id}
              className="flex flex-col gap-1 border-t border-border pt-2 first:border-t-0 first:pt-0"
            >
              <div className="flex flex-wrap items-center gap-2">
                <SeverityPill severity={finding.severity} />
                <span className="text-meta text-muted-foreground">{kindLabel(finding.kind)}</span>
              </div>
              <p className="text-body-strong">{finding.title}</p>
              {finding.requirements.length > 0 ? (
                <ul aria-label="Evidence" className="flex flex-wrap gap-1.5">
                  {finding.requirements.map((r) => (
                    <li key={`${r.id}-${r.version}`}>
                      <Chip title={r.excerpt || undefined}>
                        <QuoteIcon aria-hidden="true" className="size-3 shrink-0" />
                        {r.label}
                      </Chip>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

type Problem = { kind: "stale"; lead: string } | { kind: "message"; text: string };

function problemOf(result: Exclude<DecideResult, { kind: "ok" }>): Problem {
  switch (result.kind) {
    case "stale":
      return { kind: "stale", lead: result.detail };
    case "invalid":
      return { kind: "message", text: result.detail };
    case "forbidden":
      return { kind: "message", text: result.detail ?? DECISION_FORBIDDEN };
    case "not-found":
      return { kind: "message", text: DECISION_FORBIDDEN };
    default:
      return { kind: "message", text: DECISION_FAILED };
  }
}

/** The two action rows, the inline reason (and, to escalate, the reviewer select) with
 * **Confirm {action}** and **Cancel**. Approve records at once; it is `aria-disabled` with the
 * author's hint when `can_approve` is false. Challenge is `aria-disabled` until Story 9.5. */
function DecisionActions({
  panel,
  busy,
  onDecide,
}: {
  panel: ReviewPanel;
  busy: boolean;
  onDecide: (decision: Decision, reason: string, escalatedTo?: string) => Promise<boolean>;
}) {
  const hintId = useId();
  const challengeHintId = useId();
  const selectId = useId();
  const [action, setAction] = useState<ReasonedDecision | null>(null);
  const [reason, setReason] = useState("");
  const [reviewer, setReviewer] = useState("");
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const length = codePointLength(reason.trim());
  const reasonOk = length >= 1 && length <= DECISION_REASON_MAX;
  const ready = reasonOk && (action !== "escalated" || reviewer !== "");

  useEffect(() => {
    if (action) reasonRef.current?.focus();
  }, [action]);

  function choose(next: ReasonedDecision) {
    if (next === action) return;
    // A reason typed for one action never carries over to another.
    setAction(next);
    setReason("");
    setReviewer("");
  }

  function collapse() {
    setAction(null);
    setReason("");
    setReviewer("");
  }

  async function confirm() {
    if (!action || !ready || busy) return;
    const ok = await onDecide(action, reason, action === "escalated" ? reviewer : undefined);
    if (ok) collapse();
  }

  const secondary = (label: string, decision: ReasonedDecision) => (
    <Button
      type="button"
      variant="outline"
      className={outlineClass}
      aria-pressed={action === decision}
      disabled={busy}
      onClick={() => choose(decision)}
    >
      {label}
    </Button>
  );

  return (
    <div
      role="group"
      aria-label={ACTIONS_LABEL}
      className="flex flex-col gap-3 border-t border-border pt-4"
      data-review-actions=""
    >
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          aria-disabled={!panel.can_approve || undefined}
          aria-describedby={panel.can_approve ? undefined : hintId}
          disabled={busy}
          className={cn(!panel.can_approve && "cursor-not-allowed opacity-60")}
          onClick={() => {
            if (panel.can_approve) void onDecide("approved", "");
          }}
        >
          {APPROVE}
        </Button>
        <Button
          type="button"
          variant="outline"
          className={cn(outlineClass, "text-blocker")}
          aria-pressed={action === "rejected"}
          disabled={busy}
          onClick={() => choose("rejected")}
        >
          {REJECT}
        </Button>
        <Button
          type="button"
          variant="outline"
          className={cn(outlineClass, "cursor-not-allowed opacity-60")}
          aria-disabled="true"
          aria-describedby={challengeHintId}
        >
          {CHALLENGE}
        </Button>
        {panel.can_approve ? null : (
          <span id={hintId} className="text-meta text-text-secondary">
            {panel.approve_blocked_reason}
          </span>
        )}
        <span id={challengeHintId} className="text-meta text-text-secondary">
          {CHALLENGE_LATER}
        </span>
      </div>
      {action ? (
        <div className="flex flex-col gap-2" data-reason-form={action}>
          <ReasonInput
            label={reasonLabel(action)}
            value={reason}
            onChange={setReason}
            error={null}
            disabled={busy}
            inputRef={reasonRef}
            max={DECISION_REASON_MAX}
          />
          {action === "escalated" ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={selectId} className="text-meta text-muted-foreground">
                {CHOOSE_REVIEWER}
              </label>
              <Select
                id={selectId}
                value={reviewer}
                disabled={busy}
                onChange={(event) => setReviewer(event.target.value)}
              >
                <option value="">{CHOOSE_REVIEWER}</option>
                {panel.escalation_candidates.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </Select>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button type="button" disabled={!ready || busy} onClick={() => void confirm()}>
              {confirmLabel(action)}
            </Button>
            <Button type="button" variant="outline" disabled={busy} onClick={collapse}>
              {CANCEL}
            </Button>
          </div>
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {secondary(REQUEST_EVIDENCE, "evidence_requested")}
        {secondary(REQUEST_ALTERNATIVE, "alternative_requested")}
        {secondary(ESCALATE, "escalated")}
      </div>
    </div>
  );
}

/** The panel after the caller's own decision, without a read (they may have lost access). */
function afterDecision(panel: ReviewPanel, recorded: RecordedDecision): ReviewPanel {
  const stillMine =
    recorded.request.status === "pending" &&
    recorded.request.reviewer.id === panel.request.reviewer.id;
  return {
    ...panel,
    request: recorded.request,
    decisions: [recorded.decision, ...panel.decisions],
    version_status: recorded.version_status || panel.version_status,
    can_decide: panel.can_decide && stillMine,
    can_approve: panel.can_approve && stillMine,
    escalation_candidates: stillMine ? panel.escalation_candidates : [],
  };
}

/** Story 9.7: the review panel's version as Set Baseline needs it. */
function targetOf(gate: NonNullable<ReviewPanel["version_gate"]>): BaselineTarget {
  return {
    versionId: gate.version_id,
    version: gate.version,
    status: gate.status,
    rowVersion: gate.row_version,
    isBaseline: gate.is_baseline,
    toBaseline: gate.to_baseline,
    canSet: gate.can_set_baseline,
    baselineVersion: gate.baseline_version ?? null,
  };
}

/** The review panel (Story 9.3; the mockup's review block): the header (eyebrow "{Type}
 * review · From {sender} · {date}", the title and the author's message), the request's status
 * with its latest decision, the target (an Estimate Version's lines, totals, Assumptions,
 * Risks and its diff; or an Assessment's Findings with their Evidence chips) and, only when
 * `can_decide`, the two action rows. Story 9.4: for the author (`is_author`, not deciding) the
 * reviewer's actions stay hidden; "Escalated to {name}" after an escalation, the Reply composer
 * (`can_reply`), "All requested reviews approved. Baseline can be set." on an approved version
 * and **New version** (`can_create_version`); for both sides "Alternative to the v{n} request"
 * on a linked request and, under the actions, the Review outcomes list. Greyed with a
 * "Superseded by v4" link, and no actions, when the request or its version is superseded;
 * `dimmed` greys it too (a closed Inbox subject). A 412 shows "Changed by {name} since you
 * opened it." with Reload and View diff; nothing is recorded. */
export function ReviewPanelView({
  opportunityId,
  panel,
  layout,
  dimmed = false,
  onReload,
  onDecided,
  onReplied,
}: {
  opportunityId: string;
  panel: ReviewPanel;
  layout: PanelLayout;
  dimmed?: boolean;
  onReload: () => Promise<void> | void;
  /** After a decision is recorded (the panel already shows it). */
  onDecided: (recorded: RecordedDecision) => void;
  /** Story 9.4: after the author's reply is recorded. */
  onReplied?: (recorded: RecordedReply) => void;
}) {
  const announce = useAnnounce();
  const headingId = useId();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const [reloading, setReloading] = useState(false);
  const { request } = panel;
  const superseded = isSupersededPanel(panel);
  const greyed = superseded || dimmed;
  const actionable = panel.can_decide && !greyed;
  // Story 9.4: the author's side, where the reviewer's actions stay hidden.
  const authorView = panel.is_author && !panel.can_decide && !greyed;
  const latest = panel.decisions[0] ?? request.latest_decision ?? null;
  const reasonId = useId();
  // Story 9.4: next to Reply after a request for an alternative, else on its own.
  const newVersion =
    authorView && panel.can_create_version ? (
      <NewVersionButton
        opportunityId={opportunityId}
        versionId={request.estimate_version_id}
        describedBy={latest ? reasonId : undefined}
        onCreated={() => void onReload()}
      />
    ) : null;
  const Heading = layout === "inspector" ? "h3" : "h2";
  // Story 9.7: the version's Set Baseline state (the Baseline marker, Set Baseline).
  const gate = panel.version_gate ?? null;

  async function decide(decision: Decision, reason: string, escalatedTo?: string) {
    if (busy) return false;
    setBusy(true);
    setProblem(null);
    let result: DecideResult;
    try {
      result = await decideReviewRequest({
        opportunityId,
        requestId: request.id,
        rowVersion: request.row_version,
        decision,
        reason,
        ...(escalatedTo ? { escalatedTo } : {}),
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      announce(decisionAnnouncement(result.value));
      onDecided(result.value);
      return true;
    }
    const next = problemOf(result);
    setProblem(next);
    announce(next.kind === "stale" ? next.lead : next.text);
    return false;
  }

  async function reload() {
    setReloading(true);
    try {
      await onReload();
      setProblem(null);
    } finally {
      setReloading(false);
    }
  }

  return (
    <section
      aria-labelledby={headingId}
      data-review-panel={request.id}
      data-greyed={greyed ? "" : undefined}
      className="flex flex-col gap-4"
    >
      <div className={cn("flex flex-col gap-4", greyed && "opacity-60")}>
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="mb-1 text-meta text-text-secondary">{panelEyebrow(request)}</p>
            <Heading id={headingId} className="text-[16px] leading-6 font-semibold">
              {panelTitle(request, panel.opportunity_title)}
            </Heading>
          </div>
          {layout !== "page" ? (
            <Link
              href={reviewPanelHref(opportunityId, request.id)}
              className="inline-flex shrink-0 items-center gap-1 rounded-md px-1 text-label text-primary-text outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
            >
              <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
              {OPEN_IN_TAB}
            </Link>
          ) : null}
        </div>
        {request.message ? (
          <p className="whitespace-pre-wrap break-words text-body">{request.message}</p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2" data-review-status="">
          {gate?.is_baseline ? (
            <BaselinePill label={`v${gate.version} · Baseline`} />
          ) : (
            <RequestStatusPill status={request.status} />
          )}
          <span className="text-meta text-muted-foreground">
            {`Reviewer: ${request.reviewer.name}`}
          </span>
        </div>
        {latest ? (
          <div id={reasonId}>
            <DecisionEntry decision={latest} />
          </div>
        ) : null}
        {panel.is_author && latest?.decision === "escalated" && panel.escalated_to ? (
          <p className="text-body-strong" data-escalated-to="">
            {escalatedLabel(panel.escalated_to.name)}
          </p>
        ) : null}
        {panel.linked_request ? (
          <Link
            href={reviewPanelHref(opportunityId, panel.linked_request.id)}
            className="inline-flex items-center gap-1.5 self-start text-meta text-primary-text outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
            data-linked-request=""
          >
            <GitCompareArrowsIcon aria-hidden="true" className="size-3.5" />
            {alternativeToLabel(panel.linked_request.version_number)}
          </Link>
        ) : null}
        {panel.estimate ? <EstimateTarget version={panel.estimate} /> : null}
        {panel.assessment ? <AssessmentTarget assessment={panel.assessment} /> : null}
        {panel.diff ? (
          <section className="flex flex-col gap-1.5" aria-label="Version diff">
            <div className="flex items-center gap-2">
              <SubHeading>{diffHeading(panel.diff)}</SubHeading>
              {panel.diff.first ? null : (
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  aria-expanded={diffOpen}
                  onClick={() => setDiffOpen((open) => !open)}
                >
                  {diffOpen ? HIDE_DIFF : VIEW_DIFF}
                </Button>
              )}
            </div>
            {diffOpen || panel.diff.first ? <DiffView diff={panel.diff} /> : null}
          </section>
        ) : null}
      </div>
      {superseded ? (
        <Link
          href={tabHref(opportunityId, "estimate")}
          className="inline-flex items-center gap-1.5 self-start text-body-strong text-primary-text outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
        >
          <RedoIcon aria-hidden="true" className="size-3.5" />
          {supersededLabel(panel.superseded_by)}
        </Link>
      ) : null}
      {problem?.kind === "stale" ? (
        <InlineAlert
          lead={problem.lead}
          onReload={() => void reload()}
          reloading={reloading}
          {...(panel.diff && !panel.diff.first
            ? { onViewDiff: () => setDiffOpen((open) => !open), diffExpanded: diffOpen }
            : {})}
        />
      ) : problem ? (
        <p
          role="alert"
          className="rounded-md border border-blocker/30 bg-blocker-tint px-3 py-2 text-meta text-blocker"
        >
          {problem.text}
        </p>
      ) : null}
      {actionable ? (
        <DecisionActions panel={panel} busy={busy} onDecide={decide} />
      ) : null}
      {authorView && panel.can_reply ? (
        <ReplyComposer
          opportunityId={opportunityId}
          panel={panel}
          onReload={onReload}
          onReplied={(recorded) => onReplied?.(recorded)}
          beside={newVersion}
        />
      ) : null}
      {authorView && panel.version_status === "approved" && !gate?.is_baseline ? (
        // Story 9.7: **Set Baseline** beside it (the mockup's review block).
        <div
          className="flex flex-wrap items-center gap-3 border-t border-border pt-3"
          data-all-approved=""
        >
          <p className="min-w-0 flex-1 text-[13px] leading-5 text-text-secondary">
            {ALL_APPROVED}
          </p>
          {gate ? (
            <SetBaseline
              opportunityId={opportunityId}
              target={targetOf(gate)}
              showReason={false}
              onSet={() => void onReload()}
              onReload={() => void onReload()}
            />
          ) : null}
        </div>
      ) : null}
      {newVersion && !panel.can_reply ? (
        <div className="border-t border-border pt-3">{newVersion}</div>
      ) : null}
      <div className={cn(greyed && "opacity-60")}>
        <ReviewOutcomes panel={panel} />
      </div>
    </section>
  );
}

/** Reads the review panel (unless `initial` is given), keeps it fresh and renders it: again
 * after a decision is recorded elsewhere (`live`: the Opportunity's Review frames) and on
 * Reload. A read that fails after the first keeps what is shown (e.g. the reviewer lost access
 * with their decision). Until the first read succeeds it shows `fallback` (if given), else
 * "Loading the review…" and, once that read failed, "The review could not be loaded.". */
export function ReviewPanelLoader({
  opportunityId,
  requestId,
  initial = null,
  layout,
  live = true,
  dimmed = false,
  fallback,
  onDecided,
}: {
  opportunityId: string;
  requestId: string;
  initial?: ReviewPanel | null;
  layout: PanelLayout;
  live?: boolean;
  dimmed?: boolean;
  fallback?: ReactNode;
  onDecided?: (recorded: RecordedDecision) => void;
}) {
  const [panel, setPanel] = useState<ReviewPanel | null>(initial);
  const [failed, setFailed] = useState(false);
  const panelRef = useRef(panel);
  useEffect(() => {
    panelRef.current = panel;
  }, [panel]);

  const apply = useCallback((result: ReviewPanelResult) => {
    if (result.kind === "ok") {
      setPanel(result.panel);
      setFailed(false);
    } else if (!panelRef.current) {
      setFailed(true);
    } else {
      // No longer readable (e.g. after escalating it): keep it, read only.
      setPanel((current) =>
        current ? { ...current, can_decide: false, can_approve: false } : current,
      );
    }
  }, []);

  const reload = useCallback(async () => {
    let result: ReviewPanelResult;
    try {
      result = await loadReviewPanel({ opportunityId, requestId });
    } catch {
      result = { kind: "error" };
    }
    apply(result);
  }, [opportunityId, requestId, apply]);

  const hasInitial = initial !== null;
  useEffect(() => {
    if (hasInitial) return;
    let cancelled = false;
    loadReviewPanel({ opportunityId, requestId })
      .catch((): ReviewPanelResult => ({ kind: "error" }))
      .then((result) => {
        if (!cancelled) apply(result);
      });
    return () => {
      cancelled = true;
    };
  }, [hasInitial, opportunityId, requestId, apply]);
  useReviewEvents(opportunityId, () => void reload(), live);

  if (!panel) {
    if (fallback) return fallback;
    if (failed) return <p className="text-muted-foreground">{PANEL_NOT_LOADED}</p>;
    return <p className="text-meta text-muted-foreground">{LOADING_PANEL}</p>;
  }
  return (
    <ReviewPanelView
      opportunityId={opportunityId}
      panel={panel}
      layout={layout}
      dimmed={dimmed}
      onReload={reload}
      onDecided={(recorded) => {
        setPanel((current) => (current ? afterDecision(current, recorded) : current));
        onDecided?.(recorded);
      }}
      onReplied={(recorded) => {
        setPanel((current) =>
          current
            ? {
                ...current,
                request: recorded.request,
                replies: [recorded.reply, ...current.replies],
              }
            : current,
        );
      }}
    />
  );
}
