"use client";

import { useEffect, useId, useRef } from "react";

import { ConflictStatusPill } from "@/components/opportunities/conflict-status-pill";
import { SeverityPill } from "@/components/opportunities/severity-pill";
import {
  positionRole,
  positionSource,
  typeLabel,
  type Conflict,
  type ConflictPosition,
} from "@/lib/conflicts";

type ConflictRequirement = NonNullable<ConflictPosition["requirement"]>;

const chipClass =
  "inline-flex h-5 shrink-0 items-center rounded-sm border border-border bg-background px-1.5 font-mono text-meta text-muted-foreground";

function RequirementChip({
  requirement,
}: {
  requirement: ConflictRequirement;
}) {
  return (
    <p className="flex min-w-0 items-baseline gap-2">
      <span
        className={`${chipClass} ${requirement.label === "Superseded" ? "line-through" : ""}`}
      >
        {requirement.label}
      </span>
      <span className="min-w-0 break-words text-meta">
        {requirement.excerpt}
      </span>
    </p>
  );
}

const sameRequirement = (
  a: ConflictRequirement | null,
  b: ConflictRequirement | null,
) => a !== null && b !== null && a.id === b.id && a.version === b.version;

/** One position as a card: the agent by role (or the Estimate), the value in tabular
 * figures, its Requirement chip when it differs from the Conflict's, and the source
 * Assessment version. */
function PositionCard({
  position,
  shown,
}: {
  position: ConflictPosition;
  shown: ConflictRequirement | null;
}) {
  const requirement = position.requirement;
  return (
    <li className="flex min-w-0 flex-col gap-1.5 rounded-md border border-border p-2">
      <p className="text-label text-muted-foreground">
        {positionRole(position)}
      </p>
      <p className="text-body-strong [font-variant-numeric:tabular-nums]">
        {position.summary}
      </p>
      {requirement && !sameRequirement(requirement, shown) ? (
        <RequirementChip requirement={requirement} />
      ) : null}
      <p className="text-meta text-muted-foreground">
        {positionSource(position)}
      </p>
    </li>
  );
}

/** The selected Conflict in the right pane, read-only: its severity, type and status, the
 * summary, and the positions as equal-width cards side by side. */
export function ConflictInspector({
  conflict,
  focusRequest = 0,
}: {
  conflict: Conflict;
  focusRequest?: number;
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
          <SeverityPill severity={conflict.severity} />
          <ConflictStatusPill status={conflict.status} />
        </div>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {typeLabel(conflict.type)} Conflict
        </h3>
        <p className="text-body">{conflict.summary}</p>
        {conflict.resolution_reason ? (
          <p className="text-meta text-muted-foreground">
            {conflict.resolution_reason}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <h4 className="text-label text-muted-foreground">Positions</h4>
        {conflict.requirement ? (
          <RequirementChip requirement={conflict.requirement} />
        ) : null}
        {/* Equal-width cards, wrapping to a new row when the pane is too narrow for all. */}
        <ul className="grid grid-cols-[repeat(auto-fit,minmax(7.5rem,1fr))] gap-2">
          {conflict.positions.map((position) => (
            <PositionCard
              key={position.position}
              position={position}
              shown={conflict.requirement}
            />
          ))}
        </ul>
      </div>
    </section>
  );
}
