import { getActuals, getOpportunity, listActiveCatalogue } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { ActualsSection } from "@/components/opportunities/actuals-table";
import { PAGE_PADDING } from "@/components/shell/page-header";
import { getMe } from "@/lib/api/server";
import { LOAD_FAILED, parseActualsDrill } from "@/lib/actuals";

type SearchParams = Record<string, string | string[] | undefined>;

/** Tab 8: Actuals per Baseline Estimate line (Story 10.1), with server-calculated variance.
 * Delivery managers record and correct them; everyone else who can read the Opportunity sees
 * them read only (the API decides, through `can_record`). Renders nothing when the user may
 * not read the Opportunity; the workspace layout shows why. Story 10.4: the URL's `sort`
 * (`variance_desc|variance_asc`) and `integration_type` (an id, or `none`) from a Reports
 * link seed the table's sort and Integration Type filter. */
export async function ActualsTab({
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
  const actuals = await getActuals(opportunity.id);
  const catalogue =
    actuals.kind === "ok" && actuals.actuals.can_record
      ? await listActiveCatalogue()
      : { integrationTypes: [], workPackages: [] };

  return (
    <div className={`flex flex-col gap-4 ${PAGE_PADDING}`}>
      {actuals.kind === "ok" ? (
        <ActualsSection
          key={opportunity.id}
          opportunityId={opportunity.id}
          initial={actuals.actuals}
          catalogue={catalogue}
          drill={parseActualsDrill(searchParams)}
        />
      ) : (
        <>
          <h2 className="sr-only">Actuals</h2>
          <p>{LOAD_FAILED}</p>
        </>
      )}
    </div>
  );
}
