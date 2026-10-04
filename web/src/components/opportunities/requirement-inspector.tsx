"use client";

import { QuoteIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type Ref } from "react";

import { getPassage, type PassageResult } from "@/app/opportunities/actions";
import {
  classificationLabel,
  LOADING_PASSAGE,
  originLabel,
  PASSAGE_FAILED,
  PASSAGE_GONE,
  type Passage,
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

/** The selected Requirement in the right pane: its text, classification and origin, its
 * Evidence chips in citation order, and the shown chip's passage highlighted in its
 * surrounding text. Read-only. */
export function RequirementInspector({
  opportunityId,
  requirement,
  passageId,
  onSelectPassage,
  focusRequest = 0,
}: {
  opportunityId: string;
  requirement: Requirement;
  /** The passage shown (null or one not cited: the first). */
  passageId: string | null;
  onSelectPassage: (passageId: string) => void;
  /** Bump to move keyboard focus to the shown chip (0: leave focus alone). */
  focusRequest?: number;
}) {
  const headingId = useId();
  const evidenceId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const pressedRef = useRef<HTMLButtonElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const shown =
    requirement.evidence.find((e) => e.passage_id === passageId) ??
    requirement.evidence[0];
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
        <p className="flex items-center gap-2 text-meta text-muted-foreground">
          <span>{classificationLabel(requirement.classification)}</span>
          <span aria-hidden="true">·</span>
          <span>{originLabel(requirement.origin)}</span>
        </p>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {requirement.text}
        </h3>
      </div>
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
          <p className="text-muted-foreground">No Evidence.</p>
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
