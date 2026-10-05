"use client";

import { useEffect, useId, useRef } from "react";

import { ImpactBar } from "@/components/opportunities/impact-bar";
import { InlineField } from "@/components/opportunities/inline-field";
import {
  approvedLabel,
  categoryLabel,
  questionStatus,
  statusSince,
  type Gap,
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

/** The selected Gap in the right pane: its title and category, why it matters, its impact
 * and the basis for it, the related Requirements as chips with their excerpts, and its
 * Clarification Question with its topic, status pill and the date of its last status change.
 * With `edit` (and the Gap open), the topic and text are click-to-edit (Enter or blur saves,
 * Esc reverts), a drafted question has **Approve**; an approved one says who approved it and
 * when. Without `edit`, read-only. */
export function GapInspector({
  gap,
  focusRequest = 0,
  edit,
}: {
  gap: Gap;
  focusRequest?: number;
  /** Left out for those who may not edit. */
  edit?: QuestionEditing;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const question = gap.question;
  const editable = edit !== undefined && gap.status === "open" && question !== null;

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <p className="text-meta text-muted-foreground">{categoryLabel(gap.category)}</p>
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
        <p className="whitespace-pre-wrap break-words text-body">{gap.impact_basis}</p>
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
          {question.status === "approved" ? (
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
        </div>
      ) : null}
    </section>
  );
}
