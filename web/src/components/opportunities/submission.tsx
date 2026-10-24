"use client";

import { CircleAlertIcon, CircleCheckIcon, ClockIcon, SendIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState, type ReactNode } from "react";

import { submitEstimateVersion } from "@/app/opportunities/actions";
import { useSubmission } from "@/components/opportunities/submission-context";
import { useAnnounce } from "@/components/shell/live-region";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Pill } from "@/components/ui/pill";
import {
  BLOCKERS_CARD_ID,
  BLOCKERS_LOAD_FAILED,
  blockersAnnouncement,
  blockersCardHref,
  blockersPillLabel,
  CANCEL,
  groupBlockers,
  NO_REVIEW_REQUESTS,
  NOTHING_YET,
  READY_BODY,
  READY_TITLE,
  resolveLabel,
  resolveToSubmitLabel,
  SUBMIT,
  SUBMIT_DESCRIPTION,
  SUBMIT_FAILED,
  SUBMIT_FORBIDDEN,
  SUBMIT_NOT_DRAFT,
  SUBMIT_STALE,
  submitTitle,
  submittedAnnouncement,
  submittedBanner,
  type Blocker,
  type SubmissionBlockers,
  type SubmissionBlockersView,
} from "@/lib/submission";
import { cn } from "@/lib/utils";
import { tabHref } from "@/lib/workspace";

// --- Submit ----------------------------------------------------------------------------------

/** **Submit** for the current draft: primary and opening the confirm dialog ("Submit Estimate
 * v3?" / "Submitted versions can't be edited.") when nothing blocks; while blockers remain, an
 * outline button with `aria-disabled` and "Resolve N blockers to submit" beside it. A 409
 * shows an inline alert listing the blockers and reads them again. Nothing when the caller
 * may not submit or the current version is not a draft. */
