import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { KnowledgeNav } from "@/components/knowledge/knowledge-nav";
import { SourcesTab } from "@/components/knowledge/sources-tab";
import { AppShell } from "@/components/shell/app-shell";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import { createServerApiClient, getMe } from "@/lib/api/server";
import { seededFilters } from "@/lib/coverage";
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

/** Knowledge → Sources (Checklists and Coverage have their own routes). `?product=&type=`
 * (a Coverage cell's link) seeds the product and Integration Type filters. */
export default async function KnowledgePage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
} = {}) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  const seeded = seededFilters(await searchParams);

  const [list, types] = await Promise.all([loadSources(), activeIntegrationTypes()]);
  const sources: readonly KnowledgeSource[] = list.kind === "ok" ? list.sources : [];

  return (
    <AppShell me={result.me}>
      <PageHeader title="Knowledge" subtitle={PAGE_SUBTITLES.knowledge} />
      <PageContent>
        <KnowledgeNav current="sources" />
        {list.kind === "error" || types === null ? (
          <p>The platform is not reachable right now. Try again in a moment.</p>
        ) : (
          <SourcesTab
            key={`${seeded.product}|${seeded.integrationTypeId}`}
            initialFilters={seeded}
            initialSources={sources}
            integrationTypes={types}
            me={{ id: result.me.id, roles: result.me.roles }}
          />
        )}
      </PageContent>
    </AppShell>
  );
}
