"use client";

import { CheckIcon, GitCompareArrowsIcon, QuoteIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type Ref } from "react";

import { getPassage, type PassageResult } from "@/app/opportunities/actions";
import { InlineField } from "@/components/opportunities/inline-field";
import { ReasonInput } from "@/components/opportunities/reason-input";
import { RequirementDiff } from "@/components/opportunities/requirement-diff";
import { reasonProblem } from "@/lib/gaps";
import {
  ACCEPT_CHANGE,
  CLASSIFICATIONS,
  classificationLabel,
  CONFIRMED,
  DELETE_REASON_LABEL,
  DELETE_REQUIREMENT,
  LOADING_PASSAGE,
  NO_EVIDENCE,
  PASSAGE_FAILED,
  PASSAGE_GONE,
  PENDING_CHANGE,
  REJECT_CHANGE,
  REJECT_REASON_LABEL,
  requirementLabel,
  requirementOrigin,
  requirementTextProblem,
  SPLIT_REQUIREMENT,
  type Classification,
  type Passage,
  type PendingChange,
  type Requirement,
  type RequirementEvidence,
} from "@/lib/requirements";

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

/** An Evidence chip: a kind icon and the label (`S1 · call.vtt`) in meta type. A button that
 * shows the cited passage; `pressed` marks the one shown in the inspector. */
export function EvidenceChip({
  evidence,
  pressed,
  tabIndex,
  onSelect,
  ref,
}: {
  evidence: RequirementEvidence;
  /** Set in the inspector (`aria-pressed`); left out in the list. */
  pressed?: boolean;
  tabIndex?: number;
  /** `viaKeyboard` is true when activated with Enter or Space, not a pointer. */
  onSelect: (viaKeyboard: boolean) => void;
  ref?: Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={ref}
      type="button"
      data-passage-id={evidence.passage_id}
      aria-pressed={pressed}
      tabIndex={tabIndex}
      // A keyboard-activated click has no pointer clicks (detail 0).
      onClick={(event) => onSelect(event.detail === 0)}
      className={`inline-flex h-5 max-w-full items-center gap-1 rounded-sm border px-1.5 text-meta outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary ${
        pressed
          ? "border-primary bg-diff-tint text-foreground"
          : "border-border bg-background text-muted-foreground"
      }`}
    >
      <QuoteIcon aria-hidden="true" className="size-3 shrink-0" />
      <span className="truncate">{evidence.label}</span>
    </button>
  );
}

/** A loaded passage: the file name and version, then the text before, the cited span in a
 * `<mark>`, and the text after, with whitespace and line breaks kept. */
export function PassageView({ passage }: { passage: Passage }) {
  return (
    <figure className="flex flex-col gap-1.5">
      <figcaption className="flex items-baseline gap-2 text-meta text-muted-foreground">
        <span className="truncate">{passage.filename}</span>
        <span className="shrink-0 font-mono">v{passage.source_version}</span>
      </figcaption>
      <blockquote className="whitespace-pre-wrap break-words text-body">
        {passage.before}
        <mark className="rounded-sm bg-evidence-highlight text-foreground underline decoration-primary decoration-2 underline-offset-2">
          {passage.text}
        </mark>
        {passage.after}
      </blockquote>
    </figure>
  );
}

type Loaded = { key: string; result: PassageResult };

/** The amber "Pending change" marker (an icon and the words, never colour alone). */
export function PendingChangeMarker() {
  return (
    <span className="inline-flex items-center gap-1 text-meta text-gap">
      <GitCompareArrowsIcon aria-hidden="true" className="size-3 shrink-0" />
      {PENDING_CHANGE}
    </span>
  );
}

/** How a pending-change write ended, as the reject form needs it: `ok` closes it, `invalid`
 * shows the reason under it; `failed` was handled elsewhere (a notice or the stale view). */
export type ChangeFormOutcome = "ok" | "failed" | { invalid: string };

/** The Pending change section (Story 2.7): the current text as a `−` line and the proposed
 * text as a `+` line, both on the diff tint; the classification change, if any; the new
 * Evidence chips; and, with `edit`, **Accept**, and **Reject**, which asks for a reason. */