export function SubmitEstimate({
  opportunityId,
  view,
  onSubmitted,
  showReason = true,
}: {
  opportunityId: string;
  view: SubmissionBlockersView | null;
  /** Runs after a successful submission (the provider's refresh, a router refresh). */
  onSubmitted?: () => void;
  /** Show "Resolve N blockers to submit" beside the disabled button. */
  showReason?: boolean;
}) {
  const announce = useAnnounce();
  const router = useRouter();
  const submission = useSubmission();
  const reasonId = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<{ message: string; blockers: Blocker[] } | null>(null);

  const version = view?.version ?? null;
  if (!view || !version || version.status !== "draft" || !view.can_submit) return null;
  const count = view.to_submit.length;

  // An open dialog stays (e.g. to show a refused submission) even once blockers reappear.
  if (count > 0 && !open)
    return (
      <span className="inline-flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          aria-disabled="true"
          aria-describedby={reasonId}
          data-submit=""
          onClick={(event) => event.preventDefault()}
        >
          <SendIcon aria-hidden="true" />
          {SUBMIT}
        </Button>
        <span
          id={reasonId}
          className={cn("text-meta text-muted-foreground", !showReason && "sr-only")}
        >
          {resolveToSubmitLabel(count)}
        </span>
      </span>
    );

  async function confirm() {
    if (!version) return;
    setBusy(true);
    setProblem(null);
    let result: Awaited<ReturnType<typeof submitEstimateVersion>>;
    try {
      result = await submitEstimateVersion({
        opportunityId,
        versionId: version.id,
        rowVersion: version.row_version,
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      setOpen(false);
      announce(submittedAnnouncement(result.version.version));
      void submission?.refresh();
      onSubmitted?.();
      router.refresh();
      return;
    }
    const message =
      result.kind === "blocked"
        ? (result.detail ?? blockersAnnouncement(result.blockers?.to_submit.length ?? 0))
        : result.kind === "stale"
          ? SUBMIT_STALE
          : result.kind === "not-draft"
            ? SUBMIT_NOT_DRAFT
            : result.kind === "forbidden" || result.kind === "not-found"
              ? SUBMIT_FORBIDDEN
              : SUBMIT_FAILED;
    setProblem({
      message,
      blockers: result.kind === "blocked" ? (result.blockers?.to_submit ?? []) : [],
    });
    announce(message);
    if (result.kind !== "error") void submission?.refresh();
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setProblem(null);
      }}
    >
      <Button type="button" data-submit="" onClick={() => setOpen(true)}>
        <SendIcon aria-hidden="true" />
        {SUBMIT}
      </Button>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{submitTitle(version.version)}</DialogTitle>
          <DialogDescription>{SUBMIT_DESCRIPTION}</DialogDescription>
        </DialogHeader>
        {problem ? (
          <div
            role="alert"
            className="flex flex-col gap-1.5 rounded-md border border-blocker/30 bg-blocker-tint px-3 py-2 text-blocker"
          >
            <p className="flex items-center gap-1.5 text-body-strong">
              <CircleAlertIcon aria-hidden="true" className="size-4 shrink-0" />
              {problem.message}
            </p>
            {problem.blockers.length > 0 ? (
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
          <DialogClose render={<Button variant="outline" />}>{CANCEL}</DialogClose>
          <Button type="button" disabled={busy} onClick={() => void confirm()}>
            {SUBMIT}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The workspace header's actions (both header variants): Submit, and while blockers remain a
 * primary **Resolve N blockers** that opens the Overview's Submission blockers card. Nothing
 * for those who may not submit. Reads the shared blockers. */
export function SubmissionHeaderActions() {
  const submission = useSubmission();
  if (!submission) return null;
  const { view, opportunityId } = submission;
  if (!view?.version || view.version.status !== "draft" || !view.can_submit) return null;
  const count = view.to_submit.length;
  return (
    <div className="ml-auto flex flex-wrap items-center gap-2" data-submission-actions="">
      <SubmitEstimate opportunityId={opportunityId} view={view} />
      {count > 0 ? (
        <Link
          href={blockersCardHref(opportunityId)}
          className={`${buttonVariants({ variant: "default" })} text-control`}
        >
          {resolveLabel(count)}
        </Link>
      ) : null}
    </div>
  );
}

// --- the Overview card -----------------------------------------------------------------------

const linkClass =
  "rounded-sm text-control text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary";

/** The Overview's Submission blockers card (Story 8.6, the new mockup), from the one check:
 * a count pill ("3 to submit · 0 to Baseline" in the blocker tone, "0 blockers" resolved), the
 * "Blockers to submit · N" group with one blocker-tint row per kind ("3 open Gaps", its meta
 * line and tab action) listing each subject as a link to it, and the "Blockers to Baseline ·
 * 0" group ("No Review Requests yet"). When nothing blocks a draft: a centred check, "0
 * blockers — ready to submit". Follows the shared live blockers when a provider is above;
 * `initial` otherwise. */
export function SubmissionBlockersCard({
  opportunityId,
  initial,
}: {
  opportunityId: string;
  initial: SubmissionBlockersView | null;
}) {
  const submission = useSubmission();
  const view = submission ? submission.view : initial;
  return (
    <Card role="region" aria-labelledby={BLOCKERS_CARD_ID} className="min-w-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-[18px]">
        <h3 id={BLOCKERS_CARD_ID} className="min-w-0 flex-1 scroll-mt-4 text-section">
          Submission blockers
        </h3>
        {view ? <BlockersPill view={view} /> : null}
      </div>
      {view === null ? (
        <p className="px-5 py-4">{BLOCKERS_LOAD_FAILED}</p>
      ) : (
        <BlockersBody opportunityId={opportunityId} view={view} />
      )}
    </Card>
  );
}

function BlockersPill({ view }: { view: SubmissionBlockers }) {
  const blocked = view.to_submit.length + view.to_baseline.length > 0;
  return (
    <Pill
      tone={blocked ? "blocker" : "resolved"}
      icon={blocked ? <CircleAlertIcon /> : <CircleCheckIcon />}
      data-blockers-pill=""
    >
      {blockersPillLabel(view)}
    </Pill>
  );
}

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <h4 className="px-5 pt-3 pb-1.5 text-muted-foreground uppercase">
      <span className="text-eyebrow">{children}</span>
    </h4>
  );
}

function BlockersBody({
  opportunityId,
  view,
}: {
  opportunityId: string;
  view: SubmissionBlockersView;
}) {
  const groups = groupBlockers(view.to_submit);
  const ready = view.to_submit.length === 0 && view.to_baseline.length === 0;
  if (ready && view.version?.status === "draft")
    return (
      <div className="flex flex-col items-center gap-1.5 px-4 py-8 text-center" data-ready="">
        <CircleCheckIcon aria-hidden="true" className="size-8 text-resolved" />
        <p className="text-section text-resolved">{READY_TITLE}</p>
        <p className="text-meta text-muted-foreground">{READY_BODY}</p>
      </div>
    );
  if (ready && !view.version)
    return <p className="px-5 py-4 text-muted-foreground">{NOTHING_YET}</p>;
  const status = view.version?.status;
  if (view.version && (status === "submitted" || status === "in_review"))
    // Story 9.1: a submitted (or in-review) version has passed the submit gate; its open
    // Review Requests are what stands between it and the Baseline.
    return (
      <div className="flex flex-col pb-3">
        <div className="flex flex-col items-center gap-1.5 px-4 py-6 text-center" data-submitted="">
          <CircleCheckIcon aria-hidden="true" className="size-8 text-resolved" />
          <p className="text-section text-resolved">
            {submittedBanner(view.version.version, view.version.submitted_at)}
          </p>
          <p className="text-meta text-muted-foreground">{SUBMIT_DESCRIPTION}</p>
        </div>
        <BaselineGroup blockers={view.to_baseline} />
      </div>
    );
  return (
    <div className="flex flex-col pb-3">
      <section aria-label={`Blockers to submit · ${view.to_submit.length}`}>
        <Eyebrow>{`Blockers to submit · ${view.to_submit.length}`}</Eyebrow>
        {groups.length > 0 ? (
          <ul className="flex flex-col">
            {groups.map((group) => (
              <li
                key={group.kind}
                data-blocker={group.kind}
                className="flex items-start gap-3 border-t border-border bg-blocker-tint px-5 py-3"
              >
                <CircleAlertIcon
                  aria-hidden="true"
                  className="mt-0.5 size-4 shrink-0 text-blocker"
                />
                <div className="min-w-0 flex-1">
                  <div className="text-body-strong">{group.title}</div>
                  <div className="text-meta text-muted-foreground">{group.meta}</div>
                  <ul className="mt-1 flex flex-col gap-0.5">
                    {group.items.map((b) => (
                      <li key={b.subject_id} className="min-w-0 truncate text-meta">
                        <Link href={b.href} className={linkClass} title={b.detail}>
                          {b.title}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
                <Link href={tabHref(opportunityId, group.tab)} className={linkClass}>
                  {group.action}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="flex items-center gap-2 px-5 py-2 text-meta text-resolved">
            <CircleCheckIcon aria-hidden="true" className="size-4 shrink-0" />
            Nothing blocks submission.
          </p>
        )}
      </section>
      <BaselineGroup blockers={view.to_baseline} />
    </div>
  );
}

/** The "Blockers to Baseline · N" group (Story 9.1): one mockup row per open Review Request
 * (its title, "Engineering review · Ana · Pending", linking to the request's row on the
 * Estimate tab, and the meta "Sent 24 Oct · message excerpt"), or "No Review Request sent
 * yet". */
function BaselineGroup({ blockers }: { blockers: Blocker[] }) {
  return (
    <section aria-label={`Blockers to Baseline · ${blockers.length}`}>
      <Eyebrow>{`Blockers to Baseline · ${blockers.length}`}</Eyebrow>
      {blockers.length === 0 ? (
        <p className="flex items-center gap-2 px-5 py-2 text-meta text-muted-foreground">
          <ClockIcon aria-hidden="true" className="size-4 shrink-0 text-gap" />
          {NO_REVIEW_REQUESTS}
        </p>
      ) : (
        <ul className="flex flex-col">
          {blockers.map((b) => (
            <li
              key={b.subject_id}
              data-blocker={b.kind}
              className="flex items-start gap-3 border-t border-border px-5 py-3"
            >
              <ClockIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-gap" />
              <div className="min-w-0 flex-1">
                <Link href={b.href} className={cn(linkClass, "text-body-strong")}>
                  {b.title}
                </Link>
                <div className="text-meta text-muted-foreground">{b.detail}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
