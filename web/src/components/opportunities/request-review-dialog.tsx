"use client";

import { CheckIcon, ChevronsUpDownIcon, UserCheckIcon, XIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { requestReview, searchReviewerCandidates } from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { codePointLength, type UserSummary } from "@/lib/opportunities";
import {
  ASSESSMENTS_HELP,
  ASSESSMENTS_LABEL,
  CANCEL,
  MESSAGE_LABEL,
  MESSAGE_MAX,
  MESSAGE_TOO_LONG,
  REQUEST_FAILED,
  REQUEST_FORBIDDEN,
  REQUEST_REVIEW,
  REQUEST_STALE,
  requestCount,
  requestedAnnouncement,
  requestReviewTitle,
  REVIEW_TYPE_LABEL,
  REVIEW_TYPES,
  REVIEWERS_EMPTY,
  REVIEWERS_LABEL,
  REVIEWERS_NOT_LOADED,
  REVIEWERS_PLACEHOLDER,
  REVIEWERS_SEARCH,
  sendLabel,
  type AssessmentOption,
  type CreatedReviewRequests,
  type ReviewType,
} from "@/lib/reviews";
import { cn } from "@/lib/utils";

const SEARCH_DELAY_MS = 200;

/** The Reviewers combobox (Popover + Command, like the Evidence picker): the people who hold
 * the review type's role, as the API lists them (minus the version's author), searched on the
 * server as you type and read again when the type changes; each chosen one shows a check and
 * `aria-checked`, and a removable chip. */
function ReviewerPicker({
  opportunityId,
  reviewType,
  chosen,
  onChange,
  disabled,
}: {
  opportunityId: string;
  reviewType: ReviewType;
  chosen: UserSummary[];
  onChange: (chosen: UserSummary[]) => void;
  disabled: boolean;
}) {
  const labelId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<UserSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const reads = useRef(0);
  const chosenIds = new Set(chosen.map((u) => u.id));

  useEffect(() => {
    if (!open) return;
    const started = ++reads.current;
    const timer = setTimeout(() => {
      searchReviewerCandidates({ opportunityId, reviewType, q: query }).then(
        (result) => {
          if (started !== reads.current) return;
          if (result.kind === "ok") {
            setOptions(result.users);
            setFailed(false);
          } else setFailed(true);
        },
        () => {
          if (started === reads.current) setFailed(true);
        },
      );
    }, SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [open, query, reviewType, opportunityId]);

  function toggle(user: UserSummary) {
    if (chosenIds.has(user.id)) onChange(chosen.filter((c) => c.id !== user.id));
    else onChange([...chosen, user]);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span id={labelId} className="text-label">
        {REVIEWERS_LABEL}
      </span>
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) setOptions(null);
        }}
      >
        <PopoverTrigger
          disabled={disabled}
          aria-labelledby={labelId}
          render={<Button type="button" variant="outline" className="w-full justify-between" />}
        >
          <span className="truncate">
            {chosen.length > 0 ? `${chosen.length} chosen` : REVIEWERS_PLACEHOLDER}
          </span>
          <ChevronsUpDownIcon aria-hidden="true" className="size-4 shrink-0 opacity-60" />
        </PopoverTrigger>
        <PopoverContent className="w-80 p-0">
          <Command label={REVIEWERS_LABEL} shouldFilter={false}>
            <CommandInput
              placeholder={REVIEWERS_SEARCH}
              aria-label={REVIEWERS_SEARCH}
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {failed ? (
                <p className="p-3 text-meta text-destructive">{REVIEWERS_NOT_LOADED}</p>
              ) : options === null ? (
                <p className="p-3 text-meta text-muted-foreground">Loading…</p>
              ) : (
                <>
                  <CommandEmpty>{REVIEWERS_EMPTY}</CommandEmpty>
                  {options.length > 0 ? (
                    <CommandGroup>
                      {options.map((user) => (
                        <CommandItem
                          key={user.id}
                          value={user.id}
                          data-checked={chosenIds.has(user.id)}
                          aria-checked={chosenIds.has(user.id)}
                          onSelect={() => toggle(user)}
                        >
                          <span className="shrink-0 text-label">{user.name}</span>
                          <span className="truncate text-meta text-muted-foreground">
                            {user.email}
                          </span>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  ) : null}
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {chosen.length > 0 ? (
        <ul aria-label="Chosen reviewers" className="flex flex-wrap gap-1.5">
          {chosen.map((user) => (
            <li key={user.id}>
              <Chip>
                {user.name}
                <button
                  type="button"
                  disabled={disabled}
                  aria-label={`Remove ${user.name}`}
                  onClick={() => onChange(chosen.filter((c) => c.id !== user.id))}
                  className={
                    "inline-flex rounded-sm outline-none focus-visible:ring-2 " +
                    "focus-visible:ring-primary"
                  }
                >
                  <XIcon aria-hidden="true" className="size-3" />
                </button>
              </Chip>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** **Request review** (outline, in the Estimate toolbar after Export) and its 520px dialog,
 * "Request review of Estimate v3" (Story 9.1, the mockup's Challenge-dialog conventions): a
 * Review type segmented control (Engineering / PM / Security), the Reviewers combobox,
 * "Assessments to review (optional)" as `aria-pressed` toggle cards (all unticked: the whole
 * Estimate Version), a "Message (optional)" textarea, and **Cancel** / **Send N requests**
 * (disabled until a reviewer is chosen). A 4xx shows inline in the dialog; a send announces
 * "Review requested from 2 reviewers". Shown only when the API says the caller may
 * (`can_request_review`); the API checks the roles and the author. */
export function RequestReviewDialog({
  opportunityId,
  version,
  assessments,
  onSent,
}: {
  opportunityId: string;
  version: { id: string; version: number; row_version: number };
  assessments: AssessmentOption[];
  onSent?: (created: CreatedReviewRequests) => void;
}) {
  const announce = useAnnounce();
  const typeName = useId();
  const assessmentsId = useId();
  const messageId = useId();
  const messageRuleId = useId();
  const [open, setOpen] = useState(false);
  const [reviewType, setReviewType] = useState<ReviewType>("engineering");
  const [reviewers, setReviewers] = useState<UserSummary[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const messageOk = codePointLength(message.trim()) <= MESSAGE_MAX;
  // Only picked Assessments still offered count (the list can change under the dialog).
  const pickedNow = assessments.filter((a) => picked.includes(a.id));
  const count = requestCount(reviewers.length, pickedNow.length);

  function reset() {
    setReviewType("engineering");
    setReviewers([]);
    setPicked([]);
    setMessage("");
    setProblem(null);
  }

  function togglePicked(id: string) {
    setPicked((now) => (now.includes(id) ? now.filter((p) => p !== id) : [...now, id]));
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || reviewers.length === 0 || !messageOk) return;
    setBusy(true);
    setProblem(null);
    let result: Awaited<ReturnType<typeof requestReview>>;
    try {
      result = await requestReview({
        opportunityId,
        versionId: version.id,
        rowVersion: version.row_version,
        reviewType,
        reviewerIds: reviewers.map((r) => r.id),
        assessmentRefs: pickedNow.map((a) => ({ id: a.id, version: a.version })),
        message,
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      announce(requestedAnnouncement(reviewers.length));
      setOpen(false);
      reset();
      onSent?.(result.value);
      return;
    }
    const sentence =
      result.kind === "invalid"
        ? result.detail
        : result.kind === "stale"
          ? REQUEST_STALE
          : result.kind === "forbidden" || result.kind === "not-found"
            ? REQUEST_FORBIDDEN
            : REQUEST_FAILED;
    setProblem(sentence);
    announce(sentence);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <Button type="button" variant="outline" data-request-review="" onClick={() => setOpen(true)}>
        <UserCheckIcon aria-hidden="true" />
        {REQUEST_REVIEW}
      </Button>
      <DialogContent showCloseButton={false}>
        <form
          noValidate
          onSubmit={(event) => void send(event)}
          aria-busy={busy || undefined}
          className="flex flex-col gap-3.5"
        >
          <DialogHeader>
            <DialogTitle>{requestReviewTitle(version.version)}</DialogTitle>
          </DialogHeader>
          <fieldset className="flex flex-col gap-1">
            <legend className="mb-1 text-label">{REVIEW_TYPE_LABEL}</legend>
            <div
              data-review-type=""
              className="inline-flex w-fit rounded-md border border-border-strong bg-surface-alt p-0.5"
            >
              {REVIEW_TYPES.map((option) => (
                <label
                  key={option.value}
                  className={cn(
                    "cursor-pointer rounded-[5px] px-3 py-1 text-label has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-primary",
                    reviewType === option.value
                      ? "bg-surface text-foreground shadow-sm"
                      : "text-muted-foreground",
                  )}
                >
                  <input
                    type="radio"
                    name={typeName}
                    value={option.value}
                    checked={reviewType === option.value}
                    disabled={busy}
                    onChange={() => {
                      setReviewType(option.value);
                      // Reviewers hold one review role: the list is read again for the type.
                      setReviewers([]);
                    }}
                    className="sr-only"
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </fieldset>
          <ReviewerPicker
            opportunityId={opportunityId}
            reviewType={reviewType}
            chosen={reviewers}
            onChange={setReviewers}
            disabled={busy}
          />
          {assessments.length > 0 ? (
            <div role="group" aria-labelledby={assessmentsId} className="flex flex-col gap-1.5">
              <h3 id={assessmentsId} className="text-muted-foreground uppercase">
                <span className="text-eyebrow">{ASSESSMENTS_LABEL}</span>
              </h3>
              {assessments.map((a) => {
                const on = picked.includes(a.id);
                return (
                  <button
                    key={a.id}
                    type="button"
                    aria-pressed={on}
                    disabled={busy}
                    data-assessment-card={a.id}
                    onClick={() => togglePicked(a.id)}
                    className={cn(
                      "flex items-center gap-3 rounded-lg border px-3 py-2.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary",
                      on ? "border-primary bg-primary-tint" : "border-border-strong bg-transparent",
                    )}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        "flex size-[18px] shrink-0 items-center justify-center rounded-[5px] border-[1.5px]",
                        on
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-border-strong",
                      )}
                    >
                      {on ? <CheckIcon className="size-3" /> : null}
                    </span>
                    <span className="text-body-strong">{a.label}</span>
                  </button>
                );
              })}
              <p className="text-meta text-muted-foreground">{ASSESSMENTS_HELP}</p>
            </div>
          ) : null}
          <div className="flex flex-col gap-1">
            <label htmlFor={messageId} className="text-label">
              {MESSAGE_LABEL}
            </label>
            <Textarea
              id={messageId}
              rows={3}
              value={message}
              disabled={busy}
              aria-invalid={messageOk ? undefined : true}
              aria-describedby={messageOk ? undefined : messageRuleId}
              onChange={(event) => setMessage(event.target.value)}
            />
            {messageOk ? null : (
              <p id={messageRuleId} className="text-meta text-destructive">
                {MESSAGE_TOO_LONG}
              </p>
            )}
          </div>
          {problem ? (
            <p
              role="alert"
              data-request-problem=""
              className="rounded-md border border-blocker/30 bg-blocker-tint px-3 py-2 text-meta text-blocker"
            >
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>{CANCEL}</DialogClose>
            <Button type="submit" disabled={busy || reviewers.length === 0 || !messageOk}>
              {sendLabel(count)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
