import { getConflicts, getOpportunity } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { ConflictsSection } from "@/components/opportunities/conflicts-list";
import { ConflictsLiveRefresh } from "@/components/opportunities/conflicts-live-refresh";
import { getMe } from "@/lib/api/server";
import { CONFLICTS_NOT_LOADED } from "@/lib/conflicts";
import { PAGE_PADDING } from "@/components/shell/page-header";

/** Tab 6: the Conflicts between the specialist Assessments (and the Estimate), found by the
 * rules at the end of each assessment run (Story 6.1, demo slice) and by the Conflict Agent
 * from the Findings' text afterwards (Story 6.2, "Detected from text"; the tab follows the
 * event stream's `conflicts.changed` frames): the open Conflicts, the selected one's decision
 * card inline, where the owner and collaborators (not sales representatives) or an assigned
 * reviewer resolve or escalate it (Story 6.3), and the resolved Conflicts. The section renders
 * the "Conflicts" heading; a failed read renders its own. Renders nothing when the user may not
 * read the Opportunity; the workspace layout shows why. */
export async function ConflictsTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const conflicts = await getConflicts(opportunity.id);

  return (
    <div className={`flex flex-col gap-4 ${PAGE_PADDING}`}>
      <ConflictsLiveRefresh opportunityId={opportunity.id} />
      {conflicts.kind === "ok" ? (
        <ConflictsSection
          key={opportunity.id}
          initial={conflicts.conflicts}
          opportunityId={opportunity.id}
        />
      ) : (
        <>
          <h2 className="text-section">Conflicts</h2>
          <p>{CONFLICTS_NOT_LOADED}</p>
        </>
      )}
    </div>
  );
}
