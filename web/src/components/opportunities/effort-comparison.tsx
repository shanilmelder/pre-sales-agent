import type { ReactNode } from "react";

import { AGENTS, type AgentAssessment } from "@/lib/assessments";
import {
  ADDS_UP_NOTE,
  AGENTS_TOTAL,
  agentColumn,
  compareEffort,
  COMPARISON_NOT_LOADED,
  comparisonHours,
  DIFFERENCE,
  EFFORT_COMPARISON,
  ESTIMATE_ALLOCATED,
  estimateColumnNote,
  estimateTotalNote,
  ESTIMATE_NOT_LOADED,
  leftOutNote,
  NO_EFFORT_TO_COMPARE,
  NOT_LINKED,
  signedHours,
  type ComparisonValues,
} from "@/lib/effort-comparison";
import type { EstimateVersion } from "@/lib/estimates";
import type { Requirement } from "@/lib/requirements";

const NUMERIC = "py-1 pl-3 text-right text-numeric whitespace-nowrap";

/** One row's (or the totals row's) number cells. */
function ValueCells({
  values,
  withEstimate,
}: {
  values: ComparisonValues;
  withEstimate: boolean;
}) {
  return (
    <>
      {AGENTS.map((agent) => (
        <td key={agent.value} className={NUMERIC}>
          {comparisonHours(values.agents[agent.value])}
        </td>
      ))}
      <td className={`${NUMERIC} font-semibold`}>
        {comparisonHours(values.agentsTotal)}
      </td>
      {withEstimate ? (
        <>
          <td className={NUMERIC}>{comparisonHours(values.estimate)}</td>
          <td className={NUMERIC}>{signedHours(values.difference)}</td>
        </>
      ) : null}
    </>
  );
}

/** The Assessments tab's Effort comparison (Story 5.3, demo slice): per active Requirement,
 * the Engineering, PM and Security Agents' hours, their sum, the Estimate's hours allocated
 * to it (each line split equally among the Requirements it covers) and the difference, with
 * totals. Read-only and the same for every role that can read the Opportunity. `null`
 * Requirements or Assessments mean that read failed; `estimate` is `"error"` when the
 * Estimate read failed (the table renders without its columns). */
export function EffortComparisonSection({
  requirements,
  assessments,
  estimate,
}: {
  requirements: readonly Requirement[] | null;
  assessments: readonly AgentAssessment[] | null;
  estimate: EstimateVersion | null | "error";
}) {
  const headingId = "effort-comparison-heading";
  const captionId = "effort-comparison-caption";

  let body: ReactNode;
  if (requirements === null || assessments === null) {
    body = <p>{COMPARISON_NOT_LOADED}</p>;
  } else {
    const estimateFailed = estimate === "error";
    const comparison = compareEffort({
      requirements,
      assessments,
      estimate: estimateFailed ? null : estimate,
    });
    const withEstimate = !estimateFailed;
    // "Nothing to compare" only when the Estimate was read: a failed read may hide one.
    const empty = comparison.empty && !estimateFailed;
    body = (
      <>
        {estimateFailed ? <p>{ESTIMATE_NOT_LOADED}</p> : null}
        {empty ? (
          <p className="text-muted-foreground">{NO_EFFORT_TO_COMPARE}</p>
        ) : (
          <>
            <p className="text-meta text-muted-foreground">
              {ADDS_UP_NOTE}
              {withEstimate ? ` ${estimateColumnNote(comparison.estimateVersion)}` : null}
            </p>
            <div
              role="region"
              aria-labelledby={captionId}
              tabIndex={0}
              className="overflow-x-auto rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <table className="w-full border-collapse text-left">
                <caption id={captionId} className="sr-only">
                  {EFFORT_COMPARISON} by Requirement, in hours
                </caption>
                <thead>
                  <tr className="border-b border-border text-label text-muted-foreground">
                    <th scope="col" className="py-1 pr-3 font-normal">
                      Requirement
                    </th>
                    {AGENTS.map((agent) => (
                      <th
                        key={agent.value}
                        scope="col"
                        className="py-1 pl-3 text-right font-normal"
                      >
                        {agentColumn(agent.value)}
                      </th>
                    ))}
                    <th scope="col" className="py-1 pl-3 text-right font-normal">
                      {AGENTS_TOTAL}
                    </th>
                    {withEstimate ? (
                      <>
                        <th scope="col" className="py-1 pl-3 text-right font-normal">
                          {ESTIMATE_ALLOCATED}
                        </th>
                        <th scope="col" className="py-1 pl-3 text-right font-normal">
                          {DIFFERENCE}
                        </th>
                      </>
                    ) : null}
                  </tr>
                </thead>
                <tbody>
                  {comparison.rows.map((row) => (
                    <tr key={row.id} className="border-b border-border align-baseline">
                      <th scope="row" className="py-1 pr-3 text-left font-normal">
                        <span className="font-mono text-meta text-muted-foreground">
                          {row.label}
                        </span>{" "}
                        <span className="text-body">{row.excerpt}</span>
                      </th>
                      <ValueCells values={row} withEstimate={withEstimate} />
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="text-body-strong align-baseline">
                    <th scope="row" className="py-1 pr-3 text-left font-semibold">
                      Total
                      {comparison.unlinkedHours ? (
                        <span className="block text-meta font-normal text-muted-foreground">
                          {NOT_LINKED}: {comparisonHours(comparison.unlinkedHours)} h
                        </span>
                      ) : null}
                    </th>
                    <ValueCells values={comparison.totals} withEstimate={withEstimate} />
                  </tr>
                </tfoot>
              </table>
            </div>
            {comparison.estimateEffortTotal !== null && comparison.unlinkedHours !== null ? (
              <p className="text-meta text-muted-foreground">
                {estimateTotalNote(comparison.estimateEffortTotal, comparison.unlinkedHours)}
              </p>
            ) : null}
          </>
        )}
        {/* Not with the empty sentence, which it would contradict. */}
        {!empty && comparison.leftOut > 0 ? (
          <p className="text-meta text-muted-foreground">{leftOutNote(comparison.leftOut)}</p>
        ) : null}
      </>
    );
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h3 id={headingId} className="text-body-strong">
        {EFFORT_COMPARISON}
      </h3>
      {body}
    </section>
  );
}
