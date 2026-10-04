"use client";

import { useEffect, useId, useRef } from "react";

import { SeverityPill } from "@/components/opportunities/severity-pill";
import { hours, sectionLabel, type SectionName } from "@/lib/estimates";
import { categoryLabel, type RedTeamFinding } from "@/lib/red-team";

/** The selected Red Team Finding in the right pane, read-only: its severity, category and
 * title, the Red Team's argument, the Requirements it challenges as chips with their
 * excerpts, and the Estimate lines it challenges with their section and effort. */
export function RedTeamInspector({
  finding,
  focusRequest = 0,
}: {
  finding: RedTeamFinding;
  focusRequest?: number;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityPill severity={finding.severity} />
          <p className="text-meta text-muted-foreground">{categoryLabel(finding.category)}</p>
        </div>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {finding.title}
        </h3>
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Argument</h4>
        <p className="whitespace-pre-wrap break-words text-body">{finding.argument}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <h4 className="text-label text-muted-foreground">Challenged Requirements</h4>
        <ul className="flex flex-col gap-1.5">
          {finding.requirements.map((requirement) => (
            <li key={requirement.id} className="flex items-baseline gap-2">
              <span className="inline-flex h-5 shrink-0 items-center rounded-sm border border-border bg-background px-1.5 font-mono text-meta text-muted-foreground">
                {requirement.label}
              </span>
              <span className="min-w-0 break-words text-body">{requirement.excerpt}</span>
            </li>
          ))}
        </ul>
      </div>

      {finding.lines.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-label text-muted-foreground">Challenged Estimate lines</h4>
          <ul className="flex flex-col gap-1.5">
            {finding.lines.map((line) => (
              <li key={line.id} className="flex items-baseline gap-2">
                <span className="min-w-0 flex-1 break-words text-body">
                  {line.title}
                  <span className="text-meta text-muted-foreground">
                    {" · "}
                    {sectionLabel(line.section as SectionName)}
                  </span>
                </span>
                <span className="shrink-0 text-numeric">{hours(line.effort_hours)} h</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
