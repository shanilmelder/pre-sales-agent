import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AdminHeader } from "@/components/admin/admin-header";
import { AdminNav } from "@/components/admin/admin-nav";
import { RetentionTables } from "@/components/admin/retention-tables";
import { AppShell } from "@/components/shell/app-shell";
import { PageContent, PageHeader } from "@/components/shell/page-header";
import { createServerApiClient, getMe } from "@/lib/api/server";
import { isAdmin } from "@/lib/navigation";
import type { RetentionOverview } from "@/lib/retention";

export const metadata: Metadata = { title: "Retention · Pre Sales Agent Framework" };

type LoadResult =
  | { kind: "ok"; overview: RetentionOverview }
  | { kind: "forbidden" }
  | { kind: "error" };

async function loadOverview(): Promise<LoadResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/admin/retention");
    if (data) return { kind: "ok", overview: data };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET retention failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET retention failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
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

/** Admin → Retention (Story 10.6): read only, for platform administrators. What the daily
 * purge will delete in the next 30 days and what it deleted recently. Nothing can be deleted
 * from here. */
export default async function AdminRetentionPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  if (!isAdmin(result.me.permissions)) {
    return (
      <AppShell me={result.me}>
        <NoAccessPage />
      </AppShell>
    );
  }

  const loaded = await loadOverview();
  return (
    <AppShell me={result.me}>
      <AdminHeader />
      <PageContent>
        <AdminNav current="/admin/retention" />
        {loaded.kind === "forbidden" ? <NoAccess /> : null}
        {loaded.kind === "error" ? (
          <p>The platform is not reachable right now. Try again in a moment.</p>
        ) : null}
        {loaded.kind === "ok" ? (
          <RetentionTables due={loaded.overview.due} recent={loaded.overview.recent} />
        ) : null}
      </PageContent>
    </AppShell>
  );
}
