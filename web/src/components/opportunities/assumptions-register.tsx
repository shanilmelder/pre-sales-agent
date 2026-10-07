"use client";

import { CircleAlertIcon, ClipboardCheckIcon, ShieldPlusIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import {
  acceptAllAssumptions,
  acceptAssumption,
  loadEstimate,
  type AcceptAllAssumptionsResult,
  type AssumptionAcceptResult,
} from "@/app/opportunities/actions";
import { ImpactBar } from "@/components/opportunities/impact-bar";
import { useAnnounce } from "@/components/shell/live-region";
import {
  acceptAllLabel,
  acceptedLabel,
  carriedLabel,
  CONDITIONS,
  CONTINGENCIES,
  hours,
  isProposing,
  NOT_ACCEPTED,
  PROPOSALS_FAILED,
  PROPOSALS_MISSING,
  PROPOSING,
  registerSummary,
  staleMessage,
  UNCONVERTED_GAPS,
  type Assumption,
  type EstimateVersion,
  type EstimateView,
  type OriginGap,
} from "@/lib/estimates";
import { categoryLabel } from "@/lib/gaps";
import { cn } from "@/lib/utils";

export const ACCEPT = "Accept";
export const RELOAD = "Reload";
const ACCEPT_FAILED = "The Assumption could not be accepted. Try again.";
const ACCEPT_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can accept Assumptions.";
const GAP_NOT_OPEN =
  "Its Gap is no longer open: it was converted or replaced by a newer Gap detection. Reload to see the latest.";
const GONE = "This Assumption is no longer in the current draft. Reload to see the latest.";

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

function failure(result: AssumptionAcceptResult | AcceptAllAssumptionsResult): string {
  switch (result.kind) {
    case "gap-not-open":
      return GAP_NOT_OPEN;
    case "forbidden":
      return ACCEPT_NOT_ALLOWED;
    case "not-found":
      return GONE;
    default:
      return ACCEPT_FAILED;
  }
}

/** One Assumption as a Register row. An unaccepted row is a blocker row: blocker tint, a 2px
 * blocker bar and a "Not accepted" label (never colour alone), with **Accept** for those who
 * may accept. An accepted row reads "Accepted by {name}, {date}". */
function AssumptionRow({
  assumption,
  canAccept,
  busy,
  selected,
  onAccept,
  onOpenGap,
}: {
  assumption: Assumption;
  canAccept: boolean;
  busy: boolean;
  selected: boolean;
  onAccept: (assumption: Assumption) => void;
  onOpenGap: (assumption: Assumption, viaKeyboard: boolean) => void;
}) {
  const accepted = assumption.accepted_at !== null;
  const carried = carriedLabel(assumption);
  return (
    <li
      data-assumption-id={assumption.id}
      data-blocker={accepted ? undefined : ""}
      className={cn(
        "flex flex-col gap-1 border-b border-border px-3 py-2",
        accepted ? "" : "bg-blocker-tint shadow-[inset_2px_0_0_var(--blocker)]",
      )}
    >
      <div className="flex items-start gap-3">
        <p className="min-w-0 flex-1 break-words text-body">{assumption.wording}</p>
        {assumption.amount_hours !== null ? (
          <span className="shrink-0 text-numeric whitespace-nowrap">
            {`${hours(assumption.amount_hours)} h`}
          </span>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button
          type="button"
          data-gap-chip=""
          aria-pressed={selected}
          aria-label={`Gap: ${assumption.origin.title}`}
          onClick={(event) => onOpenGap(assumption, event.detail === 0)}
          className={cn(
            "inline-flex h-5 max-w-64 items-center gap-1 rounded-sm border border-border bg-background px-1.5 text-meta text-muted-foreground outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary",
            selected && "border-primary text-foreground",
          )}
        >
          <span className="font-medium">Gap</span>
          <span className="truncate">{assumption.origin.title}</span>
        </button>
        {assumption.line ? (
          <span className="min-w-0 truncate text-meta text-muted-foreground">
            {`Line: ${assumption.line.title}`}
          </span>
        ) : null}
        <span className="ml-auto flex items-center gap-2">
          {accepted ? (
            <>
              {carried ? <span className="text-meta text-muted-foreground">{carried}</span> : null}
              <span className="text-meta text-muted-foreground">{acceptedLabel(assumption)}</span>
            </>
          ) : (
            <>
              <span className="flex items-center gap-1 text-label text-blocker">
                <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
                {NOT_ACCEPTED}
              </span>
              {canAccept ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onAccept(assumption)}
                  aria-label={`${ACCEPT}: ${assumption.wording}`}
                  className={cn(actionClass, "bg-background")}
                >
                  {ACCEPT}
                </button>
              ) : null}
            </>
          )}
        </span>
      </div>
    </li>
  );
}

function Group({
  title,
  icon,
  items,
  total,
  ...row
}: {
  title: string;
  icon: ReactNode;
  items: readonly Assumption[];
  total?: string;
  canAccept: boolean;
  busyId: string | null;
  selectedId: string | null;
  onAccept: (assumption: Assumption) => void;
  onOpenGap: (assumption: Assumption, viaKeyboard: boolean) => void;
}) {
  const headingId = useId();
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="flex flex-col">
      <h4
        id={headingId}
        className="flex h-7 items-center gap-1.5 border-b border-border bg-muted px-3 text-label text-muted-foreground"
      >
        {icon}
        <span>{title}</span>
        <span className="[font-variant-numeric:tabular-nums]">{`(${items.length})`}</span>
        {total ? <span className="ml-auto text-numeric text-foreground">{total}</span> : null}
      </h4>
      <ul className="flex flex-col">
        {items.map((assumption) => (
          <AssumptionRow
            key={assumption.id}
            assumption={assumption}
            canAccept={row.canAccept}
            busy={row.busyId !== null}
            selected={assumption.id === row.selectedId}
            onAccept={row.onAccept}
            onOpenGap={row.onOpenGap}
          />
        ))}
      </ul>
    </section>
  );
}

