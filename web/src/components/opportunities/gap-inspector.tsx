"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { ImpactBar } from "@/components/opportunities/impact-bar";
import { InlineField } from "@/components/opportunities/inline-field";
import { ReasonInput, reasonFieldClass } from "@/components/opportunities/reason-input";
import {
  approvedLabel,
  categoryLabel,
  DISMISS_REASONS,
  dismissedLabel,
  gapStatus,
  historyAction,
  historyByline,
  IMPACTS,
  isSent,
  localToday,
  noteProblem,
  questionStatus,
  reasonProblem,
  sentLabel,
  sentOnProblem,
  statusSince,
  triggerLabel,
  type DismissReasonKind,
  type Gap,
  type GapHistoryEntry,
  type GapStatus,
  type Impact,
  type QuestionStatus,
} from "@/lib/gaps";
import { cn } from "@/lib/utils";

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

/** The question status pill: "Draft" or "Approved", always an icon and a label. 20px, fully
 * rounded, neutral outline, like the other status pills; only the icon is tinted. */
export function QuestionPill({ status }: { status: QuestionStatus }) {
  const known = questionStatus(status);
  const Icon = known.icon;
  return (
    <span
      data-question-status={status}
      className="inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground"
    >
      <Icon className={cn("size-3 shrink-0", known.tone)} aria-hidden="true" />
      {known.label}
    </span>
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

/** The selected Gap in the right pane: its status, title and category, why it matters, its
 * trigger, its impact and the basis for it, the related Requirements as chips with their
 * excerpts, its Clarification Question with its topic, status pill and the date of its last
 * status change, and its history (Story 4.4). With `edit` (and the Gap open), the topic and
 * text are click-to-edit (Enter or blur saves, Esc reverts), a drafted question has
 * **Approve**; an approved one says who approved it and when. With `gapEdit`, an open Gap has
 * an impact select with a required reason and a **Dismiss** form ("Not relevant" / "Other"
 * with a note); a dismissed one says why, by whom and when, and has **Reopen** with a reason.
 * Convert is not offered here (Epic 8 does it from the Estimate). With `send` (Story 4.6), an
 * approved question of an open Gap has **Mark sent** (a date, today by default) and a sent one
 * **No answer**; a sent question says "Sent {date} by {name}" and can't be edited or approved.
 * Without them, read-only. */
export function GapInspector({
  gap,
  focusRequest = 0,
  edit,
  gapEdit,
  send,
}: {
  gap: Gap;
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

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <p className="text-meta text-muted-foreground">{categoryLabel(gap.category)}</p>
          <GapStatusPill status={gap.status} />
        </div>
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

      {gap.dismissal ? (
        <div className="flex flex-col gap-1">
          <p className="text-meta text-muted-foreground">{dismissedLabel(gap.dismissal)}</p>
          {gap.dismissal.note ? (
            <p className="whitespace-pre-wrap break-words text-body">{gap.dismissal.note}</p>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Trigger</h4>
        <p className="text-body">{triggerLabel(gap)}</p>
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Impact</h4>
        <ImpactBar impact={gap.impact} />
        <p className="whitespace-pre-wrap break-words text-body">{gap.impact_basis}</p>
        {gapEdit && gap.status === "open" ? (
          <ImpactForm key={`${gap.id}-${gap.row_version}`} gap={gap} edit={gapEdit} />
        ) : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <h4 className="text-label text-muted-foreground">Related Requirements</h4>
        <ul className="flex flex-col gap-1.5">
          {gap.requirements.map((requirement) => (
            <li key={requirement.id} className="flex items-baseline gap-2">
              <span className="inline-flex h-5 shrink-0 items-center rounded-sm border border-border bg-background px-1.5 font-mono text-meta text-muted-foreground">
                {requirement.label}
              </span>
              <span className="min-w-0 break-words text-body">{requirement.excerpt}</span>
            </li>
          ))}
        </ul>
      </div>

      {question ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-label text-muted-foreground">Clarification Question</h4>
            <QuestionPill status={question.status} />
          </div>
          <p className="text-meta text-muted-foreground">{statusSince(question)}</p>
          {editable ? (
            <div
              role="group"
              aria-label="Clarification Question"
              aria-busy={edit.busy || undefined}
              className="flex flex-col gap-1 rounded-md border border-border p-2"
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
                inputClassName="h-6 w-full rounded-md border border-input bg-transparent px-1.5 text-meta outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <p className="text-meta text-muted-foreground">{question.topic}</p>
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
                inputClassName="min-h-16 w-full resize-y rounded-md border border-input bg-transparent px-1.5 py-1 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <p className="whitespace-pre-wrap break-words text-body">{question.text}</p>
              </InlineField>
            </div>
          ) : (
            <div
              role="group"
              aria-label="Clarification Question (read-only)"
              className="flex flex-col gap-1 rounded-md border border-border p-2"
            >
              <p className="text-meta text-muted-foreground">{question.topic}</p>
              <p className="whitespace-pre-wrap break-words text-body">{question.text}</p>
            </div>
          )}
          {question.status === "approved" || isSent(question.status) ? (
            <p className="text-meta text-muted-foreground">{approvedLabel(question)}</p>
          ) : editable ? (
            <div>
              <button
                type="button"
                disabled={edit.locked || edit.busy}
                onClick={edit.onApprove}
                className={actionClass}
              >
                Approve
              </button>
            </div>
          ) : null}
          {isSent(question.status) ? (
            <p className="text-meta text-muted-foreground">{sentLabel(question)}</p>
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
                <button
                  type="button"
                  disabled={send.busy || send.locked}
                  onClick={() => setMarkingSent(true)}
                  className={actionClass}
                >
                  Mark sent
                </button>
              </div>
            )
          ) : null}
          {sendable && question.status === "sent" ? (
            <div>
              <button
                type="button"
                disabled={send.busy || send.locked}
                onClick={send.onNoAnswer}
                className={actionClass}
              >
                No answer
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {gapEdit && gap.status === "open" ? (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-label text-muted-foreground">Dismiss</h4>
          <DismissForm edit={gapEdit} />
        </div>
      ) : null}
      {gapEdit && gap.status === "dismissed" ? (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-label text-muted-foreground">Reopen</h4>
          <ReopenForm edit={gapEdit} />
        </div>
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
    <span
      data-gap-status={status}
      className="inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground"
    >
      <Icon className={cn("size-3 shrink-0", known.tone)} aria-hidden="true" />
      {known.label}
    </span>
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
};

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
        <button type="submit" disabled={disabled} className={actionClass}>
          {confirm}
        </button>
        {onCancel ? (
          <button type="button" onClick={onCancel} className={actionClass}>
            Cancel
          </button>
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
        <button type="submit" disabled={disabled} className={actionClass}>
          Save
        </button>
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
        <button type="submit" disabled={disabled} className={actionClass}>
          Dismiss
        </button>
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
        <button type="submit" disabled={disabled} className={actionClass}>
          Reopen
        </button>
      </div>
    </form>
  );
}

/** The Gap's history, oldest first: what happened, who and when, and the reason (left out
 * for sales representatives by the API). */
function GapHistory({ history }: { history: readonly GapHistoryEntry[] }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h4 className="text-label text-muted-foreground">History</h4>
      <ol aria-label="Gap history" className="flex flex-col gap-1.5">
        {history.map((entry, index) => (
          <li key={`${entry.kind}-${entry.at}-${index}`} className="flex flex-col">
            <span className="text-body">{historyAction(entry)}</span>
            <span className="text-meta text-muted-foreground">{historyByline(entry)}</span>
            {entry.reason ? (
              <span className="whitespace-pre-wrap break-words text-meta">{entry.reason}</span>
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