function PendingChangeView({
  requirement,
  pending,
  shownId,
  onSelectPassage,
  edit,
}: {
  requirement: Requirement;
  pending: PendingChange;
  shownId: string | null;
  onSelectPassage: (passageId: string) => void;
  edit?: InspectorEditing;
}) {
  const headingId = useId();
  const evidenceId = useId();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const disabled = !edit || edit.locked || edit.busy;

  useEffect(() => {
    if (rejecting) reasonRef.current?.focus();
  }, [rejecting]);

  function onReject(event: FormEvent) {
    event.preventDefault();
    if (!edit || disabled) return;
    const problem = reasonProblem(reason);
    setError(problem);
    if (problem) {
      reasonRef.current?.focus();
      return;
    }
    void edit.onReject(reason.trim()).then((outcome) => {
      if (outcome === "ok") {
        setRejecting(false);
        setReason("");
      } else if (outcome !== "failed") {
        setError(outcome.invalid);
      }
    });
  }

  return (
    <section
      aria-labelledby={headingId}
      data-testid="pending-change"
      className="flex flex-col gap-2 rounded-md border border-border p-2"
    >
      <h4 id={headingId} className="flex items-center gap-1 text-label text-gap">
        <GitCompareArrowsIcon aria-hidden="true" className="size-3 shrink-0" />
        {PENDING_CHANGE}
      </h4>
      <RequirementDiff
        before={requirement}
        after={pending}
        beforeLabel="Current"
        afterLabel="Proposed"
      />
      {pending.evidence.length > 0 ? (
        <div className="flex flex-col gap-1">
          <span id={evidenceId} className="text-meta text-muted-foreground">
            New Evidence
          </span>
          <div role="group" aria-labelledby={evidenceId} className="flex flex-wrap gap-1.5">
            {pending.evidence.map((evidence) => (
              <EvidenceChip
                key={evidence.passage_id}
                evidence={evidence}
                pressed={evidence.passage_id === shownId}
                onSelect={() => onSelectPassage(evidence.passage_id)}
              />
            ))}
          </div>
        </div>
      ) : null}
      {edit && !rejecting ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={disabled}
            onClick={edit.onAccept}
            className={`${actionClass} disabled:opacity-60`}
          >
            {ACCEPT_CHANGE}
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => {
              setError(null);
              setRejecting(true);
            }}
            className={`${actionClass} disabled:opacity-60`}
          >
            {REJECT_CHANGE}
          </button>
        </div>
      ) : null}
      {edit && rejecting ? (
        <form onSubmit={onReject} className="flex flex-col gap-2" noValidate>
          <ReasonInput
            label={REJECT_REASON_LABEL}
            value={reason}
            onChange={setReason}
            error={error}
            disabled={edit.busy}
            inputRef={reasonRef}
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              disabled={disabled}
              className={`${actionClass} disabled:opacity-60`}
            >
              Reject change
            </button>
            <button
              type="button"
              disabled={edit.busy}
              onClick={() => {
                setRejecting(false);
                setError(null);
              }}
              className={`${actionClass} disabled:opacity-60`}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

const fieldClass =
  "w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-[invalid=true]:border-destructive";
const PARTS = ["First", "Second"] as const;

/** One of the two Requirements a split makes. */
export type SplitPart = { text: string; classification: Classification };

/** **Split** (Story 2.6): two text fields, each prefilled with the Requirement's text and with
 * its classification select. Both new Requirements cite all its Evidence. */
function SplitForm({
  requirement,
  edit,
  onClose,
}: {
  requirement: Requirement;
  edit: InspectorEditing;
  onClose: () => void;
}) {
  const ids = [useId(), useId()];
  const classIds = [useId(), useId()];
  const errorIds = [useId(), useId()];
  const formErrorId = useId();
  const firstRef = useRef<HTMLTextAreaElement>(null);
  const [parts, setParts] = useState<SplitPart[]>(() =>
    PARTS.map(() => ({ text: requirement.text, classification: requirement.classification })),
  );
  const [errors, setErrors] = useState<(string | null)[]>([null, null]);
  const [formError, setFormError] = useState<string | null>(null);
  const disabled = edit.locked || edit.busy;

  useEffect(() => {
    firstRef.current?.focus();
  }, []);

  function update(index: number, change: Partial<SplitPart>) {
    setParts((current) => current.map((p, i) => (i === index ? { ...p, ...change } : p)));
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    const problems = parts.map((p) => requirementTextProblem(p.text));
    setErrors(problems);
    setFormError(null);
    if (problems.some((p) => p !== null)) return;
    const [first, second] = parts.map((p) => ({ ...p, text: p.text.trim() }));
    void edit.onSplit([first!, second!]).then((outcome) => {
      if (outcome === "ok") onClose();
      else if (outcome !== "failed") setFormError(outcome.invalid);
    });
  }

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      aria-label="Split Requirement"
      aria-describedby={formError ? formErrorId : undefined}
      className="flex flex-col gap-2 rounded-md border border-border p-2"
    >
      {PARTS.map((name, index) => (
        <div key={name} className="flex flex-col gap-1">
          <label htmlFor={ids[index]} className="text-meta text-muted-foreground">
            {`${name} Requirement`}
          </label>
          <textarea
            id={ids[index]}
            ref={index === 0 ? firstRef : undefined}
            rows={2}
            value={parts[index]!.text}
            disabled={disabled}
            aria-invalid={errors[index] ? true : undefined}
            aria-describedby={errors[index] ? errorIds[index] : undefined}
            onChange={(event) => update(index, { text: event.target.value })}
            className={`${fieldClass} py-1`}
          />
          {errors[index] ? (
            <p id={errorIds[index]} className="text-meta text-destructive">
              {errors[index]}
            </p>
          ) : null}
          <label htmlFor={classIds[index]} className="sr-only">
            {`${name} Requirement classification`}
          </label>
          <select
            id={classIds[index]}
            value={parts[index]!.classification}
            disabled={disabled}
            onChange={(event) =>
              update(index, { classification: event.target.value as Classification })
            }
            className="h-7 w-fit rounded-md border border-input bg-background px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60"
          >
            {CLASSIFICATIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      ))}
      {formError ? (
        <p id={formErrorId} className="text-meta text-destructive">
          {formError}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={disabled} className={`${actionClass} disabled:opacity-60`}>
          Split Requirement
        </button>
        <button
          type="button"
          disabled={edit.busy}
          onClick={onClose}
          className={`${actionClass} disabled:opacity-60`}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

/** **Delete** (Story 2.6): asks why (the shared reason field), then removes the Requirement
 * from the list; it stays in history. */
function DeleteForm({ edit, onClose }: { edit: InspectorEditing; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const disabled = edit.locked || edit.busy;

  useEffect(() => {
    reasonRef.current?.focus();
  }, []);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    const problem = reasonProblem(reason);
    setError(problem);
    if (problem) {
      reasonRef.current?.focus();
      return;
    }
    void edit.onDelete(reason.trim()).then((outcome) => {
      if (outcome === "ok") onClose();
      else if (outcome !== "failed") setError(outcome.invalid);
    });
  }

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      aria-label="Delete Requirement"
      className="flex flex-col gap-2 rounded-md border border-border p-2"
    >
      <ReasonInput
        label={DELETE_REASON_LABEL}
        value={reason}
        onChange={setReason}
        error={error}
        disabled={edit.busy}
        inputRef={reasonRef}
      />
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={disabled} className={`${actionClass} disabled:opacity-60`}>
          Delete Requirement
        </button>
        <button
          type="button"
          disabled={edit.busy}
          onClick={onClose}
          className={`${actionClass} disabled:opacity-60`}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

/** What the inspector needs to edit and confirm the Requirement (Story 2.6). */
export type InspectorEditing = {
  /** A save or confirmation of this Requirement is in flight. */
  busy: boolean;
  /** Nothing may be changed (a stale view, or a reload or Confirm all in flight). */
  locked: boolean;
  /** Why the last text save from here failed, and the user's text it kept. */
  failure?: { text: string; error: string } | null;
  onCommitText: (text: string) => void;
  onClassify: (classification: Classification) => void;
  onConfirm: () => void;
  /** Accept the pending change (Story 2.7). */
  onAccept: () => void;
  /** Reject the pending change with this (trimmed) reason. */
  onReject: (reason: string) => Promise<ChangeFormOutcome>;
  /** Split the Requirement into these two (trimmed) Requirements. */
  onSplit: (parts: [SplitPart, SplitPart]) => Promise<ChangeFormOutcome>;
  /** Delete the Requirement with this (trimmed) reason. */
  onDelete: (reason: string) => Promise<ChangeFormOutcome>;
};

/** The selected Requirement in the right pane: its text, classification and origin, its
 * pending change (Story 2.7), its Evidence chips in citation order, and the shown chip's
 * passage (one of its own or of the pending change) highlighted in its surrounding text.
 * With `edit`, the text is click-to-edit, the classification a select, an unconfirmed
 * Requirement has **Confirm**, a pending change **Accept** and **Reject**, and every
 * Requirement **Split** and **Delete** (Story 2.6); without it, read-only. The header shows
 * its stable `R<n>` and its origin ("Manual" for one a person added). */
export function RequirementInspector({
  opportunityId,
  requirement,
  passageId,
  onSelectPassage,
  focusRequest = 0,
  edit,
}: {
  opportunityId: string;
  requirement: Requirement;
  /** The passage shown (null or one not cited: the first). */
  passageId: string | null;
  onSelectPassage: (passageId: string) => void;
  /** Bump to move keyboard focus to the shown chip (0: leave focus alone). */
  focusRequest?: number;
  /** Left out for those who may not edit. */
  edit?: InspectorEditing;
}) {
  const headingId = useId();
  const classificationId = useId();
  const evidenceId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const pressedRef = useRef<HTMLButtonElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  /** The Split or Delete form, while open (Story 2.6). */
  const [shaping, setShaping] = useState<"split" | "delete" | null>(null);
  const pending = requirement.pending_change;
  const shown =
    [...requirement.evidence, ...(pending?.evidence ?? [])].find(
      (e) => e.passage_id === passageId,
    ) ?? requirement.evidence[0];
  const shownId = shown?.passage_id ?? null;
  const key = `${shownId}:${attempt}`;
  const result = loaded?.key === key ? loaded.result : null;

  useEffect(() => {
    if (focusRequest <= 0) return;
    (pressedRef.current ?? headingRef.current)?.focus();
  }, [focusRequest]);

  useEffect(() => {
    if (shownId === null) return;
    let cancelled = false;
    const requested = `${shownId}:${attempt}`;
    getPassage(opportunityId, shownId)
      .catch((): PassageResult => ({ kind: "error" }))
      .then((next) => {
        if (!cancelled) setLoaded({ key: requested, result: next });
      });
    return () => {
      cancelled = true;
    };
  }, [opportunityId, shownId, attempt]);

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-4 p-gutter"
    >
      <div className="flex flex-col gap-1">
        <p className="flex flex-wrap items-center gap-2 text-meta text-muted-foreground">
          <span className="font-mono">{requirementLabel(requirement)}</span>
          <span aria-hidden="true">·</span>
          <span>{classificationLabel(requirement.classification)}</span>
          <span aria-hidden="true">·</span>
          <span>{requirementOrigin(requirement)}</span>
          {requirement.confirmed_at ? (
            <>
              <span aria-hidden="true">·</span>
              <span className="inline-flex items-center gap-1 text-foreground">
                <CheckIcon aria-hidden="true" className="size-3 shrink-0 text-resolved" />
                {CONFIRMED}
              </span>
            </>
          ) : null}
        </p>
        {edit ? (
          <InlineField
            label="Edit Requirement text"
            inputLabel="Requirement text"
            type="text"
            value={requirement.text}
            draft={edit.failure?.text}
            error={edit.failure?.error}
            locked={edit.locked || edit.busy}
            onCommit={edit.onCommitText}
            className="flex flex-col gap-0.5"
            inputClassName="h-8 w-full rounded-md border border-input bg-transparent px-1.5 text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <h3
              id={headingId}
              ref={headingRef}
              tabIndex={-1}
              className="text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              {requirement.text}
            </h3>
          </InlineField>
        ) : (
          <h3
            id={headingId}
            ref={headingRef}
            tabIndex={-1}
            className="text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            {requirement.text}
          </h3>
        )}
      </div>
      {edit ? (
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-0.5">
            <label htmlFor={classificationId} className="text-label text-muted-foreground">
              Classification
            </label>
            <select
              id={classificationId}
              value={requirement.classification}
              disabled={edit.locked || edit.busy}
              onChange={(event) => edit.onClassify(event.target.value as Classification)}
              className="h-7 rounded-md border border-input bg-background px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60"
            >
              {CLASSIFICATIONS.map(({ value, label }) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          {requirement.confirmed_at ? null : (
            <button
              type="button"
              disabled={edit.locked || edit.busy}
              onClick={edit.onConfirm}
              className={`${actionClass} disabled:opacity-60`}
            >
              Confirm
            </button>
          )}
          <button
            type="button"
            disabled={edit.locked || edit.busy}
            aria-expanded={shaping === "split"}
            onClick={() => setShaping((current) => (current === "split" ? null : "split"))}
            className={`${actionClass} disabled:opacity-60`}
          >
            {SPLIT_REQUIREMENT}
          </button>
          <button
            type="button"
            disabled={edit.locked || edit.busy}
            aria-expanded={shaping === "delete"}
            onClick={() => setShaping((current) => (current === "delete" ? null : "delete"))}
            className={`${actionClass} disabled:opacity-60`}
          >
            {DELETE_REQUIREMENT}
          </button>
        </div>
      ) : null}
      {edit && shaping === "split" ? (
        <SplitForm requirement={requirement} edit={edit} onClose={() => setShaping(null)} />
      ) : null}
      {edit && shaping === "delete" ? (
        <DeleteForm edit={edit} onClose={() => setShaping(null)} />
      ) : null}
      {pending ? (
        <PendingChangeView
          key={pending.id}
          requirement={requirement}
          pending={pending}
          shownId={shownId}
          onSelectPassage={onSelectPassage}
          edit={edit}
        />
      ) : null}
      <div className="flex flex-col gap-1.5">
        <h4 id={evidenceId} className="text-label text-muted-foreground">
          Evidence
        </h4>
        {requirement.evidence.length > 0 ? (
          <div
            role="group"
            aria-labelledby={evidenceId}
            className="flex flex-wrap gap-1.5"
          >
            {requirement.evidence.map((evidence) => {
              const pressed = evidence.passage_id === shownId;
              return (
                <EvidenceChip
                  key={evidence.passage_id}
                  ref={pressed ? pressedRef : undefined}
                  evidence={evidence}
                  pressed={pressed}
                  onSelect={() => onSelectPassage(evidence.passage_id)}
                />
              );
            })}
          </div>
        ) : (
          <p className="text-muted-foreground">{NO_EVIDENCE}</p>
        )}
      </div>
      {shownId !== null ? (
        <div aria-busy={result === null} className="flex flex-col gap-1.5">
          {result === null ? (
            <p role="status" className="text-muted-foreground">
              {LOADING_PASSAGE}
            </p>
          ) : result.kind === "ok" ? (
            <PassageView passage={result.passage} />
          ) : result.kind === "not-found" ? (
            <p role="status" className="text-muted-foreground">
              {PASSAGE_GONE}
            </p>
          ) : (
            <div className="flex flex-col items-start gap-1">
              <p role="status" className="text-destructive">
                {PASSAGE_FAILED}
              </p>
              <button
                type="button"
                onClick={() => setAttempt((n) => n + 1)}
                className={actionClass}
              >
                Retry
              </button>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
