import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AdminNav } from "@/components/admin/admin-nav";
import { EvalsView } from "@/components/admin/evals-view";
import { AppShell } from "@/components/shell/app-shell";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import { createServerApiClient, getMe } from "@/lib/api/server";
import type { EvalResult } from "@/lib/evals";
import { isAdmin } from "@/lib/navigation";

export const metadata: Metadata = { title: "Evals · Pre Sales Agent Framework" };

type ListResult =
  | { kind: "ok"; results: EvalResult[] }
  | { kind: "forbidden" }
  | { kind: "error" };

async function listResults(): Promise<ListResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/registry/evals");
    if (data) return { kind: "ok", results: data.items };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET eval results failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET eval results failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

function NoAccess() {
  return <p>You don&apos;t have access to this page</p>;
}

/** Non-admins: a header band titled "No access" (not the section name) and the access message. */
function NoAccessPage() {
  return (
    <>
      <PageHeader title="No access" />
      <PageContent>
        <NoAccess />
      </PageContent>
    </>
  );
}

/** Admin → Evals (Story 7.6): read-only results of `make eval`, for platform administrators. */
export default async function AdminEvalsPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  if (!isAdmin(result.me.permissions)) {
    return (
      <AppShell me={result.me}>
        <NoAccessPage />
      </AppShell>
    );
  }

  const list = await listResults();
  return (
    <AppShell me={result.me}>
      <PageHeader title="Evals" subtitle={PAGE_SUBTITLES.admin} />
      <PageContent>
        <AdminNav current="/admin/evals" />
        {list.kind === "forbidden" ? <NoAccess /> : null}
        {list.kind === "error" ? (
          <p>The platform is not reachable right now. Try again in a moment.</p>
        ) : null}
        {list.kind === "ok" ? <EvalsView results={list.results} /> : null}
      </PageContent>
    </AppShell>
  );
}
