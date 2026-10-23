import { getGapsContext, getOpportunity, listGaps } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { GapsSection } from "@/components/opportunities/gaps-list";
import { getMe } from "@/lib/api/server";
import { PAGE_PADDING } from "@/components/shell/page-header";

/** Tab 4: the Opportunity's open Gaps, ranked by impact, each with its drafted Clarification
 * Question, and the state of its latest Gap detection (Story 4.3 + 4.4, demo scope), under the
 * applicable Checklists and the untagged and coverage banners (Story 4.1; left out when that
 * read fails). Renders
 * nothing when the user may not read the Opportunity; the workspace layout shows why. */
export async function GapsTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const [listed, context] = await Promise.all([
    listGaps(opportunity.id),
    getGapsContext(opportunity.id),
  ]);

  return (
    <div className={`flex flex-col gap-4 ${PAGE_PADDING}`}>
      {/* The section renders its own "Gaps" heading. */}
      {listed.kind === "ok" ? (
        <GapsSection
          key={opportunity.id}
          opportunityId={opportunity.id}
          initial={listed.list}
          context={context.kind === "ok" ? context.context : null}
        />
      ) : (
        <>
          <h2 className="sr-only">Gaps</h2>
          <p>The Gaps could not be loaded. Try again in a moment.</p>
        </>
      )}
    </div>
  );
}
