"use client";

import { useEffect, useId, useRef } from "react";

import { ImpactBar } from "@/components/opportunities/impact-bar";
import { categoryLabel, DRAFT, type Gap } from "@/lib/gaps";

/** The question status pill. The demo only drafts questions: "Draft". 20px, fully rounded,
 * neutral outline, like the other status pills. */
export function QuestionPill() {
  return (
    <span className="inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full border border-border bg-background px-2 text-label text-foreground">
      {DRAFT}
    </span>
  );
}

/** The selected Gap in the right pane, read-only: its title and category, why it matters,
 * its impact and the basis for it, the related Requirements as chips with their excerpts,
 * and the drafted Clarification Question with its topic in a bordered block. */
export function GapInspector({ gap, focusRequest = 0 }: { gap: Gap; focusRequest?: number }) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

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

      {gap.question ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-label text-muted-foreground">Clarification Question</h4>
            <QuestionPill />
          </div>
          <div
            role="group"
            aria-label="Clarification Question (read-only)"
            className="flex flex-col gap-1 rounded-md border border-border p-2"
          >
            <p className="text-meta text-muted-foreground">{gap.question.topic}</p>
            <p className="whitespace-pre-wrap break-words text-body">{gap.question.text}</p>
          </div>
        </div>
      ) : null}
    </section>
  );
}
