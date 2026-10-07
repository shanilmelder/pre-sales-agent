"use client";

import { ArrowUpIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useEffect,
  useId,
  useRef,
  useState,
  useTransition,
  type FormEvent,
  type ReactNode,
  type Ref,
} from "react";

import {
  escalateConflict,
  resolveConflict,
  type ConflictChoice,
  type ConflictDecisionResult,
} from "@/app/opportunities/actions";
import { ConflictStatusPill } from "@/components/opportunities/conflict-status-pill";
import { SeverityPill } from "@/components/opportunities/severity-pill";
import { useAnnounce } from "@/components/shell/live-region";
import {
  agentsTotalEffect,
  CHOICE_REQUIRED,
  DECISION_REASON_MAX,
  decisionLabel,
  DIFFERENT_POSITION,
  ENTERED_MAX,
  ENTERED_REQUIRED,
  escalatedLabel,
  estimateEffect,
  HOURS_REQUIRED,
  isEnteredHours,
  positionName,
  positionRole,
  positionSource,
  previousDecisionLabel,
  REASON_REQUIRED,
  REVIEWER_REQUIRED,
  typeLabel,
  type Conflict,
  type ConflictPosition,
  type Person,
} from "@/lib/conflicts";
import { codePointLength } from "@/lib/opportunities";

type ConflictRequirement = NonNullable<ConflictPosition["requirement"]>;

export const RESOLVE = "Resolve";
export const ESCALATE = "Escalate";
export const RELOAD = "Reload";
const DECISION_FAILED = "The decision could not be saved. Try again.";
const NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, or the assigned reviewer can decide this Conflict.";
const GONE = "This Conflict is no longer there. Reload to see the latest.";

const chipClass =
  "inline-flex h-5 shrink-0 items-center rounded-sm border border-border bg-background px-1.5 font-mono text-meta text-muted-foreground";
const buttonClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";
const primaryClass =
  "h-6 shrink-0 self-start rounded-md bg-primary px-2 text-label text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 disabled:cursor-default disabled:opacity-60";
const fieldClass =
  "rounded-md border border-input bg-background px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-[invalid=true]:border-destructive";

function RequirementChip({
  requirement,
}: {
  requirement: ConflictRequirement;
}) {
  return (
    <p className="flex min-w-0 items-baseline gap-2">
      <span
        className={`${chipClass} ${requirement.label === "Superseded" ? "line-through" : ""}`}
      >
        {requirement.label}
      </span>
      <span className="min-w-0 break-words text-meta">
        {requirement.excerpt}
      </span>
    </p>
  );
}

const sameRequirement = (
  a: ConflictRequirement | null,
  b: ConflictRequirement | null,
) => a !== null && b !== null && a.id === b.id && a.version === b.version;

/** One position's content: the agent by role (or the Estimate), the value in tabular figures,
 * its Requirement chip when it differs from the Conflict's, and the source version. */
function PositionBody({
  position,
  shown,
  chosen,
}: {
  position: ConflictPosition;
  shown: ConflictRequirement | null;
  chosen: boolean;
}) {
  const requirement = position.requirement;
  return (
    <>
      <span className="flex items-center gap-1.5 text-label text-muted-foreground">
        {positionRole(position)}
        {chosen ? (
          <span className="rounded-sm bg-resolved/15 px-1 text-meta text-resolved">
            Chosen
          </span>
        ) : null}
      </span>
      <span className="text-body-strong [font-variant-numeric:tabular-nums]">
        {position.summary}
      </span>
      {requirement && !sameRequirement(requirement, shown) ? (
        <RequirementChip requirement={requirement} />
      ) : null}
      <span className="text-meta text-muted-foreground">
        {positionSource(position)}
      </span>
    </>
  );
}

const cardClass =
  "flex min-w-0 flex-col gap-1.5 rounded-md border border-border p-2";
const gridClass = "grid grid-cols-[repeat(auto-fit,minmax(7.5rem,1fr))] gap-2";

