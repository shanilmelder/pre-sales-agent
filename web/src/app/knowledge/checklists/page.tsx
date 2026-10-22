import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { ChecklistsTab, type CatalogueOption } from "@/components/knowledge/checklists-tab";
import { KnowledgeNav } from "@/components/knowledge/knowledge-nav";
import { AppShell } from "@/components/shell/app-shell";
import { createServerApiClient, getMe } from "@/lib/api/server";

import { loadChecklists } from "./actions";

export const metadata: Metadata = { title: "Checklists · Knowledge · Pre-Sales Agent" };

/** The active catalogue entries (Integration Types and Work Packages), for scope tags and
 * affected areas. */
async function activeCatalogue(): Promise<CatalogueOption[] | null> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/catalogue/entries", {});
    if (data) {
      return data.items.map((entry) => ({ id: entry.id, kind: entry.kind, name: entry.name }));
    }
    console.error(`GET catalogue failed: status=${response.status}`);
    return null;
  } catch (thrown) {
    console.error(`GET catalogue failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return null;
  }
}

/** Knowledge → Checklists (Story 3.4). */
export default async function KnowledgeChecklistsPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const [list, catalogue] = await Promise.all([loadChecklists(), activeCatalogue()]);

  return (
    <AppShell me={result.me}>
      <div className="flex flex-col">
        <div className="flex flex-col gap-1 p-gutter pb-2">
          <h1 className="text-title">Knowledge</h1>
        </div>
        <KnowledgeNav current="checklists" />
        <div className="h-2" />
        {list.kind === "error" || catalogue === null ? (
          <p className="p-gutter">The platform is not reachable right now. Try again in a moment.</p>
        ) : (
          <ChecklistsTab
            initialChecklists={list.checklists}
            catalogue={catalogue}
            permissions={result.me.permissions}
          />
        )}
      </div>
    </AppShell>
  );
}
