"use client";

import { useEffect, useId, useRef } from "react";

import { hours, ROLES, sectionLabel, type EstimateLine } from "@/lib/estimates";

/** The selected Estimate line in the right pane, read-only: its section and title, the basis
 * for its effort, its role mix broken down into hours (server-calculated), its effort,
 * Contingency and total, and the Requirements it covers as chips with their excerpts. */
export function EstimateInspector({
  line,
  focusRequest = 0,
}: {
  line: EstimateLine;
  focusRequest?: number;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <p className="text-meta text-muted-foreground">{sectionLabel(line.section)}</p>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {line.title}
        </h3>
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Basis</h4>
        <p className="whitespace-pre-wrap break-words text-body">{line.basis}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <h4 className="text-label text-muted-foreground">Role mix</h4>
        <table className="w-full text-body">
          <caption className="sr-only">Role mix in hours</caption>
          <thead>
            <tr className="text-label text-muted-foreground">
              <th scope="col" className="py-0.5 text-left font-medium">
                Role
              </th>
              <th scope="col" className="py-0.5 text-right font-medium">
                Share (%)
              </th>
              <th scope="col" className="py-0.5 text-right font-medium">
                Effort (h)
              </th>
            </tr>
          </thead>
          <tbody>
            {ROLES.map((role) => (
              <tr key={role.value} data-role={role.value}>
                <th scope="row" className="py-0.5 text-left font-normal">
                  {role.label}
                </th>
                <td className="py-0.5 text-right text-numeric">{line.role_mix[role.value]}</td>
                <td className="py-0.5 text-right text-numeric">
                  {hours(line.role_hours[role.value])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dl className="grid grid-cols-3 gap-2">
        {(
          [
            ["Effort (h)", line.effort_hours],
            ["Contingency (h)", line.contingency_hours],
            ["Total (h)", line.total_hours],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="flex flex-col gap-0.5">
            <dt className="text-label text-muted-foreground">{label}</dt>
            <dd className="text-numeric">{hours(value)}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-col gap-1.5">
        <h4 className="text-label text-muted-foreground">Covered Requirements</h4>
        <ul className="flex flex-col gap-1.5">
          {line.requirements.map((requirement) => (
            <li key={requirement.id} className="flex items-baseline gap-2">
              <span className="inline-flex h-5 shrink-0 items-center rounded-sm border border-border bg-background px-1.5 font-mono text-meta text-muted-foreground">
                {requirement.label}
              </span>
              <span className="min-w-0 break-words text-body">{requirement.excerpt}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
