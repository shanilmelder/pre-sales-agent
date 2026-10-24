import { getEstimate, getOpportunity, getReviewRequests } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { EstimateSection } from "@/components/opportunities/estimate-grid";
import { getMe } from "@/lib/api/server";
import { PAGE_PADDING } from "@/components/shell/page-header";

/** Tab 7: the Opportunity's current draft Estimate Version as a read-only grid, with every
 * total calculated by the server, and the state of its latest draft (Story 8.1 + 8.2, demo
 * scope), and its Review Requests (Story 9.1). Renders nothing when the user may not read
 * the Opportunity; the workspace layout shows why. */
export async function EstimateTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const [estimate, reviews] = await Promise.all([
    getEstimate(opportunity.id),
    getReviewRequests(opportunity.id),
  ]);

  return (
    <div className={`flex flex-col gap-4 ${PAGE_PADDING}`}>
      <h2 className="sr-only">Estimate</h2>
      {estimate.kind === "ok" ? (
        <EstimateSection
          key={opportunity.id}
          opportunityId={opportunity.id}
          initial={estimate.estimate}
          initialReviews={reviews.kind === "ok" ? reviews.reviews : null}
        />
      ) : (
        <p>The Estimate could not be loaded. Try again in a moment.</p>
      )}
    </div>
  );
}