/** A labelled multi-line field with a live character count and an inline error. */
function ReasonField({
  label,
  value,
  onChange,
  error,
  disabled,
  textareaRef,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error: string | null;
  disabled: boolean;
  textareaRef?: Ref<HTMLTextAreaElement>;
}) {
  const id = useId();
  const countId = useId();
  const errorId = useId();
  const length = codePointLength(value.trim());
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-label">
        {label}
      </label>
      <textarea
        id={id}
        ref={textareaRef}
        rows={3}
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${countId} ${errorId}` : countId}
        onChange={(event) => onChange(event.target.value)}
        className={`${fieldClass} py-1`}
      />
      <span
        id={countId}
        className={`text-meta [font-variant-numeric:tabular-nums] ${length > DECISION_REASON_MAX ? "text-destructive" : "text-muted-foreground"}`}
      >
        {`${length}/${DECISION_REASON_MAX}`}
      </span>
      {error ? (
        <p id={errorId} className="text-meta text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

type Outcome =
  { kind: "stale"; message: string } | { kind: "message"; text: string } | null;

/** What to show after a failed decision. */
function failure(
  result: Exclude<ConflictDecisionResult, { kind: "ok" }>,
): Outcome {
  switch (result.kind) {
    case "stale":
      return { kind: "stale", message: result.message };
    case "invalid":
      return { kind: "message", text: result.detail };
    case "conflict":
      return {
        kind: "message",
        text: `${result.detail} Reload to see the latest.`,
      };
    case "forbidden":
      return { kind: "message", text: NOT_ALLOWED };
    case "not-found":
      return { kind: "message", text: GONE };
    default:
      return { kind: "message", text: DECISION_FAILED };
  }
}

function useDecision() {
  const router = useRouter();
  const announce = useAnnounce();
  const [pending, startTransition] = useTransition();
  const [outcome, setOutcome] = useState<Outcome>(null);

  function submit(run: () => Promise<ConflictDecisionResult>, done: string) {
    setOutcome(null);
    startTransition(async () => {
      let result: ConflictDecisionResult;
      try {
        result = await run();
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok") {
        announce(done);
        // The badge, the Open and Resolved sections and the Estimate markers update.
        router.refresh();
        return;
      }
      const next = failure(result);
      setOutcome(next);
      announce(
        next?.kind === "stale" ? next.message : (next?.text ?? DECISION_FAILED),
      );
    });
  }

  const notice: ReactNode =
    outcome?.kind === "stale" ? (
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-label text-foreground">{outcome.message}</p>
        <button
          type="button"
          onClick={() => {
            setOutcome(null);
            router.refresh();
          }}
          className={buttonClass}
        >
          {RELOAD}
        </button>
      </div>
    ) : outcome?.kind === "message" ? (
      <p className="text-meta text-destructive">{outcome.text}</p>
    ) : null;

  return { pending, submit, notice };
}

const DIFFERENT = "different";

/** The Resolve form: a radio card per position (on the equal-width cards), "A different
 * position" with a text field, a required reason, then Resolve. Blank choices and reasons are
 * blocked inline before anything is sent. */
function ResolveForm({
  conflict,
  opportunityId,
}: {
  conflict: Conflict;
  opportunityId: string;
}) {
  const [choice, setChoice] = useState<string | null>(null);
  const [entered, setEntered] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<{
    choice?: string;
    entered?: string;
    reason?: string;
  }>({});
  const { pending, submit, notice } = useDecision();
  const groupName = useId();
  const choiceErrorId = useId();
  const enteredId = useId();
  const enteredErrorId = useId();
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const effort = conflict.type === "effort";
  const chosen = conflict.positions.find((p) => String(p.position) === choice);
  const agentEffect =
    effort && chosen?.source === "assessment"
      ? agentsTotalEffect(conflict.positions)
      : null;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    const found: typeof errors = {};
    let picked: ConflictChoice | null = null;
    if (choice === null) found.choice = CHOICE_REQUIRED;
    else if (choice === DIFFERENT) {
      const text = entered.trim();
      if (!text || codePointLength(text) > ENTERED_MAX)
        found.entered = ENTERED_REQUIRED;
      else if (effort && !isEnteredHours(text)) found.entered = HOURS_REQUIRED;
      else picked = { entered: text };
    } else picked = { position: Number(choice) };
    const trimmed = reason.trim();
    if (!trimmed || codePointLength(trimmed) > DECISION_REASON_MAX)
      found.reason = REASON_REQUIRED;
    setErrors(found);
    if (found.reason) reasonRef.current?.focus();
    if (!picked || found.reason) return;
    const sent = picked;
    submit(
      () =>
        resolveConflict({
          opportunityId,
          conflictId: conflict.id,
          rowVersion: conflict.row_version,
          choice: sent,
          reason: trimmed,
        }),
      "Conflict resolved",
    );
  }

  return (
    <form
      aria-label="Resolve the Conflict"
      onSubmit={onSubmit}
      className="flex flex-col gap-3"
    >
      <fieldset
        className="flex flex-col gap-1.5"
        aria-describedby={errors.choice ? choiceErrorId : undefined}
      >
        <legend className="mb-1.5 text-label text-muted-foreground">
          Choose a position
        </legend>
        {conflict.requirement ? (
          <RequirementChip requirement={conflict.requirement} />
        ) : null}
        <div className={gridClass}>
          {conflict.positions.map((position) => (
            <label
              key={position.position}
              className={`${cardClass} cursor-pointer has-[:checked]:border-primary has-[:checked]:ring-1 has-[:checked]:ring-primary has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-primary`}
            >
              <input
                type="radio"
                name={groupName}
                value={String(position.position)}
                checked={choice === String(position.position)}
                disabled={pending}
                onChange={() => setChoice(String(position.position))}
                aria-label={`${positionName(position)}, ${position.summary}`}
                className="sr-only"
              />
              <PositionBody
                position={position}
                shown={conflict.requirement}
                chosen={false}
              />
            </label>
          ))}
        </div>
        <label className="flex items-center gap-2 text-label">
          <input
            type="radio"
            name={groupName}
            value={DIFFERENT}
            checked={choice === DIFFERENT}
            disabled={pending}
            onChange={() => setChoice(DIFFERENT)}
          />
          {DIFFERENT_POSITION}
        </label>
        {choice === DIFFERENT ? (
          <div className="flex flex-col gap-1 pl-5">
            <label
              htmlFor={enteredId}
              className="text-meta text-muted-foreground"
            >
              {effort ? "Hours" : "The position"}
            </label>
            <input
              id={enteredId}
              type="text"
              inputMode={effort ? "decimal" : undefined}
              value={entered}
              disabled={pending}
              aria-invalid={errors.entered ? true : undefined}
              aria-describedby={errors.entered ? enteredErrorId : undefined}
              onChange={(event) => setEntered(event.target.value)}
              className={`${fieldClass} h-6`}
            />
            {errors.entered ? (
              <p id={enteredErrorId} className="text-meta text-destructive">
                {errors.entered}
              </p>
            ) : null}
          </div>
        ) : null}
        {agentEffect ? (
          <p className="text-meta text-muted-foreground" aria-live="polite">
            {agentEffect}
          </p>
        ) : null}
        {errors.choice ? (
          <p id={choiceErrorId} className="text-meta text-destructive">
            {errors.choice}
          </p>
        ) : null}
      </fieldset>
      <ReasonField
        label="Reason"
        value={reason}
        onChange={setReason}
        error={errors.reason ?? null}
        disabled={pending}
        textareaRef={reasonRef}
      />
      {notice}
      <button type="submit" disabled={pending} className={primaryClass}>
        {RESOLVE}
      </button>
    </form>
  );
}

/** The Escalate form of an open Conflict: a reviewer (the Opportunity's owner and
 * collaborators, without the viewer) and a required reason. */
function EscalateForm({
  conflict,
  opportunityId,
  reviewers,
}: {
  conflict: Conflict;
  opportunityId: string;
  reviewers: readonly Person[];
}) {
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<{ reviewer?: string; reason?: string }>(
    {},
  );
  const { pending, submit, notice } = useDecision();
  const selectId = useId();
  const selectErrorId = useId();

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    const trimmed = reason.trim();
    const found: typeof errors = {};
    if (!reviewer) found.reviewer = REVIEWER_REQUIRED;
    if (!trimmed || codePointLength(trimmed) > DECISION_REASON_MAX)
      found.reason = REASON_REQUIRED;
    setErrors(found);
    if (found.reviewer || found.reason) return;
    const name =
      reviewers.find((r) => r.id === reviewer)?.name ?? "the reviewer";
    submit(
      () =>
        escalateConflict({
          opportunityId,
          conflictId: conflict.id,
          rowVersion: conflict.row_version,
          reviewerId: reviewer,
          reason: trimmed,
        }),
      `Conflict escalated to ${name}`,
    );
  }

  return (
    <form
      aria-label="Escalate the Conflict"
      onSubmit={onSubmit}
      className="flex flex-col gap-3"
    >
      <div className="flex flex-col gap-1">
        <label htmlFor={selectId} className="text-label">
          Reviewer
        </label>
        <select
          id={selectId}
          value={reviewer}
          disabled={pending}
          aria-invalid={errors.reviewer ? true : undefined}
          aria-describedby={errors.reviewer ? selectErrorId : undefined}
          onChange={(event) => setReviewer(event.target.value)}
          className={`${fieldClass} h-6`}
        >
          <option value="">Choose a reviewer</option>
          {reviewers.map((person) => (
            <option key={person.id} value={person.id}>
              {person.name}
            </option>
          ))}
        </select>
        {errors.reviewer ? (
          <p id={selectErrorId} className="text-meta text-destructive">
            {errors.reviewer}
          </p>
        ) : null}
      </div>
      <ReasonField
        label="Reason for escalating"
        value={reason}
        onChange={setReason}
        error={errors.reason ?? null}
        disabled={pending}
      />
      {notice}
      <button type="submit" disabled={pending} className={primaryClass}>
        {ESCALATE}
      </button>
    </form>
  );
}

/** The selected Conflict in the right pane: its severity, type and status, the summary, the
 * decision or escalation, and the positions as equal-width cards. While it is open or
 * escalated and the viewer may decide, the cards become a choice with a reason (Resolve), and
 * an open one can be escalated to a reviewer. */
export function ConflictInspector({
  conflict,
  focusRequest = 0,
  opportunityId = "",
  reviewers = [],
}: {
  conflict: Conflict;
  focusRequest?: number;
  opportunityId?: string;
  reviewers?: readonly Person[];
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  const decision = decisionLabel(conflict);
  const effect = decision ? estimateEffect(conflict) : null;
  const escalated = escalatedLabel(conflict);
  const earlier = previousDecisionLabel(conflict);
  const deciding = conflict.can_resolve && opportunityId !== "";
  const escalating =
    conflict.can_escalate && opportunityId !== "" && reviewers.length > 0;

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-4 p-gutter"
    >
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityPill severity={conflict.severity} />
          <ConflictStatusPill status={conflict.status} />
        </div>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {typeLabel(conflict.type)} Conflict
        </h3>
        <p className="text-body">{conflict.summary}</p>
        {earlier ? (
          <p className="text-meta text-muted-foreground">{earlier}</p>
        ) : null}
        {escalated ? (
          <div className="flex flex-col gap-0.5">
            <p className="flex items-center gap-1.5 text-label text-gap">
              <ArrowUpIcon aria-hidden="true" className="size-3 shrink-0" />
              {escalated}
            </p>
            {conflict.escalation_reason ? (
              <p className="text-meta text-muted-foreground">
                {conflict.escalated_by ? `${conflict.escalated_by.name}: ` : ""}
                {conflict.escalation_reason}
              </p>
            ) : null}
          </div>
        ) : null}
        {decision ? (
          <div
            className="flex flex-col gap-0.5"
            data-testid="conflict-decision"
          >
            <p className="text-label">{decision}</p>
            {conflict.resolution_reason ? (
              <p className="text-meta text-muted-foreground">
                {conflict.resolution_reason}
              </p>
            ) : null}
            {effect ? (
              <p className="text-meta text-muted-foreground">{effect}</p>
            ) : null}
          </div>
        ) : conflict.resolution_reason ? (
          <p className="text-meta text-muted-foreground">
            {conflict.resolution_reason}
          </p>
        ) : null}
      </div>

      {deciding ? (
        <ResolveForm
          key={`resolve-${conflict.row_version}`}
          conflict={conflict}
          opportunityId={opportunityId}
        />
      ) : (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-label text-muted-foreground">Positions</h4>
          {conflict.requirement ? (
            <RequirementChip requirement={conflict.requirement} />
          ) : null}
          {/* Equal-width cards, wrapping to a new row when the pane is too narrow for all. */}
          <ul className={gridClass}>
            {conflict.positions.map((position) => (
              <li key={position.position} className={cardClass}>
                <PositionBody
                  position={position}
                  shown={conflict.requirement}
                  chosen={position.position === conflict.chosen_position}
                />
              </li>
            ))}
          </ul>
        </div>
      )}

      {escalating ? (
        <details className="flex flex-col gap-2 border-t border-border pt-3">
          <summary className="cursor-pointer text-label outline-none focus-visible:ring-2 focus-visible:ring-primary">
            Escalate to a reviewer
          </summary>
          <div className="pt-2">
            <EscalateForm
              key={`escalate-${conflict.row_version}`}
              conflict={conflict}
              opportunityId={opportunityId}
              reviewers={reviewers}
            />
          </div>
        </details>
      ) : null}
    </section>
  );
}
