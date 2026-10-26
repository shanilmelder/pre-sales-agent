"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { cancelReviewRequest } from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
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
import { Textarea } from "@/components/ui/textarea";
import { codePointLength } from "@/lib/opportunities";
import {
  CANCEL_FAILED,
  CANCEL_FORBIDDEN,
  CANCEL_REASON_LABEL,
  CANCEL_REASON_MAX,
  CANCEL_REQUEST,
  CANCEL_STALE,
  CANCELLED_ANNOUNCEMENT,
  KEEP_REQUEST,
  NO_REQUESTS,
  REASON_REQUIRED,
  REQUEST_STATUSES,
  REVIEW_REQUESTS_TITLE,
  DECISION_STYLES,
  decisionLine,
  reviewRowId,
  reviewTypeLabel,
  sentLabel,
  type RequestStatus,
  type ReviewRequest,
} from "@/lib/reviews";

/** A Review Request's status: an icon and a label in its tone, never colour alone. */
export function RequestStatusPill({ status }: { status: RequestStatus }) {
  const info = REQUEST_STATUSES[status];
  const Icon = info.icon;
  return (
    <Pill tone={info.tone} icon={<Icon />} data-request-status={status} className="shrink-0">
      {info.label}
    </Pill>
  );
}

/** "Cancel the Engineering review request?". */
function cancelTitle(request: ReviewRequest): string {
  return `Cancel the ${reviewTypeLabel(request.review_type)} review request?`;
}

/** "Ana Ruiz will no longer be asked to review Estimate v3.". */
function cancelDescription(request: ReviewRequest): string {
  return `${request.reviewer.name} will no longer be asked to review ${request.target.label}.`;
}

/** **Cancel request** and its confirm dialog with a required reason (1 to 1,000 characters).
 * A 4xx shows inline; a cancel announces "Review request cancelled". */
