import {
  getOpportunity,
  listOutdatedAssessments,
  listRequirements,
} from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { RequirementsSection } from "@/components/opportunities/requirements-list";
import { getMe } from "@/lib/api/server";

/** Tab 3: the Opportunity's Requirements, grouped by classification, with the state of its
 * latest extraction, and a notice of the Assessments that used Requirement versions that
 * have changed since (Story 2.7). `?requirement=<id>` opens that Requirement's inspector (Story
 * 4.7: the links under a Gap's answer). Renders nothing when the user may not read the
 * Opportunity; the workspace layout shows why. */
export async function RequirementsTab({
  id,
  searchParams = {},
}: {
  id: string;
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  const requested = searchParams.requirement;
  const requirementId = typeof requested === "string" ? requested : null;
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const [listed, outdated] = await Promise.all([
    listRequirements(opportunity.id),
    listOutdatedAssessments(opportunity.id),
  ]);

  return (
    <div className="flex flex-col gap-4 p-gutter">
      <h2 className="sr-only">Requirements</h2>
      {listed.kind === "ok" ? (
        <RequirementsSection
          key={opportunity.id}
          opportunityId={opportunity.id}
          initial={listed.list}
          initialOutdated={outdated.kind === "ok" ? outdated.items : []}
          initialSelectedId={requirementId}
        />
      ) : (
        <p>The Requirements could not be loaded. Try again in a moment.</p>
      )}
    </div>
  );
}
