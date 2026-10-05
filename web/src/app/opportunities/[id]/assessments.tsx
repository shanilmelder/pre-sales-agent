import { getAssessments, getOpportunity, getRedTeam } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { FindingSelectionProvider } from "@/components/opportunities/finding-selection";
import { RedTeamSection } from "@/components/opportunities/red-team-list";
import { SpecialistAssessmentsSection } from "@/components/opportunities/specialist-assessments";
import { getMe } from "@/lib/api/server";

/** Tab 5: the Opportunity's Assessments. In the demo scope a Specialist Assessments section
 * (Epic 5 slice 5A: the Engineering, PM and Security Agents' current Assessments and the
 * latest run) above the Red Team section (Story 6.5). Only one Finding across both sections
 * is selected at a time. Renders nothing when the user may not read the Opportunity; the
 * workspace layout shows why. */
export async function AssessmentsTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const [assessments, redTeam] = await Promise.all([
    getAssessments(opportunity.id),
    getRedTeam(opportunity.id),
  ]);

  return (
    <div className="flex flex-col gap-4 p-gutter">
      <h2 className="sr-only">Assessments</h2>
      <FindingSelectionProvider key={opportunity.id}>
        {assessments.kind === "ok" ? (
          <SpecialistAssessmentsSection
            opportunityId={opportunity.id}
            initial={assessments.assessments}
          />
        ) : (
          <p>The Specialist Assessments could not be loaded. Try again in a moment.</p>
        )}
        {redTeam.kind === "ok" ? (
          <RedTeamSection opportunityId={opportunity.id} initial={redTeam.redTeam} />
        ) : (
          <p>The Red Team Review could not be loaded. Try again in a moment.</p>
        )}
      </FindingSelectionProvider>
    </div>
  );
}
