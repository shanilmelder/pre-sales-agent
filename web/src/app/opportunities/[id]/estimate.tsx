import {
  getEstimate,
  getEstimateVersions,
  getOpportunity,
  getReviewRequests,
} from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { EstimateSection } from "@/components/opportunities/estimate-grid";
import { getMe } from "@/lib/api/server";
import { parseVersionParam } from "@/lib/estimates";
import { PAGE_PADDING } from "@/components/shell/page-header";

/** Tab 7: the Opportunity's current draft Estimate Version as a read-only grid, with every
 * total calculated by the server, and the state of its latest draft (Story 8.1 + 8.2, demo
 * scope), and its Review Requests (Story 9.1). Story 9.7: `?version=n` shows that version read
 * only, and the version switcher lists every version. Renders nothing when the user may not
 * read the Opportunity; the workspace layout shows why. */
export async function EstimateTab({
  id,
  searchParams = {},
}: {
  id: string;
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const version = parseVersionParam(searchParams.version);
  const [estimate, reviews, versions] = await Promise.all([
    getEstimate(opportunity.id, version),
    getReviewRequests(opportunity.id),
    getEstimateVersions(opportunity.id),
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
          initialVersions={versions.kind === "ok" ? versions.versions : null}
        />
      ) : (
        <p>The Estimate could not be loaded. Try again in a moment.</p>
      )}
    </div>
  );
}
