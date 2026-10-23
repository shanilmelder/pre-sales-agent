"use client";

import { SparklesIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import { MandatoryLabel } from "@/components/knowledge/mandatory-label";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Pill } from "@/components/ui/pill";
import { pillToneFor } from "@/lib/pill-tone";
import { ImpactBar } from "@/components/opportunities/impact-bar";
import { InlineField } from "@/components/opportunities/inline-field";
import { ReasonInput, reasonFieldClass } from "@/components/opportunities/reason-input";
import {
  answeredLabel,
  answeredOnProblem,
  answerRecordedBy,
  answerTextProblem,
  approvedLabel,
  canDismiss,
  categoryLabel,
  checklistNoLongerApplies,
  DISMISS_REASONS,
  dismissedLabel,
  FROM_CHECKLIST,
  gapStatus,
  historyAction,
  historyByline,
  impactLabel,
  IMPACTS,
  impactTone,
  INJECTION_SUSPECTED,
  isAnswerable,
  isMandatory,
  isSent,
  localToday,
  NO_LONGER_APPLIES,
  noteProblem,
  possibleAnswerLabel,
  questionFlow,
  questionStatus,
  reasonProblem,
  requirementChangeLabel,
  requirementHref,
  sentLabel,
  sentOnProblem,
  statusSince,
  triggerLabel,
  type AnswerPassage,
  type AnswerSuggestion,
  type DismissReasonKind,
  type Gap,
  type GapAnswer,
  type GapHistoryEntry,
  type GapStatus,
  type Impact,
  type QuestionStatus,
} from "@/lib/gaps";

/** The primary-tint pill with a sparkle: what raised the Gap ("Clarification Agent"). */
export function TriggerPill({ children }: { children: ReactNode }) {
  return (
    <Pill icon={<SparklesIcon />} className="bg-primary-tint text-primary-text" data-trigger="">
      {children}
    </Pill>
  );
}

