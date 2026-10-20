import { getConflicts, getOpportunity } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { ConflictsSection } from "@/components/opportunities/conflicts-list";
import { ConflictsLiveRefresh } from "@/components/opportunities/conflicts-live-refresh";
import { getMe } from "@/lib/api/server";
import { CONFLICTS_NOT_LOADED } from "@/lib/conflicts";

/** Tab 6: the Conflicts between the specialist Assessments (and the Estimate), found by the
 * rules at the end of each assessment run (Story 6.1, demo slice) and by the Conflict Agent
 * from the Findings' text afterwards (Story 6.2, "Detected from text"; the tab follows the
 * event stream's `conflicts.changed` frames): Open and Resolved
 * sections, each Conflict's positions in the right pane, where the owner and collaborators
 * (not sales representatives) or an assigned reviewer resolve or escalate it (Story 6.3). Renders
 * nothing when the user may not read the Opportunity; the workspace layout shows why. */
export async function ConflictsTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const conflicts = await getConflicts(opportunity.id);

  return (
    <div className="flex flex-col gap-4 p-gutter">
      <h2 className="sr-only">Conflicts</h2>
      <ConflictsLiveRefresh opportunityId={opportunity.id} />
      {conflicts.kind === "ok" ? (
        <ConflictsSection
          key={opportunity.id}
          initial={conflicts.conflicts}
          opportunityId={opportunity.id}
        />
      ) : (
        <p>{CONFLICTS_NOT_LOADED}</p>
      )}
    </div>
  );
}
