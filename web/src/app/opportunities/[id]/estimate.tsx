import { getEstimate, getOpportunity } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { EstimateSection } from "@/components/opportunities/estimate-grid";
import { getMe } from "@/lib/api/server";

/** Tab 7: the Opportunity's current draft Estimate Version as a read-only grid, with every
 * total calculated by the server, and the state of its latest draft (Story 8.1 + 8.2, demo
 * scope). Renders nothing when the user may not read the Opportunity; the workspace layout
 * shows why. */
export async function EstimateTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const estimate = await getEstimate(opportunity.id);

  return (
    <div className="flex flex-col gap-4 p-gutter">
      <h2 className="sr-only">Estimate</h2>
      {estimate.kind === "ok" ? (
        <EstimateSection
          key={opportunity.id}
          opportunityId={opportunity.id}
          initial={estimate.estimate}
        />
      ) : (
        <p>The Estimate could not be loaded. Try again in a moment.</p>
      )}
    </div>
  );
}
