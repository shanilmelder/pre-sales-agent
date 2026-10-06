import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AdminNav } from "@/components/admin/admin-nav";
import { CatalogueAdmin } from "@/components/admin/catalogue-admin";
import { AppShell } from "@/components/shell/app-shell";
import { createServerApiClient, getMe } from "@/lib/api/server";
import type { CatalogueEntry } from "@/lib/catalogue";
import { isAdmin } from "@/lib/navigation";

export const metadata: Metadata = { title: "Catalogue · Pre-Sales Agent" };

type ListResult =
  | { kind: "ok"; entries: CatalogueEntry[] }
  | { kind: "forbidden" }
  | { kind: "error" };

async function listEntries(): Promise<ListResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/catalogue/entries", {
      params: { query: { include_retired: true } },
    });
    if (data) return { kind: "ok", entries: data.items };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET catalogue failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET catalogue failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

function NoAccess() {
  return (
    <div className="p-gutter">
      <p>You don&apos;t have access to this page</p>
    </div>
  );
}

export default async function AdminCataloguePage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  if (!isAdmin(result.me.roles)) {
    return (
      <AppShell me={result.me}>
        <NoAccess />
      </AppShell>
    );
  }

  const list = await listEntries();
  return (
    <AppShell me={result.me}>
      <div className="flex flex-col">
        <div className="flex flex-col gap-1 p-gutter pb-2">
          <h1 className="text-title">Catalogue</h1>
        </div>
        <AdminNav current="/admin/catalogue" />
        <div className="h-2" />
        {list.kind === "forbidden" ? <NoAccess /> : null}
        {list.kind === "error" ? (
          <p className="p-gutter">The platform is not reachable right now. Try again in a moment.</p>
        ) : null}
        {list.kind === "ok" ? <CatalogueAdmin initialEntries={list.entries} /> : null}
      </div>
    </AppShell>
  );
}
