import { redirect } from "next/navigation";

import { getOpportunity, listTrace, parsePage } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { TraceSection } from "@/components/opportunities/trace-list";
import { getMe } from "@/lib/api/server";
import {
  pageCount,
  parseTraceFilters,
  TRACE_LOAD_FAILED,
  traceHref,
} from "@/lib/trace";

type SearchParams = Record<string, string | string[] | undefined>;

/** Tab 8: the Opportunity's Decision Trace, read-only (Story 9.8, demo slice): its trace
 * events newest first, filtered by the URL's `subject`, `actor` and `event`, one page
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
  const listed = await listTrace(opportunity.id, page, filters);
  if (
    listed.kind === "ok" &&
    listed.page.items.length === 0 &&
    listed.page.total > 0
  ) {
    // Past the last page (a hand-edited or stale URL): go to the last one.
    redirect(traceHref(opportunity.id, filters, pageCount(listed.page)));
  }

  return (
    <div className="flex flex-col gap-4 p-gutter">
      <h2 className="sr-only">Trace</h2>
      {listed.kind === "ok" ? (
        <TraceSection
          key={traceHref(opportunity.id, filters, page)}
          opportunityId={opportunity.id}
          page={listed.page}
          filters={filters}
        />
      ) : (
        <p>{TRACE_LOAD_FAILED}</p>
      )}
    </div>
  );
}
