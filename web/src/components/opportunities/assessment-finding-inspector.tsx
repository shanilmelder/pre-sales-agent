"use client";

import { useEffect, useId, useRef } from "react";

import { ChallengeButton } from "@/components/opportunities/challenge-dialog";
import { Chip } from "@/components/ui/chip";
import { SeverityPill } from "@/components/opportunities/severity-pill";
import {
  agentLabel,
  kindLabel,
  type AssessmentAgent,
  type AssessmentFinding,
} from "@/lib/assessments";

/** The selected specialist Finding in the right pane, read-only: its severity, kind and
 * agent, its title and detail, and the Requirements it cites as chips with their excerpts.
 * Story 9.5: **Challenge** opens the Challenge dialog on this Finding when the API's
 * `can_challenge` allows it (`opportunityId` set). Critic and Red Team Findings have their own
 * inspectors and no Challenge. */
export function AssessmentFindingInspector({
  finding,
  agent,
  focusRequest = 0,
  opportunityId,
  canChallenge = false,
}: {
  finding: AssessmentFinding;
  agent: AssessmentAgent;
  focusRequest?: number;
  opportunityId?: string;
  canChallenge?: boolean;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-4 p-gutter"
    >
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityPill severity={finding.severity} />
          <p className="text-meta text-muted-foreground">
            {kindLabel(finding.kind)} · {agentLabel(agent)}
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
        {canChallenge && opportunityId ? (
          <div>
            <ChallengeButton
              opportunityId={opportunityId}
              target={{ kind: "finding", id: finding.id }}
              size="sm"
            />
          </div>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Detail</h4>
        <p className="whitespace-pre-wrap break-words text-body">
          {finding.detail}
        </p>
      </div>

      <div className="flex flex-col gap-1.5">
        <h4 className="text-label text-muted-foreground">Cited Requirements</h4>
        <ul className="flex flex-col gap-1.5">
          {finding.requirements.map((requirement) => (
            <li key={requirement.id} className="flex items-baseline gap-2">
              <Chip className="shrink-0">{requirement.label}</Chip>
              <span className="min-w-0 break-words text-body">
                {requirement.excerpt}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
