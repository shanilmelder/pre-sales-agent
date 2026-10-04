import { notFound } from "next/navigation";

import { OverviewTab } from "@/app/opportunities/[id]/overview";
import { RequirementsTab } from "@/app/opportunities/[id]/requirements";
import { SourcesTab } from "@/app/opportunities/[id]/sources";
import { isWorkspaceTab, TAB_NOT_AVAILABLE, WORKSPACE_TABS } from "@/lib/workspace";

/** `/opportunities/{id}/{tab}`: Overview, Sources, Requirements, or "Not available yet." for
 * a tab later epics build. An unknown slug is the not-found page. */
export default async function WorkspaceTabPage({
  params,
}: {
  params: Promise<{ id: string; tab: string }>;
}) {
  const { id, tab } = await params;
  if (!isWorkspaceTab(tab)) notFound();
  if (tab === "overview") return await OverviewTab({ id });
  if (tab === "sources") return await SourcesTab({ id });
  if (tab === "requirements") return await RequirementsTab({ id });
  return (
    <div className="p-gutter">
      <h2 className="sr-only">{WORKSPACE_TABS.find((t) => t.slug === tab)?.label}</h2>
      <p className="text-muted-foreground">{TAB_NOT_AVAILABLE}</p>
    </div>
  );
}
