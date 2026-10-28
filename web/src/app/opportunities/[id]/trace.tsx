import { redirect } from "next/navigation";

import {
  getAssumptionLineage,
  getLineLineage,
  getOpportunity,
  listTrace,
  parsePage,
} from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { TraceSection } from "@/components/opportunities/trace-list";
import { getMe } from "@/lib/api/server";
import {
  ASSUMPTION_SUBJECT,
  assumptionChipTitle,
  pageCount,
  parseTraceFilters,
  TRACE_LOAD_FAILED,
  traceHref,
} from "@/lib/trace";
import { PAGE_PADDING } from "@/components/shell/page-header";

type SearchParams = Record<string, string | string[] | undefined>;

/** Tab 8: the Opportunity's Decision Trace, read-only (Story 9.8, demo slice): its trace
 * events newest first, filtered by the URL's `subject`, `actor` and `event` (and, Story 9.9,
 * `subject_id`: one Estimate line's events, its chip named by the line's title; Story 10.4: or
 * one Assumption's events plus the Actuals that recorded it as failed, its chip "Assumption
 * A{n} · {wording}" and its Chain card from the Assumption's lineage), one page
 * (`page`) at a time. Renders nothing when the user may not read the Opportunity; the
 * workspace layout shows why. */
export async function TraceTab({
  id,
  searchParams = {},
}: {
  id: string;
  searchParams?: SearchParams;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const filters = parseTraceFilters(searchParams);
  const page = parsePage(searchParams.page);
  const [listed, line, assumption] = await Promise.all([
    listTrace(opportunity.id, page, filters),
    filters.subject_id && filters.subject === "estimates.estimate_line"
      ? getLineLineage(opportunity.id, filters.subject_id)
      : null,
    filters.subject_id && filters.subject === ASSUMPTION_SUBJECT
      ? getAssumptionLineage(opportunity.id, filters.subject_id)
      : null,
  ]);
  const chain = assumption?.kind === "ok" ? assumption.lineage : null;
  const subjectTitle =
    line?.kind === "ok" ? line.lineage.title : chain ? assumptionChipTitle(chain) : null;
  if (
    listed.kind === "ok" &&
    listed.page.items.length === 0 &&
    listed.page.total > 0
  ) {
    // Past the last page (a hand-edited or stale URL): go to the last one.
    redirect(traceHref(opportunity.id, filters, pageCount(listed.page)));
  }

  return (
    <div className={`flex flex-col gap-4 ${PAGE_PADDING}`}>
      {listed.kind === "ok" ? (
        <TraceSection
          key={traceHref(opportunity.id, filters, page)}
          opportunityId={opportunity.id}
          page={listed.page}
          filters={filters}
          subjectTitle={subjectTitle}
          chain={chain}
        />
      ) : (
        <>
          <h2 className="text-section">Trace</h2>
          <p>{TRACE_LOAD_FAILED}</p>
        </>
      )}
    </div>
  );
}
