import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { KnowledgeNav, KNOWLEDGE_SUBTITLE } from "@/components/knowledge/knowledge-nav";
import { SourcesTab } from "@/components/knowledge/sources-tab";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { createServerApiClient, getMe } from "@/lib/api/server";
import type { KnowledgeSource } from "@/lib/knowledge-sources";

import { loadSources } from "./actions";

export const metadata: Metadata = { title: "Knowledge · Pre Sales Agent Framework" };

async function activeIntegrationTypes(): Promise<{ id: string; name: string }[] | null> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/catalogue/entries", {
      params: { query: { kind: "integration_type" } },
    });
    if (data) return data.items.map((entry) => ({ id: entry.id, name: entry.name }));
    console.error(`GET integration types failed: status=${response.status}`);
    return null;
  } catch (thrown) {
    console.error(`GET integration types failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return null;
  }
}

/** Knowledge → Sources (the Checklists and Coverage tabs come with later stories). */
export default async function KnowledgePage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const [list, types] = await Promise.all([loadSources(), activeIntegrationTypes()]);
  const sources: readonly KnowledgeSource[] = list.kind === "ok" ? list.sources : [];

  return (
    <AppShell me={result.me}>
      <div className="flex flex-col">
        {list.kind === "error" || types === null ? (
          <>
            <PageHeader title="Knowledge" subtitle={KNOWLEDGE_SUBTITLE} />
            <KnowledgeNav />
            <p className="p-gutter">
              The platform is not reachable right now. Try again in a moment.
            </p>
          </>
        ) : (
          <SourcesTab
            initialSources={sources}
            integrationTypes={types}
            me={{ id: result.me.id, roles: result.me.roles }}
          />
        )}
      </div>
    </AppShell>
  );
}
