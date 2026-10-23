"use client";

import { ArrowUpIcon, CheckIcon, SparklesIcon } from "lucide-react";
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
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Pill } from "@/components/ui/pill";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useAnnounce } from "@/components/shell/live-region";
import {
  agentPillLabel,
  agentsTotalEffect,
  CHOICE_REQUIRED,
  conflictNote,
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
  positionVersion,
  previousDecisionLabel,
  REASON_REQUIRED,
  REVIEWER_REQUIRED,
  type Conflict,
  type ConflictPosition,
  type Person,
} from "@/lib/conflicts";
import { kindLabel, type FindingKind } from "@/lib/assessments";
import { codePointLength } from "@/lib/opportunities";

type ConflictRequirement = NonNullable<ConflictPosition["requirement"]>;

/** What a saved decision did: resolved the Conflict or escalated it. */
export type DecisionKind = "resolved" | "escalated";

export const RESOLVE = "Resolve";
export const ESCALATE = "Escalate";
export const RELOAD = "Reload";
export const DECISION_HINT = "Choose a position, then give a reason.";
export const ESCALATE_HINT = "Choose a reviewer, then give a reason.";
const DECISION_FAILED = "The decision could not be saved. Try again.";
const NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, or the assigned reviewer can decide this Conflict.";
const GONE = "This Conflict is no longer there. Reload to see the latest.";

const fieldClass =
  "h-[38px] rounded-md border border-border-strong bg-surface-alt px-3 text-body outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background aria-[invalid=true]:border-destructive";

/** The evidence chip of a position's Requirement (struck through when superseded). */
function RequirementChip({ requirement }: { requirement: ConflictRequirement }) {
  return (
    <Chip className={`self-start ${requirement.label === "Superseded" ? "line-through" : ""}`}>
      {requirement.label}
    </Chip>
  );
}

/** One position card's content: the agent pill (primary tint, sparkle) with the version, the
 * value at 20px in tabular figures (a Finding's stance smaller), the cited Finding's title as the
 * basis line, and the Requirement as the evidence chip. */
function PositionBody({ position, chosen }: { position: ConflictPosition; chosen: boolean }) {
  const version = positionVersion(position);
  return (
    <>
      <span className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-full bg-primary-tint py-0.5 pr-2.5 pl-2 text-label text-primary-text">
          <SparklesIcon aria-hidden="true" className="size-3 shrink-0" />
          {agentPillLabel(position)}
        </span>
        {version ? <span className="text-meta text-muted-foreground">{version}</span> : null}
        {chosen ? (
          <Pill tone="resolved" icon={<CheckIcon />} className="ml-auto">
            Chosen
          </Pill>
        ) : null}
      </span>
      <span
        className={
          position.finding
            ? "min-w-0 break-words text-section"
            : "text-[20px] leading-7 font-semibold [font-variant-numeric:tabular-nums]"
        }
      >
        {position.summary}
      </span>
      {position.finding ? (
        <span
          data-testid="position-finding"
          className="min-w-0 break-words text-body text-muted-foreground"
        >
          {`${kindLabel(position.finding.kind as FindingKind)} · ${position.finding.title}`}
        </span>
      ) : null}
      {position.requirement ? <RequirementChip requirement={position.requirement} /> : null}
    </>
  );
}

const cardClass = "flex min-w-0 flex-col gap-3 rounded-xl border-2 p-5";

/** Two columns from `md` (one below), auto-fit when there are three or more positions. */
function gridClass(count: number): string {
  return count > 2
    ? "grid grid-cols-1 gap-4 md:grid-cols-[repeat(auto-fit,minmax(12rem,1fr))]"
    : "grid grid-cols-1 gap-4 md:grid-cols-2";
}

