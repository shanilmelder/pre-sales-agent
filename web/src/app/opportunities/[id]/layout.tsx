import type { Metadata } from "next";
import type { ReactNode } from "react";

import { getConflicts, getOpportunity } from "@/app/opportunities/data";
import { AccessGate, hasAccess } from "@/components/access-gate";
import { WorkspaceHeader } from "@/components/opportunities/workspace-header";
import { WorkspaceTabs } from "@/components/opportunities/workspace-tabs";
import { AppShell } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";

// The title stays generic: customer names are not put in the tab title or history.
export const metadata: Metadata = { title: "Opportunity · Pre-Sales Agent" };

/** The Opportunity workspace: header and tab strip around every tab. Fetched here once per
 * navigation into the workspace (with the Conflicts tab's open count, refreshed by a
 * navigation or `router.refresh()`); switching tabs re-renders only the tab page. Each tab
 * page gates itself too, since a layout can't keep a page out of the payload. */
export default async function OpportunityLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ id: string }>;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const { id } = await params;
  const loaded = await getOpportunity(id);
  // The Conflicts tab's badge: open plus escalated, read with the layout (no live updates).
  const conflicts = loaded.kind === "ok" ? await getConflicts(loaded.opportunity.id) : null;
  const counts = conflicts?.kind === "ok" ? { conflicts: conflicts.conflicts.open_count } : {};

  return (
    <AppShell me={result.me}>
      {loaded.kind === "not-found" ? (
        <div className="p-gutter">
          <p>{NO_ACCESS_TO_OPPORTUNITY}</p>
        </div>
      ) : loaded.kind === "error" ? (
        <p className="p-gutter">The platform is not reachable right now. Try again in a moment.</p>
      ) : (
        <>
          <WorkspaceHeader opportunity={loaded.opportunity} />
          <WorkspaceTabs id={loaded.opportunity.id} counts={counts}>
            {children}
          </WorkspaceTabs>
        </>
      )}
    </AppShell>
  );
}
