import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { GraphCanvas } from "@/components/knowledge/graph-canvas";
import { KnowledgeNav } from "@/components/knowledge/knowledge-nav";
import { AppShell } from "@/components/shell/app-shell";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import { getMe } from "@/lib/api/server";
import { canAuthor } from "@/lib/checklists";
import { GRAPH_DENIED } from "@/lib/knowledge-graph";

import { loadGraph } from "./actions";

export const metadata: Metadata = { title: "Graph · Knowledge · Pre-Sales Agent" };

/** Knowledge → Graph (Story 3.6): Products, Integration Types, Knowledge Sources and
 * Checklists and their links, for admins and Checklist editors. Anyone else sees the
 * access-denied message (the tab is hidden for them, and the API answers 403). */
export default async function KnowledgeGraphPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  const permitted = canAuthor(result.me.permissions);
  const graph = permitted ? await loadGraph() : ({ kind: "forbidden" } as const);

  return (
    <AppShell me={result.me}>
      <PageHeader title="Knowledge" subtitle={PAGE_SUBTITLES.knowledge} />
      <PageContent>
        <KnowledgeNav current="graph" showGraph={permitted} />
        {graph.kind === "ok" ? (
          <GraphCanvas
            initialGraph={graph.graph}
            me={{ id: result.me.id, roles: result.me.roles }}
          />
        ) : graph.kind === "forbidden" ? (
          <p role="alert">{GRAPH_DENIED}</p>
        ) : (
          <p>The platform is not reachable right now. Try again in a moment.</p>
        )}
      </PageContent>
    </AppShell>
  );
}
