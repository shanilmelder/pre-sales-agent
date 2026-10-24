import { OctagonAlertIcon, ShieldXIcon } from "lucide-react";
import Link from "next/link";

import { BODY_ROW, CardTable, FOOTNOTE } from "@/components/admin/card-table";
import { Card } from "@/components/ui/card";
import { Pill } from "@/components/ui/pill";
import {
  agentAtVersion,
  denialReasonLabel,
  DENIALS_FOOTNOTE,
  shortId,
  THRESHOLD_EXCEEDED,
  type ToolDenial,
} from "@/lib/admin";
import { formatDateTime } from "@/lib/sources";

const GRID =
  "grid-cols-[150px_minmax(0,1fr)_minmax(0,1.1fr)_minmax(0,1fr)_100px_minmax(0,1fr)]";

const linkClass =
  "rounded-sm font-mono text-meta text-primary-text underline outline-none focus-visible:ring-2 focus-visible:ring-primary";

/** The denial's reason: always an icon and a label, never colour alone. */
function ReasonPill({ denial }: { denial: ToolDenial }) {
  return (
    <Pill data-reason={denial.reason} tone="neutral" icon={<ShieldXIcon />} className="shrink-0">
      {denialReasonLabel(denial.reason)}
    </Pill>
  );
}

/** Admin → Agents → Denied tool calls (Story 7.4): one row per denied ToolGateway call, newest
 * first, as a card table (time, Agent and version, tool action, reason, Opportunity and run
 * links), then the footnote. A run that passed the denial alert threshold carries a
 * "Threshold exceeded" pill. Ids and timings only: no Opportunity names, prompts or Source
 * text. `empty` is the sentence shown when there are no rows. */
export function ToolDenialsTable({
  denials,
  empty,
}: {
  denials: readonly ToolDenial[];
  empty: string;
}) {
  return (
    <>
      <Card className="overflow-hidden">
        {denials.length === 0 ? (
          <p className="px-5 py-4 text-text-secondary">{empty}</p>
        ) : (
          <CardTable
            label="Denied tool calls"
            grid={GRID}
            columns={["Time", "Agent", "Tool action", "Reason", "Opportunity", "Run"]}
          >
            {denials.map((denial) => (
              <div
                key={denial.id}
                role="row"
                data-denial-id={denial.id}
                className={`py-3 ${BODY_ROW} ${GRID}`}
              >
                <div role="cell" className="text-meta text-numeric">
                  <time dateTime={denial.created_at}>{formatDateTime(denial.created_at)}</time>
                </div>
                <div role="rowheader" className="min-w-0 truncate font-mono text-meta">
                  {agentAtVersion(denial)}
                </div>
                <div role="cell" className="min-w-0 truncate font-mono text-meta">
                  {denial.tool}
                </div>
                <div role="cell" className="flex min-w-0 flex-wrap gap-1">
                  <ReasonPill denial={denial} />
                  {denial.threshold_exceeded ? (
                    <Pill
                      data-threshold-exceeded=""
                      tone="blocker"
                      icon={<OctagonAlertIcon />}
                      className="shrink-0"
                    >
                      {THRESHOLD_EXCEEDED}
                    </Pill>
                  ) : null}
                </div>
                <div role="cell">
                  <Link
                    href={`/opportunities/${denial.opportunity_id}/overview`}
                    aria-label={`Opportunity ${shortId(denial.opportunity_id)}`}
                    className={linkClass}
                  >
                    {shortId(denial.opportunity_id)}
                  </Link>
                </div>
                <div role="cell">
                  {denial.run_id ? (
                    <Link
                      href={`/opportunities/${denial.opportunity_id}/assessments`}
                      aria-label={`Run ${shortId(denial.run_id)}`}
                      className={linkClass}
                    >
                      {shortId(denial.run_id)}
                    </Link>
                  ) : (
                    <span className="text-text-secondary">
                      <span aria-hidden="true">—</span>
                      <span className="sr-only">No run</span>
                    </span>
                  )}
                </div>
              </div>
            ))}
          </CardTable>
        )}
      </Card>
      <p className={FOOTNOTE}>{DENIALS_FOOTNOTE}</p>
    </>
  );
}
