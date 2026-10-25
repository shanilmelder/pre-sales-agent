import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AdminHeader } from "@/components/admin/admin-header";
import { AdminNav } from "@/components/admin/admin-nav";
import { AgentsAdmin } from "@/components/admin/agents-admin";
import { AppShell } from "@/components/shell/app-shell";
import { PageContent, PageHeader } from "@/components/shell/page-header";
import type { RegistryAgent } from "@/lib/admin";
import { createServerApiClient, getMe } from "@/lib/api/server";
import { isAdmin } from "@/lib/navigation";

export const metadata: Metadata = { title: "Agents · Pre Sales Agent Framework" };

type ListResult =
  | { kind: "ok"; agents: RegistryAgent[] }
  | { kind: "forbidden" }
  | { kind: "error" };

async function listAgents(): Promise<ListResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/registry/agents");
    if (data) return { kind: "ok", agents: data.items };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET registry agents failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET registry agents failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
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

/** Admin → Agents: the Agent registry. Selecting a row opens its inspector: config history,
 * a two-version diff, new and restored versions, and Enable/Disable (Story 7.3). */
export default async function AdminAgentsPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  if (!isAdmin(result.me.permissions)) {
    return (
      <AppShell me={result.me}>
        <NoAccessPage />
      </AppShell>
    );
  }

  const list = await listAgents();
  return (
    <AppShell me={result.me}>
      <AdminHeader />
      <PageContent>
        <AdminNav current="/admin/agents" />
        {list.kind === "forbidden" ? <NoAccess /> : null}
        {list.kind === "error" ? (
          <p>The platform is not reachable right now. Try again in a moment.</p>
        ) : null}
        {list.kind === "ok" ? <AgentsAdmin initialAgents={list.agents} /> : null}
      </PageContent>
    </AppShell>
  );
}
