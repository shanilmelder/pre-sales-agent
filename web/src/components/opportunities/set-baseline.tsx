"use client";

import { AnchorIcon, CircleAlertIcon, CircleCheckIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import {
  loadVersionApprovers,
  setEstimateBaseline,
  type SetBaselineResult,
} from "@/app/opportunities/actions";
import { useSubmission } from "@/components/opportunities/submission-context";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Pill } from "@/components/ui/pill";
import {
  APPROVERS_FAILED,
  approvedOn,
  approveFirstReason,
  BASELINE,
  BASELINE_FAILED,
  BASELINE_FORBIDDEN,
  BASELINE_STALE,
  BASELINE_WARNING,
  baselineSetAnnouncement,
  NO_APPROVERS,
  rejectedReason,
  SET_BASELINE,
  setBaselineTitle,
  supersededReason,
  type BaselineApproval,
  type EstimateVersion,
} from "@/lib/estimates";
import { reviewTypeLabel } from "@/lib/reviews";
import { CANCEL, type Blocker } from "@/lib/submission";
import { cn } from "@/lib/utils";

/** What Set Baseline needs to know about one Estimate Version (Story 9.7): the API's view of
 * it (the Estimate tab's, the header's or the review panel's). */
export type BaselineTarget = {
  versionId: string;
  version: number;
  status: EstimateVersion["status"];
  rowVersion: number;
  /** It is the Opportunity's current Baseline. */
  isBaseline: boolean;
  /** Its blockers to Baseline (`to_baseline`, the one check). */
  toBaseline: readonly Blocker[];
  /** The caller may set the Baseline (the API's flag; no role check here). */
  canSet: boolean;
  /** The current Baseline's number, when known: an older or equal version can't replace it. */
  baselineVersion?: number | null;
};

const NOT_NEWER = "Only a newer approved Estimate Version can replace the Baseline";

/** The mockup's outline button: 13px/500, 7×14 padding, radius 8. */
const buttonClass = "h-auto rounded-lg px-3.5 py-[7px] text-control";

/** The Baseline marker (Story 9.7): a resolved-tint pill with the anchor, in place of the
 * version's status pill wherever the Baseline version is shown. */
export function BaselinePill({
  label = BASELINE,
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <Pill tone="resolved" icon={<AnchorIcon />} data-baseline-pill="" className={className}>
      {label}
    </Pill>
  );
}

/** Why Set Baseline is unavailable for `target`, or null when it may be pressed. */
export function setBaselineReason(target: BaselineTarget): string | null {
  if (target.baselineVersion != null && target.version <= target.baselineVersion)
    return NOT_NEWER;
  if (target.status === "superseded") return supersededReason(target.version);
  if (target.status === "rejected") return rejectedReason(target.version);
  if (target.toBaseline.length > 0) return target.toBaseline[0]!.title;
  if (target.status !== "approved") return approveFirstReason(target.version);
  return null;
}

type Problem =
  | { kind: "blocked"; message: string; blockers: readonly Blocker[] }
  | { kind: "stale" }
  | { kind: "text"; message: string };

function problemOf(result: Exclude<SetBaselineResult, { kind: "ok" }>): Problem {
  switch (result.kind) {
    case "blocked":
      return {
        kind: "blocked",
        message: result.detail ?? "Resolve the blockers before you can set the Baseline.",
        blockers: result.blockers,
      };
    case "not-newer":
      return { kind: "text", message: result.detail ?? NOT_NEWER };
    case "stale":
      return { kind: "stale" };
    case "forbidden":
    case "not-found":
      return { kind: "text", message: BASELINE_FORBIDDEN };
    default:
      return { kind: "text", message: BASELINE_FAILED };
  }
}

/** **Set Baseline** (Story 9.7) for a version that isn't a draft and isn't the Baseline,
 * when the API says the caller may set it. Primary, opening the confirm dialog, only when the
 * version is approved and nothing blocks it; otherwise an outline button with
 * `aria-disabled` and the reason beside it (the first blocker, or "Every requested review
 * must approve v3 first."). The dialog (480px, the mockup's) lists the approvers, warns that
 * it cannot be undone, and on Set Baseline announces "Estimate v3 is now the Baseline" and
 * refreshes the blockers and the page. A 409 lists the blockers inline; a 412 says "Changed
 * since you opened it." with Reload. */