/** The required reason, with a live character count and an inline error. */
function ReasonField({
  value,
  onChange,
  error,
  disabled,
  textareaRef,
}: {
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
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-label">
        Reason (required)
      </label>
      <Textarea
        id={id}
        ref={textareaRef}
        rows={3}
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${countId} ${errorId}` : countId}
        onChange={(event) => onChange(event.target.value)}
      />
      <span
        id={countId}
        className={`self-end text-meta [font-variant-numeric:tabular-nums] ${length > DECISION_REASON_MAX ? "text-destructive" : "text-muted-foreground"}`}
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

type Outcome = { kind: "stale"; message: string } | { kind: "message"; text: string } | null;

/** What to show after a failed decision. */
function failure(result: Exclude<ConflictDecisionResult, { kind: "ok" }>): Outcome {
  switch (result.kind) {
    case "stale":
      return { kind: "stale", message: result.message };
    case "invalid":
      return { kind: "message", text: result.detail };
    case "conflict":
      return { kind: "message", text: `${result.detail} Reload to see the latest.` };
    case "forbidden":
      return { kind: "message", text: NOT_ALLOWED };
    case "not-found":
      return { kind: "message", text: GONE };
    default:
      return { kind: "message", text: DECISION_FAILED };
  }
}

function useDecision(onDecided?: (kind: DecisionKind) => void) {
  const router = useRouter();
  const announce = useAnnounce();
  const [pending, startTransition] = useTransition();
  const [outcome, setOutcome] = useState<Outcome>(null);

  function submit(
    run: () => Promise<ConflictDecisionResult>,
    done: string,
    kind: DecisionKind,
  ) {
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
        onDecided?.(kind);
        // The badge, the Open and Resolved cards and the Estimate markers update.
        router.refresh();
        return;
      }
      const next = failure(result);
      setOutcome(next);
      announce(next?.kind === "stale" ? next.message : (next?.text ?? DECISION_FAILED));
    });
  }

  const notice: ReactNode =
    outcome?.kind === "stale" ? (
      <InlineAlert
        lead={outcome.message}
        onReload={() => {
          setOutcome(null);
          router.refresh();
        }}
      />
    ) : outcome?.kind === "message" ? (
      <p className="text-meta text-destructive">{outcome.text}</p>
    ) : null;

  return { pending, submit, notice };
}

const DIFFERENT = "different";

type Errors = { choice?: string; entered?: string; reason?: string; reviewer?: string };

/** The decision form: a radio card per position, "A different position" with a text field, one
 * required reason, then Resolve and (when allowed) Escalate on one row. The first Escalate press
 * reveals the reviewer select; the second sends the escalation with the same reason. Blank
 * choices, reviewers and reasons are blocked inline before anything is sent. */
function DecisionForm({
  conflict,
  opportunityId,
  reviewers,
  escalating,
  onDecided,
}: {
  conflict: Conflict;
  opportunityId: string;
  reviewers: readonly Person[];
  escalating: boolean;
  onDecided?: (kind: DecisionKind) => void;
}) {
  const [choice, setChoice] = useState<string | null>(null);
  const [entered, setEntered] = useState("");
  const [reason, setReason] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [showReviewer, setShowReviewer] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const { pending, submit, notice } = useDecision(onDecided);
  const groupName = useId();
  const choiceErrorId = useId();
  const enteredId = useId();
  const enteredErrorId = useId();
  const selectId = useId();
  const selectErrorId = useId();
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const selectRef = useRef<HTMLSelectElement>(null);
  const effort = conflict.type === "effort";
  const chosen = conflict.positions.find((p) => String(p.position) === choice);
  const agentEffect =
    effort && chosen?.source === "assessment" ? agentsTotalEffect(conflict.positions) : null;

  useEffect(() => {
    if (showReviewer) selectRef.current?.focus();
  }, [showReviewer]);

  function reasonError(trimmed: string): string | undefined {
    return !trimmed || codePointLength(trimmed) > DECISION_REASON_MAX ? REASON_REQUIRED : undefined;
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    const found: Errors = {};
    let picked: ConflictChoice | null = null;
    if (choice === null) found.choice = CHOICE_REQUIRED;
    else if (choice === DIFFERENT) {
      const text = entered.trim();
      if (!text || codePointLength(text) > ENTERED_MAX) found.entered = ENTERED_REQUIRED;
      else if (effort && !isEnteredHours(text)) found.entered = HOURS_REQUIRED;
      else picked = { entered: text };
    } else picked = { position: Number(choice) };
    const trimmed = reason.trim();
    found.reason = reasonError(trimmed);
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
      "resolved",
    );
  }

  function onEscalate() {
    if (pending) return;
    if (!showReviewer) {
      setErrors({});
      setShowReviewer(true);
      return;
    }
    const trimmed = reason.trim();
    const found: Errors = {};
    if (!reviewer) found.reviewer = REVIEWER_REQUIRED;
    found.reason = reasonError(trimmed);
    setErrors(found);
    if (found.reviewer) selectRef.current?.focus();
    else if (found.reason) reasonRef.current?.focus();
    if (found.reviewer || found.reason) return;
    const name = reviewers.find((r) => r.id === reviewer)?.name ?? "the reviewer";
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
      "escalated",
    );
  }

  return (
    <form aria-label="Decide the Conflict" onSubmit={onSubmit} className="flex flex-col gap-4">
      <fieldset
        className="flex flex-col gap-3"
        aria-describedby={errors.choice ? choiceErrorId : undefined}
      >
        <legend className="mb-3 text-label text-muted-foreground">Choose a position</legend>
        <div className={gridClass(conflict.positions.length)}>
          {conflict.positions.map((position) => (
            <label
              key={position.position}
              className={`${cardClass} cursor-pointer border-border bg-surface hover:bg-surface-alt has-[:checked]:border-primary has-[:checked]:bg-primary-tint has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring has-[:focus-visible]:ring-offset-2`}
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
              <PositionBody position={position} chosen={false} />
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
            <label htmlFor={enteredId} className="text-meta text-muted-foreground">
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
              className={`${fieldClass} max-w-sm`}
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
        value={reason}
        onChange={setReason}
        error={errors.reason ?? null}
        disabled={pending}
        textareaRef={reasonRef}
      />
      {notice}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={pending}>
          {RESOLVE}
        </Button>
        {escalating ? (
          <Button type="button" variant="outline" disabled={pending} onClick={onEscalate}>
            <ArrowUpIcon aria-hidden="true" />
            {ESCALATE}
          </Button>
        ) : null}
        {escalating && showReviewer ? (
          <div className="flex flex-col gap-1">
            <label htmlFor={selectId} className="sr-only">
              Reviewer
            </label>
            <span className="w-56">
              <Select
                id={selectId}
                ref={selectRef}
                value={reviewer}
                disabled={pending}
                aria-invalid={errors.reviewer ? true : undefined}
                aria-describedby={errors.reviewer ? selectErrorId : undefined}
                onChange={(event) => setReviewer(event.target.value)}
              >
                <option value="">Choose a reviewer</option>
                {reviewers.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </Select>
            </span>
          </div>
        ) : null}
        <span className="text-meta text-muted-foreground">
          {showReviewer ? ESCALATE_HINT : DECISION_HINT}
        </span>
      </div>
      {errors.reviewer ? (
        <p id={selectErrorId} className="text-meta text-destructive">
          {errors.reviewer}
        </p>
      ) : null}
    </form>
  );
}

/** The decision card of the selected Conflict, inline under the Open card: its summary as the
 * title, a note (type and severity, an earlier decision, the escalation), then the positions as
 * big cards. While it is open or escalated and the viewer may decide, the cards become a choice
 * with a required reason, Resolve, and (for an open one) Escalate. Otherwise the cards are
 * static, the chosen one marked, under the decision line, its reason and the Estimate effect. */
export function ConflictInspector({
  conflict,
  focusRequest = 0,
  opportunityId = "",
  reviewers = [],
  onDecided,
}: {
  conflict: Conflict;
  focusRequest?: number;
  opportunityId?: string;
  reviewers?: readonly Person[];
  /** Called after a decision is saved, before the refresh. */
  onDecided?: (kind: DecisionKind) => void;
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
  const deciding =
    conflict.can_resolve && conflict.status !== "resolved" && opportunityId !== "";
  const escalating = conflict.can_escalate && opportunityId !== "" && reviewers.length > 0;

  return (
    <Card
      role="region"
      aria-labelledby={headingId}
      data-testid="conflict-decision-card"
      className="min-w-0 gap-4 p-6"
    >
      <div className="flex flex-col gap-1.5">
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="rounded-sm text-section outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {conflict.summary}
        </h3>
        <p className="text-meta text-muted-foreground">{conflictNote(conflict)}</p>
        {conflict.requirement ? (
          <p className="flex min-w-0 items-baseline gap-2">
            <RequirementChip requirement={conflict.requirement} />
            <span className="min-w-0 break-words text-meta text-muted-foreground">
              {conflict.requirement.excerpt}
            </span>
          </p>
        ) : null}
        {earlier ? <p className="text-meta text-muted-foreground">{earlier}</p> : null}
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
      </div>

      {deciding ? (
        <DecisionForm
          key={`decide-${conflict.row_version}`}
          conflict={conflict}
          opportunityId={opportunityId}
          reviewers={reviewers}
          escalating={escalating}
          onDecided={onDecided}
        />
      ) : (
        <div className="flex flex-col gap-4">
          {decision ? (
            <div className="flex flex-col gap-0.5" data-testid="conflict-decision">
              <p className="text-body-strong">{decision}</p>
              {conflict.resolution_reason ? (
                <p className="text-body text-muted-foreground">{conflict.resolution_reason}</p>
              ) : null}
              {effect ? <p className="text-meta text-muted-foreground">{effect}</p> : null}
            </div>
          ) : conflict.resolution_reason ? (
            <p className="text-body text-muted-foreground">{conflict.resolution_reason}</p>
          ) : null}
          <h4 className="sr-only">Positions</h4>
          <ul className={gridClass(conflict.positions.length)}>
            {conflict.positions.map((position) => {
              const chosen = position.position === conflict.chosen_position;
              return (
                <li
                  key={position.position}
                  className={`${cardClass} ${chosen ? "border-primary bg-primary-tint" : "border-border bg-surface"}`}
                >
                  <PositionBody position={position} chosen={chosen} />
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Card>
  );
}
