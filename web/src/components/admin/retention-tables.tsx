import type { ReactNode } from "react";

import { BODY_ROW, CardTable, FOOTNOTE } from "@/components/admin/card-table";
import { Card } from "@/components/ui/card";
import { Pill } from "@/components/ui/pill";
import { formatDate } from "@/lib/opportunities";
import { OUTCOME_LABELS } from "@/lib/outcome";
import {
  DUE_HEADING,
  DUE_SUBLINE,
  filesLabel,
  NO_DUE,
  NO_RECENT,
  RECENT_HEADING,
  RECENT_SUBLINE,
  RETENTION_FOOTNOTE,
  rowsByModule,
  rowsLabel,
  RULE_LABELS,
  totalRows,
  type PurgeEvent,
  type RetentionDue,
} from "@/lib/retention";
import { formatDateTime } from "@/lib/sources";

const DUE_GRID = "grid-cols-[minmax(0,2fr)_110px_minmax(0,1fr)_140px]";
const RECENT_GRID = "grid-cols-[170px_minmax(0,1.6fr)_120px_minmax(0,1.4fr)_80px]";

/** A titled Admin card: the heading and subline, then the table or its empty sentence. */
function Section({
  id,
  title,
  sub,
  children,
}: {
  id: string;
  title: string;
  sub: string;
  children: ReactNode;
}) {
  return (
    <Card className="overflow-hidden">
      <section aria-labelledby={id}>
        <div className="px-5 py-[18px]">
          <h2 id={id} className="text-section">
            {title}
          </h2>
          <p className="text-meta text-text-secondary">{sub}</p>
        </div>
        {children}
      </section>
    </Card>
  );
}

function Empty({ children }: { children: string }) {
  return <p className="border-t border-border px-5 py-4 text-text-secondary">{children}</p>;
}

/** The outcome as a tint pill with its word (never colour alone). */
function OutcomePill({ outcome }: { outcome: RetentionDue["outcome"] }) {
  return (
    <Pill data-outcome={outcome} tone={outcome === "won" ? "resolved" : "neutral"}>
      {OUTCOME_LABELS[outcome]}
    </Pill>
  );
}

function DueTable({ due }: { due: readonly RetentionDue[] }) {
  return (
    <CardTable
      label={DUE_HEADING}
      grid={DUE_GRID}
      columns={["Opportunity", "Outcome", "Rule", "Retention date"]}
      scrollable
    >
      {due.map((item) => (
        <div
          key={item.opportunity_id}
          role="row"
          data-opportunity-id={item.opportunity_id}
          className={`py-3 ${BODY_ROW} ${DUE_GRID}`}
        >
          <div role="rowheader" className="min-w-0 truncate font-mono text-meta">
            {item.opportunity_id}
          </div>
          <div role="cell">
            <OutcomePill outcome={item.outcome} />
          </div>
          <div role="cell" className="text-meta">
            {RULE_LABELS[item.rule]}
          </div>
          <div role="cell" className="text-meta text-numeric">
            <time dateTime={item.retention_until}>{formatDate(item.retention_until)}</time>
          </div>
        </div>
      ))}
    </CardTable>
  );
}

function RecentTable({ recent }: { recent: readonly PurgeEvent[] }) {
  return (
    <CardTable
      label={RECENT_HEADING}
      grid={RECENT_GRID}
      columns={["When", "Opportunity", "Rule", "Rows", "Files"]}
      scrollable
    >
      {recent.map((event) => (
        <div
          key={`${event.purged_opportunity_id}-${event.occurred_at}`}
          role="row"
          data-purged-id={event.purged_opportunity_id}
          className={`py-3 ${BODY_ROW} ${RECENT_GRID}`}
        >
          <div role="cell" className="text-meta text-numeric">
            <time dateTime={event.occurred_at}>{formatDateTime(event.occurred_at)}</time>
          </div>
          <div role="rowheader" className="min-w-0 truncate font-mono text-meta">
            {event.purged_opportunity_id}
          </div>
          <div role="cell" className="text-meta">
            {RULE_LABELS[event.rule]}
          </div>
          <div role="cell" className="min-w-0 text-meta">
            <span className="text-numeric">{rowsLabel(totalRows(event))}</span>
            <span className="block truncate text-text-secondary" title={rowsByModule(event)}>
              {rowsByModule(event)}
            </span>
          </div>
          <div role="cell" className="text-meta text-numeric">
            {filesLabel(event.files_deleted)}
          </div>
        </div>
      ))}
    </CardTable>
  );
}

/** Admin → Retention (Story 10.6), read only: the Opportunities due for purge in the next 30
 * days (UUID, outcome, rule, retention date) and the recent purges (when, UUID, rule, rows,
 * files), then the footnote. Ids, outcomes, dates and counts only: no names or content. There
 * is deliberately no control that deletes. */
export function RetentionTables({
  due,
  recent,
}: {
  due: readonly RetentionDue[];
  recent: readonly PurgeEvent[];
}) {
  return (
    <div className="flex flex-col gap-6">
      <Section id="retention-due" title={DUE_HEADING} sub={DUE_SUBLINE}>
        {due.length === 0 ? <Empty>{NO_DUE}</Empty> : <DueTable due={due} />}
      </Section>
      <Section id="retention-recent" title={RECENT_HEADING} sub={RECENT_SUBLINE}>
        {recent.length === 0 ? <Empty>{NO_RECENT}</Empty> : <RecentTable recent={recent} />}
      </Section>
      <p className={FOOTNOTE}>{RETENTION_FOOTNOTE}</p>
    </div>
  );
}
