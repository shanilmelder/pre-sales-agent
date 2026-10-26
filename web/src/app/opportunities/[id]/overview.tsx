import {
  getAssessments,
  getConflicts,
  getEstimate,
  getOpportunity,
  getRedTeam,
  getSubmissionBlockers,
  listGaps,
  listRequirements,
  listSources,
  listTrace,
} from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { Collaborators } from "@/components/opportunities/collaborators";
import { OverviewLiveRefresh } from "@/components/opportunities/overview-live-refresh";
import { OverviewSummary, type OverviewData } from "@/components/opportunities/overview-summary";
import { StatusPill } from "@/components/opportunities/status-pill";
import { getMe } from "@/lib/api/server";
import { formatDate, utcToday } from "@/lib/opportunities";
import { PAGE_PADDING } from "@/components/shell/page-header";
import { Card } from "@/components/ui/card";

function Detail({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] items-baseline gap-2">
      <dt className="text-label text-muted-foreground">{term}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

/** Every read the summary needs, in parallel (the same reads the other tabs make). A failed
 * read is `null`, so only its own card says it could not be loaded. */
async function loadSummary(id: string): Promise<OverviewData> {
  const [
    sources,
    requirements,
    gaps,
    estimate,
    assessments,
    redTeam,
    trace,
    conflicts,
    blockers,
  ] = await Promise.all([
    listSources(id),
    listRequirements(id),
    listGaps(id),
    getEstimate(id),
    getAssessments(id),
    getRedTeam(id),
    listTrace(id, 1),
    getConflicts(id),
    getSubmissionBlockers(id),
  ]);
  return {
    sources: sources.kind === "ok" ? sources.sources : null,
    requirements: requirements.kind === "ok" ? requirements.list : null,
    gaps: gaps.kind === "ok" ? gaps.list : null,
    estimate: estimate.kind === "ok" ? estimate.estimate : null,
    assessments: assessments.kind === "ok" ? assessments.assessments : null,
    redTeam: redTeam.kind === "ok" ? redTeam.redTeam : null,
    trace: trace.kind === "ok" ? trace.page.items : null,
    conflicts: conflicts.kind === "ok" ? conflicts.conflicts : null,
    blockers:
      blockers.kind === "ok" && Array.isArray(blockers.blockers.to_submit)
        ? blockers.blockers
        : null,
  };
}

/** Tab 1: a read-only summary of where the Opportunity stands (Story 1.8, redesigned to the
 * new mockups), then a Details card with its fields, derived status and collaborators.
 * Renders nothing when the user may not read it; the workspace layout shows why. */
export async function OverviewTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const summary = await loadSummary(opportunity.id);

  return (
    <div className={`flex flex-col gap-6 ${PAGE_PADDING}`}>
      <h2 className="sr-only">Overview</h2>
      <OverviewLiveRefresh opportunityId={opportunity.id} />
      <OverviewSummary
        opportunityId={opportunity.id}
        data={summary}
        proposalDate={opportunity.target_proposal_date}
        today={utcToday()}
      />
      <Card role="region" aria-labelledby="overview-details">
        <div className="border-b border-border px-5 py-[18px]">
          <h3 id="overview-details" className="text-section">
            Details
          </h3>
        </div>
        <div className="flex flex-col gap-5 p-5">
          <dl className="grid grid-cols-1 gap-x-8 gap-y-3 md:grid-cols-2">
            <Detail term="Status">
              <StatusPill status={opportunity.status} />
            </Detail>
            <Detail term="Customer">{opportunity.customer_name}</Detail>
            <Detail term="Products in scope">
              <ul className="flex flex-col">
                {opportunity.products.map((product) => (
                  <li key={product}>{product}</li>
                ))}
              </ul>
            </Detail>
            <Detail term="Industry">{opportunity.industry}</Detail>
            <Detail term="Created">
              <span className="text-numeric">{formatDate(opportunity.created_at.slice(0, 10))}</span>
            </Detail>
          </dl>
          <div className="border-t border-border pt-5">
            <Collaborators key={opportunity.id} initial={opportunity} />
          </div>
        </div>
      </Card>
    </div>
  );
}
