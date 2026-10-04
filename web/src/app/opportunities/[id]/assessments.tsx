import { getOpportunity, getRedTeam } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { RedTeamSection } from "@/components/opportunities/red-team-list";
import { getMe } from "@/lib/api/server";

/** Tab 5: the Opportunity's Assessments. In the demo scope (Story 6.5) one Red Team section:
 * the current Red Team Review's severity-ranked Findings, read-only, and the state of its
 * latest run. Renders nothing when the user may not read the Opportunity; the workspace
 * layout shows why. */
export async function AssessmentsTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const redTeam = await getRedTeam(opportunity.id);

  return (
    <div className="flex flex-col gap-4 p-gutter">
      <h2 className="sr-only">Assessments</h2>
      {redTeam.kind === "ok" ? (
        <RedTeamSection
          key={opportunity.id}
          opportunityId={opportunity.id}
          initial={redTeam.redTeam}
        />
      ) : (
        <p>The Red Team Review could not be loaded. Try again in a moment.</p>
      )}
    </div>
  );
}