export function SetBaseline({
  opportunityId,
  target,
  onSet,
  onReload,
  showReason = true,
  className,
}: {
  opportunityId: string;
  target: BaselineTarget;
  /** After the Baseline is set (the caller reads its view again). */
  onSet?: () => void;
  /** Reload after a 412 (the caller's own read; the page is refreshed too). */
  onReload?: () => void;
  /** Show the reason beside the unavailable button (it is always its description). */
  showReason?: boolean;
  className?: string;
}) {
  const announce = useAnnounce();
  const router = useRouter();
  const submission = useSubmission();
  const reasonId = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [approvers, setApprovers] = useState<BaselineApproval[] | null>(null);
  const [approversFailed, setApproversFailed] = useState(false);

  if (target.status === "draft" || target.isBaseline || !target.canSet) return null;
  const reason = setBaselineReason(target);

  if (reason !== null && !open)
    return (
      <span className={cn("inline-flex flex-wrap items-center gap-2", className)}>
        <Button
          type="button"
          variant="outline"
          aria-disabled="true"
          aria-describedby={reasonId}
          data-set-baseline=""
          className={cn(buttonClass, "border-border-strong bg-surface")}
          onClick={(event) => event.preventDefault()}
        >
          {SET_BASELINE}
        </Button>
        <span
          id={reasonId}
          className={cn("text-meta text-muted-foreground", !showReason && "sr-only")}
        >
          {reason}
        </span>
      </span>
    );

  async function readApprovers() {
    setApproversFailed(false);
    try {
      const result = await loadVersionApprovers({ opportunityId, versionId: target.versionId });
      if (result.kind === "ok") {
        setApprovers(result.approvers);
        return;
      }
    } catch {
      // Said below.
    }
    setApproversFailed(true);
  }

  function changeOpen(next: boolean) {
    setOpen(next);
    if (next) {
      setApprovers(null);
      void readApprovers();
    } else setProblem(null);
  }

  async function confirm() {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    let result: SetBaselineResult;
    try {
      result = await setEstimateBaseline({
        opportunityId,
        versionId: target.versionId,
        rowVersion: target.rowVersion,
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      setOpen(false);
      announce(baselineSetAnnouncement(result.baseline.version));
      void submission?.refresh();
      onSet?.();
      router.refresh();
      return;
    }
    const next = problemOf(result);
    setProblem(next);
    announce(next.kind === "stale" ? BASELINE_STALE : next.message);
    if (result.kind !== "error") void submission?.refresh();
  }

  function reload() {
    setOpen(false);
    setProblem(null);
    void submission?.refresh();
    onReload?.();
    router.refresh();
  }

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <Button
        type="button"
        data-set-baseline=""
        className={cn(buttonClass, className)}
        onClick={() => changeOpen(true)}
      >
        {SET_BASELINE}
      </Button>
      <DialogContent showCloseButton={false} className="w-[480px]">
        <DialogHeader>
          <DialogTitle className="text-[20px] leading-7 font-semibold">
            {setBaselineTitle(target.version)}
          </DialogTitle>
        </DialogHeader>
        <section aria-labelledby={`${reasonId}-approvers`} className="flex flex-col gap-2">
          <h3 id={`${reasonId}-approvers`} className="text-muted-foreground uppercase">
            <span className="text-eyebrow">Approvers</span>
          </h3>
          {approvers === null ? (
            <p className="text-meta text-muted-foreground">
              {approversFailed ? APPROVERS_FAILED : "Loading the approvers…"}
            </p>
          ) : approvers.length === 0 ? (
            <p className="text-meta text-muted-foreground">{NO_APPROVERS}</p>
          ) : (
            <ul className="flex flex-col gap-2" data-approvers="">
              {approvers.map((a) => (
                <li
                  key={a.decision_id ?? `${a.name}-${a.review_type}`}
                  className="flex items-center gap-2.5"
                >
                  <span className="min-w-0 flex-1 break-words">
                    {`${a.name} · ${reviewTypeLabel(a.review_type)} review`}
                  </span>
                  {a.status === "approved" ? (
                    <Pill tone="resolved" icon={<CircleCheckIcon />}>
                      {approvedOn(a.decided_at)}
                    </Pill>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>
        <p
          className="flex items-start gap-2.5 rounded-[10px] bg-gap-tint px-3.5 py-2.5 text-control text-gap"
          data-baseline-warning=""
        >
          <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {BASELINE_WARNING}
        </p>
        {problem?.kind === "stale" ? (
          <InlineAlert lead={BASELINE_STALE} onReload={reload} />
        ) : problem ? (
          <div
            role="alert"
            className="flex flex-col gap-1.5 rounded-md border border-blocker/30 bg-blocker-tint px-3 py-2 text-blocker"
          >
            <p className="flex items-center gap-1.5 text-body-strong">
              <CircleAlertIcon aria-hidden="true" className="size-4 shrink-0" />
              {problem.message}
            </p>
            {problem.kind === "blocked" && problem.blockers.length > 0 ? (
              <ul className="flex list-disc flex-col gap-0.5 pl-6 text-meta">
                {problem.blockers.map((b) => (
                  <li key={`${b.kind}-${b.subject_id}`}>
                    <Link href={b.href} className="underline-offset-2 hover:underline">
                      {b.title}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" className={buttonClass} />}>
            {CANCEL}
          </DialogClose>
          <Button
            type="button"
            className={buttonClass}
            disabled={busy}
            onClick={() => void confirm()}
          >
            {SET_BASELINE}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
