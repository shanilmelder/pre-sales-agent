import { getOpportunity, listSources } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { SourcesSection } from "@/components/opportunities/sources-list";
import { getMe } from "@/lib/api/server";

/** Tab 2: the Opportunity's Sources, with the upload area for its owner and collaborators.
 * Renders nothing when the user may not read the Opportunity; the workspace layout shows
 * why. */
export async function SourcesTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const listed = await listSources(opportunity.id);

  return (
    <div className="flex flex-col gap-4 p-gutter">
      <h2 className="sr-only">Sources</h2>
      {listed.kind === "ok" ? (
        <SourcesSection
          key={opportunity.id}
          opportunityId={opportunity.id}
          canAdd={opportunity.can_add_sources}
          initial={listed.sources}
        />
      ) : (
        <p>The Sources could not be loaded. Try again in a moment.</p>
      )}
    </div>
  );
}
