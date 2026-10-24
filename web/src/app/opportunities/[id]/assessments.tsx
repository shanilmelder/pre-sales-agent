import {
  getAssessments,
  getEstimate,
  getOpportunity,
  getRedTeam,
  listRequirements,
} from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { EffortComparisonSection } from "@/components/opportunities/effort-comparison";
import { FindingSelectionProvider } from "@/components/opportunities/finding-selection";
import { SpecialistAssessmentsSection } from "@/components/opportunities/specialist-assessments";
import { getMe } from "@/lib/api/server";
import type { AssessmentsView } from "@/lib/assessments";
import { PAGE_PADDING } from "@/components/shell/page-header";

/** The view shown when the Assessments read fails, so the Red Team still renders. */
const EMPTY_ASSESSMENTS: AssessmentsView = {
  run: null,
  assessments: [],
  can_start: false,
  can_resolve: false,
};

/** Tab 5: the Opportunity's Assessments: the run header, Agent tasks, Results so far and
 * one Findings table across the Engineering, PM and Security Agents and the Red Team
 * (Story 6.5, folded in as a fourth agent), then the Effort comparison (Story 5.3: the
 * agents' hours per Requirement next to the Estimate's). Only one Finding is selected at a
 * time. A failed Assessments or Red Team read says so; the other still renders. Renders nothing when the user may not read the Opportunity; the
 * workspace layout shows why. */
export async function AssessmentsTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const [assessments, redTeam, estimate, requirements] = await Promise.all([
    getAssessments(opportunity.id),
    getRedTeam(opportunity.id),
    getEstimate(opportunity.id),
    listRequirements(opportunity.id),
  ]);

  return (
    <div className={`flex flex-col gap-6 ${PAGE_PADDING}`}>
      <h2 className="sr-only">Assessments</h2>
      <FindingSelectionProvider key={opportunity.id}>
        <SpecialistAssessmentsSection
          opportunityId={opportunity.id}
          initial={assessments.kind === "ok" ? assessments.assessments : EMPTY_ASSESSMENTS}
          assessmentsFailed={assessments.kind !== "ok"}
          redTeam={redTeam.kind === "ok" ? redTeam.redTeam : null}
        />
        <EffortComparisonSection
          requirements={requirements.kind === "ok" ? requirements.list.items : null}
          assessments={assessments.kind === "ok" ? assessments.assessments.assessments : null}
          estimate={estimate.kind === "ok" ? estimate.estimate.version : "error"}
        />
      </FindingSelectionProvider>
    </div>
  );
}
