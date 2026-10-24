import type { Metadata } from "next";
import type { ReactNode } from "react";

import {
  countBlockingFindings,
  countOpenConflicts,
  countOpenGaps,
} from "@/app/opportunities/actions";
import {
  getConflicts,
  getCritic,
  getOpportunity,
  getRedTeam,
  listGaps,
} from "@/app/opportunities/data";
import { AccessGate, hasAccess } from "@/components/access-gate";
import { WorkspaceHeader } from "@/components/opportunities/workspace-header";
import { WorkspaceTabs } from "@/components/opportunities/workspace-tabs";
import { AppShell } from "@/components/shell/app-shell";
import { PageContent, PageHeader } from "@/components/shell/page-header";
import { getMe } from "@/lib/api/server";
import { totalBlocking } from "@/lib/findings";
import { openGapCount } from "@/lib/gaps";
import { NO_ACCESS_TO_OPPORTUNITY, utcToday } from "@/lib/opportunities";

// The title stays generic: customer names are not put in the tab title or history.
export const metadata: Metadata = { title: "Opportunity · Pre Sales Agent Framework" };

/** The Opportunity workspace: header and tab strip around every tab. Fetched here once per
 * navigation into the workspace (with the Conflicts, Gaps and Assessments tabs' counts, which
 * then follow the event stream); switching tabs re-renders only the tab page. Each tab page
 * gates itself too, since a layout can't keep a page out of the payload. */
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
  // The Conflicts tab's badge: open plus escalated, kept live over the event stream (6.2).
  const conflicts = loaded.kind === "ok" ? await getConflicts(loaded.opportunity.id) : null;
  // The Gaps tab's badge: open Gaps, kept live over the event stream (Story 4.7).
  const gaps = loaded.kind === "ok" ? await listGaps(loaded.opportunity.id) : null;
  // The Assessments tab's badge: open critical Critic and Red Team Findings (Story 6.6).
  const [redTeam, critic] =
    loaded.kind === "ok"
      ? await Promise.all([getRedTeam(loaded.opportunity.id), getCritic(loaded.opportunity.id)])
      : [null, null];
  const blocking = totalBlocking(
    redTeam?.kind === "ok" ? redTeam.redTeam : null,
    critic?.kind === "ok" ? critic.critic : null,
  );
  const counts = {
    ...(conflicts?.kind === "ok" ? { conflicts: conflicts.conflicts.open_count } : {}),
    // (`items` is checked: a partial read must not break the whole workspace.)
    ...(gaps?.kind === "ok" && Array.isArray(gaps.list.items)
      ? { gaps: openGapCount(gaps.list.items) }
      : {}),
    ...(blocking !== null ? { assessments: blocking } : {}),
  };

  return (
    <AppShell me={result.me}>
      {loaded.kind === "not-found" ? (
        <>
          {/* A generic "Opportunity" title: this one may not exist or not be visible to this user. */}
          <PageHeader title="Opportunity" />
          <PageContent>
            <p>{NO_ACCESS_TO_OPPORTUNITY}</p>
          </PageContent>
        </>
      ) : loaded.kind === "error" ? (
        <>
          <PageHeader title="Opportunity" />
          <PageContent>
            <p>The platform is not reachable right now. Try again in a moment.</p>
          </PageContent>
        </>
      ) : (
        <>
          <WorkspaceHeader opportunity={loaded.opportunity} today={utcToday()} />
          <WorkspaceTabs
            id={loaded.opportunity.id}
            counts={counts}
            loadGapCount={countOpenGaps}
            loadConflictCount={countOpenConflicts}
            loadBlockingCount={countBlockingFindings}
          >
            {children}
          </WorkspaceTabs>
        </>
      )}
    </AppShell>
  );
}
