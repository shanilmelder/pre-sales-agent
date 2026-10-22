import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { KnowledgeNav } from "@/components/knowledge/knowledge-nav";
import { SourcesTab } from "@/components/knowledge/sources-tab";
import { AppShell } from "@/components/shell/app-shell";
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

/** Knowledge → Sources (Checklists has its own route; Coverage comes with Story 3.5). */
export default async function KnowledgePage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const [list, types] = await Promise.all([loadSources(), activeIntegrationTypes()]);
  const sources: readonly KnowledgeSource[] = list.kind === "ok" ? list.sources : [];

  return (
    <AppShell me={result.me}>
      <div className="flex flex-col">
        <div className="flex flex-col gap-1 p-gutter pb-2">
          <h1 className="text-title">Knowledge</h1>
        </div>
        <KnowledgeNav current="sources" />
        <div className="h-2" />
        {list.kind === "error" || types === null ? (
          <p className="p-gutter">The platform is not reachable right now. Try again in a moment.</p>
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