function CancelRequest({
  opportunityId,
  request,
  onCancelled,
}: {
  opportunityId: string;
  request: ReviewRequest;
  onCancelled: () => void;
}) {
  const announce = useAnnounce();
  const reasonId = useId();
  const ruleId = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const length = codePointLength(reason.trim());
  const reasonOk = length >= 1 && length <= CANCEL_REASON_MAX;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
    if (busy || !reasonOk) return;
    setBusy(true);
    setProblem(null);
    let result: Awaited<ReturnType<typeof cancelReviewRequest>>;
    try {
      result = await cancelReviewRequest({
        opportunityId,
        requestId: request.id,
        rowVersion: request.row_version,
        reason: reason.trim(),
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      setOpen(false);
      announce(CANCELLED_ANNOUNCEMENT);
      onCancelled();
      return;
    }
    const sentence =
      result.kind === "invalid"
        ? result.detail
        : result.kind === "stale"
          ? CANCEL_STALE
          : result.kind === "forbidden" || result.kind === "not-found"
            ? CANCEL_FORBIDDEN
            : CANCEL_FAILED;
    setProblem(sentence);
    announce(sentence);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setReason("");
          setProblem(null);
          setTouched(false);
        }
      }}
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={`${CANCEL_REQUEST} to ${request.reviewer.name}`}
        onClick={() => setOpen(true)}
      >
        {CANCEL_REQUEST}
      </Button>
      <DialogContent showCloseButton={false}>
        <form noValidate onSubmit={(event) => void submit(event)} className="flex flex-col gap-3.5">
          <DialogHeader>
            <DialogTitle>{cancelTitle(request)}</DialogTitle>
            <DialogDescription>{cancelDescription(request)}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1">
            <label htmlFor={reasonId} className="text-label">
              {CANCEL_REASON_LABEL}
            </label>
            <Textarea
              id={reasonId}
              rows={3}
              value={reason}
              disabled={busy}
              aria-invalid={touched && !reasonOk ? true : undefined}
              aria-describedby={touched && !reasonOk ? ruleId : undefined}
              onChange={(event) => setReason(event.target.value)}
            />
            {touched && !reasonOk ? (
              <p id={ruleId} className="text-meta text-destructive">
                {REASON_REQUIRED}
              </p>
            ) : null}
          </div>
          {problem ? (
            <p
              role="alert"
              className="rounded-md border border-blocker/30 bg-blocker-tint px-3 py-2 text-meta text-blocker"
            >
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              {KEEP_REQUEST}
            </DialogClose>
            <Button type="submit" variant="destructive" disabled={busy}>
              {CANCEL_REQUEST}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** A request's status on the card (Story 9.3): its latest decision while it is still pending
 * (Evidence requested, Alternative requested, Escalated), else its status. */
function RequestStatus({ request }: { request: ReviewRequest }) {
  const latest = request.latest_decision;
  if (latest && request.status === "pending") {
    const style = DECISION_STYLES[latest.decision];
    const Icon = style.icon;
    return (
      <Pill
        tone={style.tone}
        icon={<Icon />}
        data-request-status={request.status}
        data-decision={latest.decision}
        className="shrink-0"
      >
        {style.label}
      </Pill>
    );
  }
  return <RequestStatusPill status={request.status} />;
}

/** The `?review={id}` of the page's URL, if any (read in the browser only). */
export function linkedReview(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("review");
}

/** The Estimate tab's **Review requests** card (Story 9.1), below the Version lifecycle card:
 * one row per request with the reviewer, the review type, the target, the status pill (icon
 * and label), when it was sent and the message, and **Cancel request** for its sender while
 * it is pending (`can_cancel`, the API's decision). `?review={id}` scrolls to that row and
 * highlights it. "No Review Request sent yet" when there is none. Story 9.3: the status
 * shows the latest decision ("{who} · {decision} · {when}" and its reason under it), and
 * clicking a row (`onOpen`) opens its review panel in the Inspector. */
export function ReviewRequestsCard({
  opportunityId,
  items,
  onChanged,
  onOpen,
  selectedId = null,
}: {
  opportunityId: string;
  items: ReviewRequest[];
  /** Runs after a cancel (the tab reads the Estimate and the requests again). */
  onChanged: () => void;
  /** Opens the request's review panel; `viaKeyboard` when opened with Enter or Space. */
  onOpen?: (request: ReviewRequest, viaKeyboard: boolean) => void;
  /** The request whose panel is open. */
  selectedId?: string | null;
}) {
  const headingId = useId();

  /** The linked id already scrolled to and focused: a live reload only re-highlights. */
  const handled = useRef<string | null>(null);

  // `?review={id}`: highlight that row (a DOM attribute, set again after every reload in case
  // the row was re-created) and, once per linked id, scroll to it and focus it.
  useEffect(() => {
    const wanted = linkedReview();
    if (!wanted) return;
    const row = document.getElementById(reviewRowId(wanted));
    if (!row) return;
    row.setAttribute("data-highlighted", "");
    if (handled.current === wanted) return;
    handled.current = wanted;
    row.scrollIntoView?.({ block: "center" });
    row.focus({ preventScroll: true });
  }, [items]);

  return (
    <Card role="region" aria-labelledby={headingId} data-review-requests="" className="gap-0">
      <div className="flex items-center gap-2 border-b border-border px-5 py-[18px]">
        <h3 id={headingId} className="flex-1 text-section">
          {REVIEW_REQUESTS_TITLE}
        </h3>
        <span className="text-meta text-muted-foreground">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="px-5 py-4 text-meta text-muted-foreground">{NO_REQUESTS}</p>
      ) : (
        <ul className="flex flex-col">
          {items.map((request) => (
            <li
              key={request.id}
              id={reviewRowId(request.id)}
              tabIndex={-1}
              data-review-row={request.id}
              data-selected={selectedId === request.id ? "" : undefined}
              className={
                "flex flex-wrap items-start gap-3 border-t border-border px-5 py-3 outline-none " +
                "first:border-t-0 focus-visible:ring-2 focus-visible:ring-primary " +
                "data-[highlighted]:bg-primary-tint data-[selected]:bg-primary-tint"
              }
            >
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex flex-wrap items-center gap-2">
                  {onOpen ? (
                    <button
                      type="button"
                      data-open-review={request.id}
                      aria-current={selectedId === request.id ? "true" : undefined}
                      // A keyboard-activated click has no pointer clicks (detail 0).
                      onClick={(event) => onOpen(request, event.detail === 0)}
                      className="rounded-sm text-left text-body-strong text-primary-text outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
                    >
                      {request.reviewer.name}
                      <span className="sr-only">{`: open the ${request.target.label} review`}</span>
                    </button>
                  ) : (
                    <span className="text-body-strong">{request.reviewer.name}</span>
                  )}
                  <span className="text-meta text-muted-foreground">
                    {`${reviewTypeLabel(request.review_type)} review · ${request.target.label}`}
                  </span>
                  <RequestStatus request={request} />
                </div>
                <p className="text-meta text-muted-foreground">
                  <time dateTime={request.created_at}>{sentLabel(request.created_at)}</time>
                  {` by ${request.requested_by.name}`}
                </p>
                {request.message ? (
                  <p className="whitespace-pre-wrap break-words text-body">{request.message}</p>
                ) : null}
                {request.latest_decision ? (
                  <div className="flex flex-col" data-latest-decision="">
                    <p className="text-meta text-muted-foreground">
                      {decisionLine(request.latest_decision)}
                    </p>
                    {request.latest_decision.reason ? (
                      <p className="whitespace-pre-wrap break-words text-meta">
                        {request.latest_decision.reason}
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {request.status === "cancelled" && request.cancel_reason ? (
                  <p className="text-meta text-muted-foreground">
                    {`Cancelled: ${request.cancel_reason}`}
                  </p>
                ) : null}
              </div>
              {request.can_cancel ? (
                <CancelRequest
                  opportunityId={opportunityId}
                  request={request}
                  onCancelled={onChanged}
                />
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
