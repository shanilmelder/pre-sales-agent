import { getOpportunity, listRequirements } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { RequirementsSection } from "@/components/opportunities/requirements-list";
import { getMe } from "@/lib/api/server";

/** Tab 3: the Opportunity's Requirements, grouped by classification, with the state of its
 * latest extraction. Renders nothing when the user may not read the Opportunity; the
 * workspace layout shows why. */
export async function RequirementsTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const listed = await listRequirements(opportunity.id);

  return (
    <div className="flex flex-col gap-4 p-gutter">
      <h2 className="sr-only">Requirements</h2>
      {listed.kind === "ok" ? (
        <RequirementsSection
          key={opportunity.id}
          opportunityId={opportunity.id}
          initial={listed.list}
        />
      ) : (
        <p>The Requirements could not be loaded. Try again in a moment.</p>
      )}
    </div>
  );
}