/** The Assumptions Register below the grid (Story 8.4 + 8.5, minimal): the version's
 * Conditions and Contingencies (with their total), each with its wording, hours, a "Gap"
 * origin chip that opens the Gap in the inspector, its linked line and who accepted it; the
 * header "7 · 6 accepted · 1 not accepted" with **Accept all (N)**; and an "Unconverted Gaps"
 * note for open Gaps with no proposal. After every accept the Estimate is read again, so the
 * grid's Contingency column and totals come from the server. Read-only without
 * `canAccept`. Proposals that failed or are missing are said so, with no re-draft Retry
 * (Story 8.3: the Estimate is built from the Assessments). */
export function AssumptionsRegister({
  opportunityId,
  version,
  canAccept,
  selectedId = null,
  onChanged,
  onOpenGap,
}: {
  opportunityId: string;
  version: EstimateVersion;
  canAccept: boolean;
  /** The Assumption whose Gap is open in the inspector. */
  selectedId?: string | null;
  /** The Estimate as read again after an accept or a Reload. */
  onChanged: (estimate: EstimateView) => void;
  onOpenGap: (assumption: Assumption, viaKeyboard: boolean) => void;
}) {
  const announce = useAnnounce();
  const headingId = useId();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  /** Set after a 412: who changed it (null when unknown). */
  const [stale, setStale] = useState<{ changedBy: string | null } | null>(null);
  const { conditions, contingencies, contingency_hours } = version.assumptions;
  const { counts, unconverted_gaps: unconverted } = version;
  const proposing = isProposing(version);

  async function reload(): Promise<boolean> {
    try {
      const loaded = await loadEstimate(opportunityId);
      if (loaded.kind === "ok") {
        onChanged(loaded.estimate);
        return true;
      }
    } catch {
      // The Register stays as it is.
    }
    return false;
  }

  async function accept(assumption: Assumption) {
    if (busyId) return;
    setBusyId(assumption.id);
    setMessage(null);
    setStale(null);
    let result: AssumptionAcceptResult;
    try {
      result = await acceptAssumption({
        opportunityId,
        assumptionId: assumption.id,
        rowVersion: assumption.row_version,
      });
    } catch {
      result = { kind: "error" };
    }
    if (result.kind === "ok") {
      await reload();
      announce(acceptedLabel(result.assumption));
    } else if (result.kind === "stale") {
      setStale({ changedBy: result.changedBy });
      announce(staleMessage(result.changedBy));
    } else {
      const sentence = failure(result);
      setMessage(sentence);
      announce(sentence);
    }
    setBusyId(null);
  }

  async function acceptAll() {
    if (busyId) return;
    setBusyId("all");
    setMessage(null);
    setStale(null);
    let result: AcceptAllAssumptionsResult;
    try {
      result = await acceptAllAssumptions(opportunityId);
    } catch {
      result = { kind: "error" };
    }
    if (result.kind === "ok") {
      await reload();
      announce(`${result.count} accepted`);
    } else {
      const sentence = failure(result);
      setMessage(sentence);
      announce(sentence);
    }
    setBusyId(null);
  }

  const rowProps = {
    canAccept,
    busyId,
    selectedId,
    onAccept: (a: Assumption) => void accept(a),
    onOpenGap,
  };
  return (
    <section
      aria-labelledby={headingId}
      data-testid="assumptions-register"
      className="flex flex-col gap-2"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h3 id={headingId} className="text-body-strong">
          Assumptions Register
        </h3>
        <p className="text-label text-muted-foreground [font-variant-numeric:tabular-nums]">
          {registerSummary(counts)}
        </p>
        {canAccept && counts.not_accepted > 0 ? (
          <button
            type="button"
            disabled={busyId !== null}
            onClick={() => void acceptAll()}
            className={cn(actionClass, "ml-auto")}
          >
            {acceptAllLabel(counts.not_accepted)}
          </button>
        ) : null}
      </div>

      {proposing ? (
        <p className="flex items-center gap-2 text-label" data-status={version.proposal_status}>
          <span
            aria-hidden="true"
            data-testid="proposing-dot"
            className="size-1.5 shrink-0 animate-pulse rounded-full bg-agent motion-reduce:animate-none"
          />
          {PROPOSING}
        </p>
      ) : version.proposal_status === "failed" || version.proposal_status === null ? (
        <div className="flex flex-wrap items-center gap-2" data-testid="proposals-failed">
          <p className="flex items-center gap-1.5 text-label text-blocker">
            <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
            {version.proposal_status === "failed" ? PROPOSALS_FAILED : PROPOSALS_MISSING}
          </p>
        </div>
      ) : null}

      {stale ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-label text-foreground">{staleMessage(stale.changedBy)}</p>
          <button
            type="button"
            onClick={() => {
              setStale(null);
              void reload();
            }}
            className={actionClass}
          >
            {RELOAD}
          </button>
        </div>
      ) : null}
      {message ? <p className="text-meta text-destructive">{message}</p> : null}

      {counts.total > 0 ? (
        <div className="flex flex-col overflow-hidden rounded-md border border-border">
          <Group
            title={CONDITIONS}
            icon={<ClipboardCheckIcon aria-hidden="true" className="size-3.5 shrink-0" />}
            items={conditions}
            {...rowProps}
          />
          <Group
            title={CONTINGENCIES}
            icon={<ShieldPlusIcon aria-hidden="true" className="size-3.5 shrink-0" />}
            items={contingencies}
            total={`${hours(contingency_hours)} h`}
            {...rowProps}
          />
        </div>
      ) : version.proposal_status === "succeeded" ? (
        <p className="text-muted-foreground">No Assumptions for this version.</p>
      ) : null}

      {unconverted.length > 0 ? (
        <div
          role="note"
          aria-labelledby={`${headingId}-unconverted`}
          className="flex flex-col gap-1.5 rounded-md border border-border p-3"
        >
          <h4 id={`${headingId}-unconverted`} className="flex items-center gap-1.5 text-label">
            <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0 text-gap" />
            {`${UNCONVERTED_GAPS} (${unconverted.length})`}
          </h4>
          <p className="text-meta text-muted-foreground">
            No Assumption was proposed for these open Gaps. Answer them, or re-draft the Estimate.
          </p>
          <ul className="flex flex-col gap-1">
            {unconverted.map((g) => (
              <li key={g.id} className="flex items-center gap-3">
                <ImpactBar impact={g.impact} />
                <span className="w-40 shrink-0 truncate text-meta text-muted-foreground">
                  {categoryLabel(g.category)}
                </span>
                <span className="min-w-0 flex-1 truncate text-body">{g.title}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/** The Gap an Assumption was made from, in the right pane, read-only: its category, title,
 * why it matters, impact and status. */
export function OriginGapInspector({
  gap,
  focusRequest = 0,
}: {
  gap: OriginGap;
  focusRequest?: number;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  const status =
    gap.status === "converted" ? "Converted" : gap.status === "open" ? "Open" : "Superseded";
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <p className="text-meta text-muted-foreground">{`Gap · ${categoryLabel(gap.category)}`}</p>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {gap.title}
        </h3>
      </div>
      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Why it matters</h4>
        <p className="whitespace-pre-wrap break-words text-body">{gap.why_it_matters}</p>
      </div>
      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Impact</h4>
        <ImpactBar impact={gap.impact} />
      </div>
      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Status</h4>
        <p className="text-body">{status}</p>
      </div>
    </section>
  );
}
