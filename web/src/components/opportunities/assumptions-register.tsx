"use client";

import {
  CircleAlertIcon,
  CircleCheckIcon,
  ClipboardCheckIcon,
  LoaderCircleIcon,
  ShieldPlusIcon,
} from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import {
  acceptAllAssumptions,
  acceptAssumption,
  loadEstimate,
  type AcceptAllAssumptionsResult,
  type AssumptionAcceptResult,
} from "@/app/opportunities/actions";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { ACCEPT } from "@/components/opportunities/assumption-inspector";
import { OriginText } from "@/components/opportunities/estimate-item-parts";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Pill } from "@/components/ui/pill";
import { ImpactBar } from "@/components/opportunities/impact-bar";
import { useAnnounce } from "@/components/shell/live-region";
import {
  acceptAllLabel,
  acceptedLabel,
  assumptionId,
  assumptionLabel,
  carriedLabel,
  CONDITIONS,
  CONTINGENCIES,
  hours,
  isProposing,
  NOT_ACCEPTED,
  PROPOSALS_FAILED,
  PROPOSALS_MISSING,
  PROPOSING,
  registerStatus,
  staleMessage,
  UNCONVERTED_GAPS,
  type Assumption,
  type EstimateVersion,
  type EstimateView,
  type OriginGap,
} from "@/lib/estimates";
import { categoryLabel } from "@/lib/gaps";
import { cn } from "@/lib/utils";

export { ACCEPT };
export const RELOAD = "Reload";
const ACCEPT_FAILED = "The Assumption could not be accepted. Try again.";
const ACCEPT_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can accept Assumptions.";
const GAP_NOT_OPEN =
  "Its Gap is no longer open: it was dismissed, converted or replaced by a newer Gap detection. Reload to see the latest.";
const GONE = "This Assumption is no longer in the current draft. Reload to see the latest.";

export function acceptFailure(
  result: AssumptionAcceptResult | AcceptAllAssumptionsResult,
): string {
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

/** One Assumption as a Register row (Story 8.5 anatomy): its `A{n}` ID chip and wording (a
 * button that opens the Assumption inspector; a click anywhere on the row does too), then a
 * muted "{Condition | Contingency · N.N h} · from {Gap | Unknown}: {title}" (the chip opens the
 * origin Gap in the inspector; a superseded origin is struck through and labelled), the linked
 * line, and its status. An unaccepted row is a blocker row: blocker tint, a 2px blocker bar and
 * a red "Not accepted" with an alert icon (never colour alone), with **Accept** for those who
 * may accept. An accepted row reads, in green with a check, "Accepted by {name} · {date}". */
function AssumptionRow({
  assumption,
  canAccept,
  busy,
  selected,
  gapSelected,
  onAccept,
  onOpen,
  onOpenGap,
}: {
  assumption: Assumption;
  canAccept: boolean;
  busy: boolean;
  /** The Assumption is open in the inspector. */
  selected: boolean;
  /** Its origin Gap is open in the inspector. */
  gapSelected: boolean;
  onAccept: (assumption: Assumption) => void;
  onOpen?: (assumption: Assumption, viaKeyboard: boolean) => void;
  onOpenGap: (assumption: Assumption, viaKeyboard: boolean) => void;
}) {
  const accepted = assumption.accepted_at !== null;
  const carried = carriedLabel(assumption);
  return (
    <li
      data-assumption-id={assumption.id}
      data-blocker={accepted ? undefined : ""}
      data-selected={selected ? "" : undefined}
      onClick={(event) => {
        // A click on the row opens it, except on its own buttons (Accept, the origin chip).
        const target = event.target as HTMLElement;
        if (target.closest("button")) return;
        onOpen?.(assumption, false);
      }}
      className={cn(
        "flex flex-wrap items-start gap-x-4 gap-y-2 border-b border-border px-5 py-3",
        onOpen ? "cursor-pointer" : "",
        selected
          ? "bg-primary-tint"
          : accepted
            ? ""
            : "bg-blocker-tint shadow-[inset_2px_0_0_var(--blocker)]",
        selected && !accepted ? "shadow-[inset_2px_0_0_var(--blocker)]" : "",
      )}
    >
      <div className="flex min-w-0 flex-1 basis-72 items-start gap-3">
        <Chip className="mt-0.5 shrink-0 px-1.5 py-0" data-assumption-label="">
          {assumptionId(assumption)}
        </Chip>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {onOpen ? (
            <button
              type="button"
              data-open-assumption=""
              aria-pressed={selected}
              onClick={(event) => onOpen(assumption, event.detail === 0)}
              className="w-fit rounded-sm text-left break-words text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              {assumption.wording}
            </button>
          ) : (
            <p className="break-words text-body">{assumption.wording}</p>
          )}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
            <span className="flex min-w-0 items-center gap-1">
              <span className="text-meta">{`${assumptionLabel(assumption)} ·`}</span>
              <button
                type="button"
                data-gap-chip=""
                aria-pressed={gapSelected}
                onClick={(event) => onOpenGap(assumption, event.detail === 0)}
                className={cn(
                  "max-w-80 truncate rounded-sm text-left underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary",
                  gapSelected ? "text-foreground underline" : "text-primary-text",
                )}
              >
                <OriginText item={assumption} />
              </button>
            </span>
            {assumption.line ? (
              <span className="min-w-0 truncate text-meta">{`Line: ${assumption.line.title}`}</span>
            ) : null}
            {carried ? <span className="text-meta">{carried}</span> : null}
          </div>
        </div>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-3">
        {accepted ? (
          <span className="flex items-center gap-1 text-resolved">
            <CircleCheckIcon aria-hidden="true" className="size-3.5 shrink-0" />
            <span className="text-label">{acceptedLabel(assumption)}</span>
          </span>
        ) : (
          <>
            <span className="flex items-center gap-1 text-blocker">
              <CircleAlertIcon aria-hidden="true" className="size-3.5 shrink-0" />
              <span className="text-label">{NOT_ACCEPTED}</span>
            </span>
            {canAccept ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => onAccept(assumption)}
                aria-label={`${ACCEPT}: ${assumption.wording}`}
              >
                {ACCEPT}
              </Button>
            ) : null}
          </>
        )}
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
  selectedAssumptionId: string | null;
  onAccept: (assumption: Assumption) => void;
  onOpen?: (assumption: Assumption, viaKeyboard: boolean) => void;
  onOpenGap: (assumption: Assumption, viaKeyboard: boolean) => void;
}) {
  const headingId = useId();
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="flex flex-col">
      <h4
        id={headingId}
        className="flex h-8 items-center gap-1.5 border-b border-border bg-background px-5 text-muted-foreground uppercase"
      >
        {icon}
        <span className="text-eyebrow">{title}</span>
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
            selected={assumption.id === row.selectedAssumptionId}
            gapSelected={assumption.id === row.selectedId}
            onAccept={row.onAccept}
            onOpen={row.onOpen}
            onOpenGap={row.onOpenGap}
          />
        ))}
      </ul>
    </section>
  );
}

