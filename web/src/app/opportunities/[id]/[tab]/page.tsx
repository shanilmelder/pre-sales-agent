import { notFound } from "next/navigation";

import { AssessmentsTab } from "@/app/opportunities/[id]/assessments";
import { ConflictsTab } from "@/app/opportunities/[id]/conflicts";
import { EstimateTab } from "@/app/opportunities/[id]/estimate";
import { GapsTab } from "@/app/opportunities/[id]/gaps";
import { OverviewTab } from "@/app/opportunities/[id]/overview";
import { RequirementsTab } from "@/app/opportunities/[id]/requirements";
import { SourcesTab } from "@/app/opportunities/[id]/sources";
import { TraceTab } from "@/app/opportunities/[id]/trace";
import { isWorkspaceTab, TAB_NOT_AVAILABLE, WORKSPACE_TABS } from "@/lib/workspace";

/** `/opportunities/{id}/{tab}`: Overview, Sources, Requirements, Gaps, Assessments,
 * Conflicts, Estimate, Trace, or "Not available yet." for a tab later epics build. An unknown slug is the
 * not-found page. */
export default async function WorkspaceTabPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; tab: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id, tab } = await params;
  if (!isWorkspaceTab(tab)) notFound();
  if (tab === "overview") return await OverviewTab({ id });
  if (tab === "sources") return await SourcesTab({ id });
  if (tab === "requirements") return await RequirementsTab({ id });
  if (tab === "gaps") return await GapsTab({ id });
  if (tab === "assessments") return await AssessmentsTab({ id });
  if (tab === "conflicts") return await ConflictsTab({ id });
  if (tab === "estimate") return await EstimateTab({ id });
  if (tab === "trace") return await TraceTab({ id, searchParams: (await searchParams) ?? {} });
  return (
    <div className="p-gutter">
      <h2 className="sr-only">{WORKSPACE_TABS.find((t) => t.slug === tab)?.label}</h2>
      <p className="text-muted-foreground">{TAB_NOT_AVAILABLE}</p>
    </div>
  );
}
