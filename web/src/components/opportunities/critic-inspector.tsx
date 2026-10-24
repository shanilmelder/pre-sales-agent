"use client";

import { useEffect, useId, useRef } from "react";

import { Chip } from "@/components/ui/chip";
import { FindingDecisions } from "@/components/opportunities/finding-decisions";
import { SeverityPill } from "@/components/opportunities/severity-pill";
import { citedFindingLabel, criticCategoryLabel, type CriticFinding } from "@/lib/critic";

/** The selected Critic Finding in the right pane (Story 6.4): its severity, category and
 * title, its status and actions (Story 6.6, with `opportunityId`), the Critic's argument,
 * the specialist Findings it cites (each with the agent's role, the Assessment version and
 * the Finding's title) and the Requirements it cites as chips with their excerpts. */
export function CriticInspector({
  finding,
  opportunityId,
  focusRequest = 0,
}: {
  finding: CriticFinding;
  /** Set to show the Finding's status and actions (Story 6.6). */
  opportunityId?: string;
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
          <p className="text-meta text-muted-foreground">
            {criticCategoryLabel(finding.category)}
          </p>
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

      {opportunityId ? (
        <FindingDecisions opportunityId={opportunityId} finding={finding} />
      ) : null}

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Argument</h4>
        <p className="whitespace-pre-wrap break-words text-body">{finding.argument}</p>
      </div>

      {finding.findings.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-label text-muted-foreground">Cited Findings</h4>
          <ul className="flex flex-col gap-1.5">
            {finding.findings.map((cited) => (
              <li key={cited.id} className="flex items-baseline gap-2">
                <Chip className="shrink-0">{citedFindingLabel(cited)}</Chip>
                <span className="min-w-0 break-words text-body">{cited.title}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {finding.requirements.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <h4 className="text-label text-muted-foreground">Requirements</h4>
          <ul className="flex flex-col gap-1.5">
            {finding.requirements.map((requirement) => (
              <li key={requirement.id} className="flex items-baseline gap-2">
                <Chip className="shrink-0">{requirement.label}</Chip>
                <span className="min-w-0 break-words text-body">{requirement.excerpt}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