/** An inspector section: padded 16 with a bottom border. */
function Section({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col gap-2 border-b border-border p-4 ${className}`}>{children}</div>
  );
}

/** An inspector section's heading: an uppercase meta label. */
function SectionHeading({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <h4 className={`text-eyebrow text-text-secondary uppercase ${className}`}>{children}</h4>;
}

/** The question status pill, always an icon and a label, tinted by status: Draft neutral,
 * Approved and Answered resolved, Sent primary, No answer gap amber. */
export function QuestionPill({ status }: { status: QuestionStatus }) {
  const known = questionStatus(status);
  const Icon = known.icon;
  // Pill has no primary tone: Sent takes the primary tint through its classes.
  const primary = known.tone === "text-primary";
  return (
    <Pill
      data-question-status={status}
      tone={pillToneFor(known.tone)}
      {...(primary ? { "data-tone": "primary" } : {})}
      icon={<Icon />}
      className={primary ? "shrink-0 bg-primary-tint text-primary-text" : "shrink-0"}
    >
      {known.label}
    </Pill>
  );
}

export type QuestionField = "text" | "topic";

/** What the inspector needs to edit and approve the Gap's question (Story 4.5). */
export type QuestionEditing = {
  /** A save or approval of this question is in flight. */
  busy: boolean;
  /** Nothing may be changed (a stale view, or a reload or Approve all in flight). */
  locked: boolean;
  /** Why the last save of a field failed, and the user's text it kept. */
  failure?: { field: QuestionField; text: string; error: string } | null;
  /** Bump to start editing the question text (the `e` shortcut). */
  editRequest?: number;
  onCommit: (field: QuestionField, value: string) => void;
  onApprove: () => void;
};

/** The selected Gap in the right pane, in sections (Gaps tab redesign): a header ("{Impact}
 * impact · {category}", the status pill and the title); Why it matters with the trigger pill;
 * the related Requirements as id chips with their excerpts; the Clarification Question (its
 * pill, topic and text in a bordered box, and the date of its last status change); Actions (the
 * status's primary action with a line saying where the question is in its flow); suggested
 * answers and the answer; the impact with the basis for it; Dismiss; and the history (Story
 * 4.4).
 *
 * With `edit` (and the Gap open), the topic and text are click-to-edit (Enter or blur saves, Esc
 * reverts) and a drafted question has **Approve question**; an approved one says who approved
 * it and when. With `gapEdit`, an open Gap has an impact select with a required reason and a
 * **Dismiss** form ("Not relevant" / "Other" with a note); a dismissed one says why, by whom and
 * when, and has **Reopen** with a reason. Story 4.2: a mandatory Gap shows the "Mandatory" label
 * by its trigger (and "Checklist no longer applies" once it doesn't), its question "from
 * Checklist", no Related Requirements, and no **Dismiss** while its Checklist still applies.
 * Convert is not offered here (Epic 8 does it from the Estimate). With `send` (Story 4.6), an
 * approved question of an open Gap has **Mark as sent** (a date, today by default) and a sent one
 * **Record answer** and **No answer**; a sent question says "Sent {date} by {name}" and can't be
 * edited or approved. Story 4.7: with `send`, a sent or "No answer" question of an open Gap has
 * **Record answer** (the answer, a date, and whether it settles the Gap), and each suggested answer
 * has **Confirm** and **Not an answer**; an answered Gap shows "Answered by customer, {date}" with
 * the answer passage as Evidence and links to the Requirements the answer changed, and (with
 * `gapEdit`) **Reopen**. Without them, read-only. */
export function GapInspector({
  gap,
  opportunityId,
  focusRequest = 0,
  edit,
  gapEdit,
  send,
}: {
  gap: Gap;
  /** For the links to the Requirements an answer changed. */
  opportunityId: string;
  focusRequest?: number;
  /** Left out for those who may not edit questions. */
  edit?: QuestionEditing;
  /** Left out for those who may not change Gaps. */
  gapEdit?: GapEditing;
  /** Left out for those who may not send questions (Story 4.6). */
  send?: QuestionSending;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const question = gap.question;
  const editable =
    edit !== undefined && gap.status === "open" && question !== null && !isSent(question.status);
  const sendable = send !== undefined && gap.status === "open" && question !== null;
  const [markingSent, setMarkingSent] = useState(false);
  const [answering, setAnswering] = useState(false);
  const flow =
    gap.status === "dismissed"
      ? questionFlow("dismissed")
      : gap.status === "answered"
        ? questionFlow("answered")
        : gap.status === "open" && question
          ? questionFlow(question.status)
          : null;
  const reopenable = gapEdit !== undefined && (gap.status === "dismissed" || gap.status === "answered");

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section aria-labelledby={headingId} className="flex flex-col">
      <Section className="gap-1.5">
        <div className="flex items-center gap-2 text-label">
          <span className={impactTone(gap.impact)}>{impactLabel(gap.impact)} impact</span>
          <span className="min-w-0 flex-1 text-text-secondary">· {categoryLabel(gap.category)}</span>
          <GapStatusPill status={gap.status} />
        </div>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-section [overflow-wrap:anywhere] outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {gap.title}
        </h3>
      </Section>

      <Section>
        <SectionHeading>Why it matters</SectionHeading>
        <p className="whitespace-pre-wrap break-words text-body">{gap.why_it_matters}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <TriggerPill>{triggerLabel(gap)}</TriggerPill>
          {isMandatory(gap) ? <MandatoryLabel /> : null}
          {gap.status === "open" && checklistNoLongerApplies(gap) ? (
            <span className="text-meta text-text-secondary">{NO_LONGER_APPLIES}</span>
          ) : null}
        </div>
      </Section>

      {gap.requirements.length > 0 ? (
        <Section>
          <SectionHeading>Related Requirements</SectionHeading>
          <ul className="flex flex-col gap-2">
            {gap.requirements.map((requirement) => (
              <li key={requirement.id} className="flex items-baseline gap-2.5">
                <Chip className="shrink-0">{requirement.label}</Chip>
                <span className="min-w-0 break-words text-body">{requirement.excerpt}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {question ? (
        <Section>
          <div className="flex items-center gap-2">
            <SectionHeading className="flex-1">
              Clarification Question
              {question.from_checklist ? (
                <span className="ml-2 font-normal">{FROM_CHECKLIST}</span>
              ) : null}
            </SectionHeading>
            <QuestionPill status={question.status} />
          </div>
          {editable ? (
            <div
              role="group"
              aria-label="Clarification Question"
              aria-busy={edit.busy || undefined}
              className="flex flex-col gap-1 rounded-lg border border-border-strong bg-background px-3 py-2.5"
            >
              <InlineField
                label="Edit topic"
                inputLabel="Topic"
                type="text"
                value={question.topic}
                draft={edit.failure?.field === "topic" ? edit.failure.text : undefined}
                error={edit.failure?.field === "topic" ? edit.failure.error : null}
                locked={edit.locked || edit.busy}
                onCommit={(next) => edit.onCommit("topic", next)}
                className="flex flex-col gap-0.5"
                inputClassName="h-7 w-full rounded-md border border-input bg-surface px-2 text-meta outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <p className="text-meta text-text-secondary">{question.topic}</p>
              </InlineField>
              <InlineField
                label="Edit question"
                inputLabel="Question"
                type="textarea"
                value={question.text}
                draft={edit.failure?.field === "text" ? edit.failure.text : undefined}
                error={edit.failure?.field === "text" ? edit.failure.error : null}
                locked={edit.locked || edit.busy}
                editRequest={edit.editRequest}
                onCommit={(next) => edit.onCommit("text", next)}
                className="flex flex-col gap-0.5"
                inputClassName="min-h-20 w-full resize-y rounded-md border border-input bg-surface px-2 py-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <p className="whitespace-pre-wrap break-words text-body">{question.text}</p>
              </InlineField>
            </div>
          ) : (
            <div
              role="group"
              aria-label="Clarification Question (read-only)"
              className="flex flex-col gap-1 rounded-lg border border-border-strong bg-background px-3 py-2.5"
            >
              <p className="text-meta text-text-secondary">{question.topic}</p>
              <p className="whitespace-pre-wrap break-words text-body">{question.text}</p>
            </div>
          )}
          <p className="text-meta text-text-secondary">
            {statusSince(question)}
            {editable ? ". Press e to edit." : ""}
          </p>
          {question.status === "approved" || isSent(question.status) ? (
            <p className="text-meta text-text-secondary">{approvedLabel(question)}</p>
          ) : null}
          {isSent(question.status) ? (
            <p className="text-meta text-text-secondary">{sentLabel(question)}</p>
          ) : null}
        </Section>
      ) : null}

      {flow ? (
        <Section className="gap-3">
          <SectionHeading>Actions</SectionHeading>
          {gap.status === "open" && question ? (
            <>
              {question.status === "drafted" && editable ? (
                <div>
                  <Button
                    type="button"
                    disabled={edit.locked || edit.busy}
                    onClick={edit.onApprove}
                  >
                    Approve question
                  </Button>
                </div>
              ) : null}
              {sendable && question.status === "approved" ? (
                markingSent ? (
                  <MarkSentForm
                    label="Mark this question sent"
                    confirm="Mark sent"
                    disabled={send.busy || send.locked}
                    onSubmit={async (sentOn) => {
                      const outcome = await send.onMarkSent(sentOn);
                      if (outcome === "ok" || outcome === "failed") setMarkingSent(false);
                      return outcome;
                    }}
                    onCancel={() => setMarkingSent(false)}
                  />
                ) : (
                  <div>
                    <Button
                      type="button"
                      disabled={send.busy || send.locked}
                      onClick={() => setMarkingSent(true)}
                    >
                      Mark as sent
                    </Button>
                  </div>
                )
              ) : null}
              {sendable && isAnswerable(question.status) && !answering ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    disabled={send.busy || send.locked}
                    onClick={() => setAnswering(true)}
                  >
                    Record answer
                  </Button>
                  {question.status === "sent" ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={send.busy || send.locked}
                      onClick={send.onNoAnswer}
                    >
                      No answer
                    </Button>
                  ) : null}
                </div>
              ) : null}
              {sendable && isAnswerable(question.status) && answering ? (
                <RecordAnswerForm
                  gapTitle={gap.title}
                  disabled={send.busy || send.locked}
                  onSubmit={async (text, answeredOn, settlesGap) => {
                    const outcome = await send.onRecordAnswer(text, answeredOn, settlesGap);
                    // Only a recorded answer closes the form: a failure keeps the typed text.
                    if (outcome === "ok") setAnswering(false);
                    return outcome;
                  }}
                  onCancel={() => setAnswering(false)}
                />
              ) : null}
            </>
          ) : null}
          <p className="text-meta text-text-secondary">{flow}</p>
          {gap.dismissal ? (
            <div className="flex flex-col gap-1">
              <p className="text-meta text-text-secondary">{dismissedLabel(gap.dismissal)}</p>
              {gap.dismissal.note ? (
                <p className="whitespace-pre-wrap break-words text-body">{gap.dismissal.note}</p>
              ) : null}
            </div>
          ) : null}
          {reopenable ? <ReopenForm edit={gapEdit} /> : null}
        </Section>
      ) : null}

      {gap.answer_suggestions.length > 0 ? (
        <Section>
          <SectionHeading>Suggested answers</SectionHeading>
          <ul className="flex flex-col gap-2">
            {gap.answer_suggestions.map((suggestion) => (
              <li key={suggestion.id}>
                <SuggestionCard
                  suggestion={suggestion}
                  decide={sendable && question && isAnswerable(question.status) ? send : undefined}
                />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {gap.answer ? <AnswerSection answer={gap.answer} opportunityId={opportunityId} /> : null}

      <Section>
        <SectionHeading>Impact</SectionHeading>
        <ImpactBar impact={gap.impact} coloured />
        <p className="whitespace-pre-wrap break-words text-body">{gap.impact_basis}</p>
        {gapEdit && gap.status === "open" ? (
          <ImpactForm key={`${gap.id}-${gap.row_version}`} gap={gap} edit={gapEdit} />
        ) : null}
      </Section>

      {gapEdit && gap.status === "open" && canDismiss(gap) ? (
        <Section>
          <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
            <h4 className="text-body-strong">Dismiss</h4>
            <DismissForm edit={gapEdit} />
          </div>
        </Section>
      ) : null}

      <GapHistory history={gap.history} />
    </section>
  );
}

// --- Gap status, impact change, dismiss, reopen and history (Story 4.4) ----------------------

/** A Gap's status pill: "Open", "Converted" or "Dismissed", always an icon and a label. */
export function GapStatusPill({ status }: { status: GapStatus }) {
  const known = gapStatus(status);
  const Icon = known.icon;
  return (
    <Pill data-gap-status={status} tone={pillToneFor(known.tone)} icon={<Icon />} className="shrink-0">
      {known.label}
    </Pill>
  );
}

// --- sending questions (Story 4.6) -------------------------------------------------------------

/** What the inspector needs to mark the Gap's question sent or "No answer" (Story 4.6). */
export type QuestionSending = {
  /** A write of this question is in flight. */
  busy: boolean;
  /** Nothing may be changed (a stale view, or a reload or bulk write in flight). */
  locked: boolean;
  onMarkSent: (sentOn: string) => Promise<GapFormOutcome>;
  onNoAnswer: () => void;
  /** **Record answer** (Story 4.7). */
  onRecordAnswer: (
    text: string,
    answeredOn: string,
    settlesGap: boolean,
  ) => Promise<GapFormOutcome>;
  /** **Confirm** a suggested answer (Story 4.7). */
  onConfirmSuggestion: (suggestion: AnswerSuggestion) => void;
  /** **Not an answer** (Story 4.7). */
  onRejectSuggestion: (suggestion: AnswerSuggestion) => void;
};

// --- answers (Story 4.7) ---------------------------------------------------------------------

/** A cited passage as an Evidence chip: its `S<n> · <file name>` label and its excerpt. */
function PassageChip({ passage }: { passage: AnswerPassage }) {
  return (
    <figure className="flex flex-col gap-1.5 rounded-lg border border-border bg-background p-3">
      <figcaption>
        <Chip>{passage.label}</Chip>
      </figcaption>
      {passage.excerpt ? (
        <blockquote className="whitespace-pre-wrap break-words text-body">{passage.excerpt}</blockquote>
      ) : null}
    </figure>
  );
}

/** The Answer section: who answered when, the answer passage as Evidence, and the Requirements
 * the answer added, updated or proposed changes to, each a link that opens it (with its diff)
 * on the Requirements tab. */
function AnswerSection({ answer, opportunityId }: { answer: GapAnswer; opportunityId: string }) {
  return (
    <Section>
      <SectionHeading>Answer</SectionHeading>
      <p className="text-body">{answeredLabel(answer.answered_on)}</p>
      <p className="text-meta text-text-secondary">{answerRecordedBy(answer)}</p>
      {answer.passage ? <PassageChip passage={answer.passage} /> : null}
      {answer.requirement_changes.length > 0 ? (
        <div className="flex flex-col gap-1">
          <p className="text-meta text-text-secondary">Requirement changes</p>
          <ul aria-label="Requirement changes" className="flex flex-wrap gap-1.5">
            {answer.requirement_changes.map((change) => (
              <li key={change.requirement_id}>
                <Link
                  href={requirementHref(opportunityId, change.requirement_id)}
                  className="inline-flex h-6 items-center rounded-md bg-primary-tint px-2 text-label text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
                >
                  {requirementChangeLabel(change)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Section>
  );
}

/** A suggested answer: the Source it is in, the passage, an "Injection suspected" warning when
 * the passage reads like an instruction, and (with `decide`) **Confirm** and **Not an
 * answer**. Only a person's Confirm answers the question. */
function SuggestionCard({
  suggestion,
  decide,
}: {
  suggestion: AnswerSuggestion;
  decide?: QuestionSending;
}) {
  return (
    <article
      aria-label={possibleAnswerLabel(suggestion)}
      className="flex flex-col gap-2 rounded-lg border border-border p-3"
    >
      <p className="text-meta text-text-secondary">{possibleAnswerLabel(suggestion)}</p>
      {suggestion.injection_suspected ? (
        <Pill tone="gap" className="w-fit">
          {INJECTION_SUSPECTED}
        </Pill>
      ) : null}
      <PassageChip passage={suggestion.passage} />
      {decide ? (
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={decide.busy || decide.locked}
            onClick={() => decide.onConfirmSuggestion(suggestion)}
          >
            Confirm
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={decide.busy || decide.locked}
            onClick={() => decide.onRejectSuggestion(suggestion)}
          >
            Not an answer
          </Button>
        </div>
      ) : null}
    </article>
  );
}

/** **Record answer**: the customer's answer, the date they gave it (today by default, never
 * later), whether it settles the Gap (ticked by default), then Record answer. */
export function RecordAnswerForm({
  gapTitle,
  disabled,
  onSubmit,
  onCancel,
}: {
  gapTitle: string;
  disabled: boolean;
  onSubmit: (text: string, answeredOn: string, settlesGap: boolean) => Promise<GapFormOutcome>;
  onCancel: () => void;
}) {
  const today = localToday();
  const [text, setText] = useState("");
  const [answeredOn, setAnsweredOn] = useState(today);
  const [settles, setSettles] = useState(true);
  const [textError, setTextError] = useState<string | null>(null);
  const [dateError, setDateError] = useState<string | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const dateRef = useRef<HTMLInputElement>(null);
  const textId = useId();
  const textErrorId = useId();
  const dateId = useId();
  const dateErrorId = useId();

  useEffect(() => {
    textRef.current?.focus();
  }, []);

  function onSubmitForm(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    const textProblem = answerTextProblem(text);
    const dateProblem = answeredOnProblem(answeredOn, today);
    setTextError(textProblem);
    setDateError(dateProblem);
    if (textProblem) {
      textRef.current?.focus();
      return;
    }
    if (dateProblem) {
      dateRef.current?.focus();
      return;
    }
    void (async () => {
      const outcome = await onSubmit(text.trim(), answeredOn, settles);
      if (outcome !== "ok" && outcome !== "failed") setTextError(outcome.invalid);
    })();
  }

  return (
    <form
      aria-label="Record the customer’s answer"
      noValidate
      onSubmit={onSubmitForm}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          onCancel();
        }
      }}
      className="flex flex-col gap-1.5"
    >
      <label htmlFor={textId} className="text-meta text-muted-foreground">
        Customer’s answer
      </label>
      <textarea
        id={textId}
        ref={textRef}
        value={text}
        disabled={disabled}
        aria-invalid={textError ? true : undefined}
        aria-describedby={textError ? textErrorId : undefined}
        onChange={(event) => setText(event.target.value)}
        className={`${fieldClass} min-h-20 resize-y py-1`}
      />
      {textError ? (
        <p id={textErrorId} className="text-meta text-destructive">
          {textError}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={dateId} className="shrink-0 text-meta text-muted-foreground">
          Date answered
        </label>
        <input
          id={dateId}
          ref={dateRef}
          type="date"
          value={answeredOn}
          max={today}
          disabled={disabled}
          aria-invalid={dateError ? true : undefined}
          aria-describedby={dateError ? dateErrorId : undefined}
          onChange={(event) => setAnsweredOn(event.target.value)}
          className={`${fieldClass} h-6 w-auto`}
        />
      </div>
      {dateError ? (
        <p id={dateErrorId} className="text-meta text-destructive">
          {dateError}
        </p>
      ) : null}
      <label className="flex items-start gap-1.5 text-label">
        <input
          type="checkbox"
          checked={settles}
          disabled={disabled}
          onChange={(event) => setSettles(event.target.checked)}
          className="mt-0.5"
        />
        <span>
          This answer settles the Gap <span className="text-muted-foreground">“{gapTitle}”</span>
        </span>
      </label>
      <div className="flex gap-2">
        <Button type="submit" disabled={disabled} variant="outline" size="sm">
          Record answer
        </Button>
        <Button type="button" onClick={onCancel} variant="outline" size="sm">
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** The small "date sent" form: a date (today by default, never later) and a confirm button,
 * with Cancel when `onCancel` is given. A refused date shows under the field. */
export function MarkSentForm({
  label,
  confirm,
  disabled,
  onSubmit,
  onCancel,
}: {
  /** The form's accessible name. */
  label: string;
  /** The confirm button, e.g. "Mark 3 sent". */
  confirm: string;
  disabled: boolean;
  onSubmit: (sentOn: string) => Promise<GapFormOutcome>;
  onCancel?: () => void;
}) {
  const today = localToday();
  const [sentOn, setSentOn] = useState(today);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const errorId = useId();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function onSubmitForm(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    const problem = sentOnProblem(sentOn, today);
    setError(problem);
    if (problem) {
      inputRef.current?.focus();
      return;
    }
    void (async () => {
      const outcome = await onSubmit(sentOn);
      if (outcome !== "ok" && outcome !== "failed") setError(outcome.invalid);
    })();
  }

  return (
    <form
      aria-label={label}
      noValidate
      onSubmit={onSubmitForm}
      onKeyDown={(event) => {
        if (event.key === "Escape" && onCancel) {
          event.preventDefault();
          event.stopPropagation();
          onCancel();
        }
      }}
      className="flex flex-col gap-1.5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={inputId} className="shrink-0 text-meta text-muted-foreground">
          Date sent
        </label>
        <input
          id={inputId}
          ref={inputRef}
          type="date"
          value={sentOn}
          max={today}
          required
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => setSentOn(event.target.value)}
          className={`${fieldClass} h-6 w-auto`}
        />
        <Button type="submit" disabled={disabled} variant="outline" size="sm">
          {confirm}
        </Button>
        {onCancel ? (
          <Button type="button" onClick={onCancel} variant="outline" size="sm">
            Cancel
          </Button>
        ) : null}
      </div>
      {error ? (
        <p id={errorId} className="text-meta text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}

/** How a Gap write ended, as the inspector's forms need it: `ok` clears the form, `invalid`
 * shows the reason under it; `failed` was handled elsewhere (a notice or the stale view). */
export type GapFormOutcome = "ok" | "failed" | { invalid: string };

/** What the inspector needs to change the Gap's impact, dismiss and reopen it (Story 4.4). */
export type GapEditing = {
  /** A write of this Gap is in flight. */
  busy: boolean;
  /** Nothing may be changed (a stale view, or a reload or approval in flight). */
  locked: boolean;
  onImpact: (impact: Impact, reason: string) => Promise<GapFormOutcome>;
  onDismiss: (kind: DismissReasonKind, note: string) => Promise<GapFormOutcome>;
  onReopen: (reason: string) => Promise<GapFormOutcome>;
};

const fieldClass = reasonFieldClass;

/** Run a form's write; clear it on success, show a 422 under it. */
async function submitForm(
  write: () => Promise<GapFormOutcome>,
  onOk: () => void,
  setError: (error: string | null) => void,
) {
  const outcome = await write();
  if (outcome === "ok") onOk();
  else if (outcome !== "failed") setError(outcome.invalid);
}

/** Impact: a select plus a required reason, then Save. */
function ImpactForm({ gap, edit }: { gap: Gap; edit: GapEditing }) {
  const [impact, setImpact] = useState<Impact>(gap.impact);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const selectId = useId();
  const disabled = edit.busy || edit.locked;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    const problem = reasonProblem(reason);
    setError(problem);
    if (problem) {
      reasonRef.current?.focus();
      return;
    }
    void submitForm(
      () => edit.onImpact(impact, reason.trim()),
      () => setReason(""),
      setError,
    );
  }

  return (
    <form aria-label="Change impact" onSubmit={onSubmit} className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <label htmlFor={selectId} className="shrink-0 whitespace-nowrap text-meta text-muted-foreground">
          New impact
        </label>
        <select
          id={selectId}
          value={impact}
          disabled={disabled}
          onChange={(event) => setImpact(event.target.value as Impact)}
          className={`${fieldClass} h-6 w-auto`}
        >
          {IMPACTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <ReasonInput
        label="Reason for the change"
        value={reason}
        onChange={setReason}
        error={error}
        disabled={disabled}
        inputRef={reasonRef}
      />
      <div>
        <Button type="submit" disabled={disabled} variant="outline" size="sm">
          Save
        </Button>
      </div>
    </form>
  );
}

/** Dismiss: "Not relevant" / "Other", a note (required for Other), then Dismiss. */
function DismissForm({ edit }: { edit: GapEditing }) {
  const [kind, setKind] = useState<DismissReasonKind>("not_relevant");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const groupName = useId();
  const disabled = edit.busy || edit.locked;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    const problem = noteProblem(kind, note);
    setError(problem);
    if (problem) {
      noteRef.current?.focus();
      return;
    }
    void submitForm(
      () => edit.onDismiss(kind, note.trim()),
      () => setNote(""),
      setError,
    );
  }

  return (
    <form aria-label="Dismiss the Gap" onSubmit={onSubmit} className="flex flex-col gap-1.5">
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 text-meta text-muted-foreground">Reason</legend>
        <div className="flex gap-3">
          {DISMISS_REASONS.map((option) => (
            <label key={option.value} className="flex items-center gap-1.5 text-label">
              <input
                type="radio"
                name={groupName}
                value={option.value}
                checked={kind === option.value}
                disabled={disabled}
                onChange={() => setKind(option.value)}
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>
      <ReasonInput
        label={kind === "other" ? "Note" : "Note (optional)"}
        value={note}
        onChange={setNote}
        error={error}
        disabled={disabled}
        inputRef={noteRef}
      />
      <div>
        <Button
          type="submit"
          disabled={disabled}
          variant="outline"
          size="sm"
          className="text-blocker"
        >
          Dismiss
        </Button>
      </div>
    </form>
  );
}

/** Reopen: a required reason, then Reopen. */
function ReopenForm({ edit }: { edit: GapEditing }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const disabled = edit.busy || edit.locked;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    const problem = reasonProblem(reason);
    setError(problem);
    if (problem) {
      reasonRef.current?.focus();
      return;
    }
    void submitForm(
      () => edit.onReopen(reason.trim()),
      () => setReason(""),
      setError,
    );
  }

  return (
    <form aria-label="Reopen the Gap" onSubmit={onSubmit} className="flex flex-col gap-1.5">
      <ReasonInput
        label="Reason for reopening"
        value={reason}
        onChange={setReason}
        error={error}
        disabled={disabled}
        inputRef={reasonRef}
      />
      <div>
        <Button type="submit" disabled={disabled} variant="outline" size="sm">
          Reopen
        </Button>
      </div>
    </form>
  );
}

/** The Gap's history, oldest first: what happened, who and when, and the reason (left out
 * for sales representatives by the API). */
function GapHistory({ history }: { history: readonly GapHistoryEntry[] }) {
  return (
    <div className="flex flex-col gap-2 p-4">
      <SectionHeading>History</SectionHeading>
      <ol aria-label="Gap history" className="flex flex-col gap-2.5">
        {history.map((entry, index) => (
          <li
            key={`${entry.kind}-${entry.at}-${index}`}
            className="flex flex-col border-l-2 border-border pl-3"
          >
            <span className="text-body">{historyAction(entry)}</span>
            <span className="text-meta text-text-secondary">{historyByline(entry)}</span>
            {entry.reason ? (
              <span className="whitespace-pre-wrap break-words text-meta">{entry.reason}</span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