/** The Assumptions Register card below the grid (Story 8.4 + 8.5, minimal): the version's
 * Conditions and Contingencies (with their total), each with its wording, hours, a "from Gap"
 * link that opens the Gap in the inspector, its linked line and who accepted it; the header
 * with a red "{n} not accepted block submit" pill (or green "All accepted") and **Accept all
 * (N)**; and an "Unconverted Gaps"
 * note for open Gaps with no proposal. After every accept the Estimate is read again, so the
 * grid's Contingency column and totals come from the server. Read-only without
 * `canAccept`. Proposals that failed or are missing are said so, with no re-draft Retry
 * (Story 8.3: the Estimate is built from the Assessments). */
export function AssumptionsRegister({
  opportunityId,
  version,
  canAccept,
  selectedId = null,
  selectedAssumptionId = null,
  onChanged,
  onOpen,
  onOpenGap,
}: {
  opportunityId: string;
  version: EstimateVersion;
  /** Whether Accept and Accept all are offered (a draft version, and the caller may accept). */
  canAccept: boolean;
  /** The Assumption whose Gap is open in the inspector. */
  selectedId?: string | null;
  /** The Assumption open in the inspector (Story 8.5). */
  selectedAssumptionId?: string | null;
  /** The Estimate as read again after an accept or a Reload. */
  onChanged: (estimate: EstimateView) => void;
  /** Open the Assumption in the inspector (Story 8.5). */
  onOpen?: (assumption: Assumption, viaKeyboard: boolean) => void;
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
      const sentence = acceptFailure(result);
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
      const sentence = acceptFailure(result);
      setMessage(sentence);
      announce(sentence);
    }
    setBusyId(null);
  }

  const rowProps = {
    canAccept,
    busyId,
    selectedId,
    selectedAssumptionId,
    onAccept: (a: Assumption) => void accept(a),
    onOpen,
    onOpenGap,
  };
  const status = registerStatus(counts);
  const failedProposals =
    version.proposal_status === "failed" || version.proposal_status === null;
  return (
    <Card
      role="region"
      aria-labelledby={headingId}
      data-testid="assumptions-register"
      className="overflow-hidden"
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-4">
        <h3 id={headingId} className="text-section">
          Assumptions Register
        </h3>
        {counts.total > 0 ? (
          <Pill
            tone={status.tone}
            data-register-status=""
            icon={status.tone === "blocker" ? <CircleAlertIcon /> : <CircleCheckIcon />}
          >
            {status.label}
          </Pill>
        ) : null}
        {canAccept && counts.not_accepted > 0 ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busyId !== null}
            onClick={() => void acceptAll()}
            className="ml-auto"
          >
            {acceptAllLabel(counts.not_accepted)}
          </Button>
        ) : null}
      </div>

      {proposing || failedProposals || stale || message ? (
        <div className="flex flex-col gap-2 border-b border-border px-5 py-3">
          {proposing ? (
            <p className="flex items-center gap-2 text-label" data-status={version.proposal_status}>
              <LoaderCircleIcon
                aria-hidden="true"
                data-testid="proposing-dot"
                className="size-3 shrink-0 text-agent"
              />
              {PROPOSING}
            </p>
          ) : failedProposals ? (
            <div className="flex flex-wrap items-center gap-2" data-testid="proposals-failed">
              <p className="flex items-center gap-1.5 text-label text-blocker">
                <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
                {version.proposal_status === "failed" ? PROPOSALS_FAILED : PROPOSALS_MISSING}
              </p>
            </div>
          ) : null}
          {stale ? (
            <InlineAlert
              lead={staleMessage(stale.changedBy)}
              onReload={() => {
                setStale(null);
                void reload();
              }}
            />
          ) : null}
          {message ? <p className="text-meta text-destructive">{message}</p> : null}
        </div>
      ) : null}

      {counts.total > 0 ? (
        <div className="flex flex-col">
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
        <p className="px-5 py-4 text-muted-foreground">No Assumptions for this version.</p>
      ) : null}

      {unconverted.length > 0 ? (
        <div
          role="note"
          aria-labelledby={`${headingId}-unconverted`}
          className="flex flex-col gap-1.5 px-5 py-3"
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
    </Card>
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
