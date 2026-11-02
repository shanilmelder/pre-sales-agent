import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AdminHeader } from "@/components/admin/admin-header";
import { AdminNav } from "@/components/admin/admin-nav";
import { ModelProfileSubnav } from "@/components/admin/model-profile-subnav";
import { ModelProfilesAdmin } from "@/components/admin/model-profiles-admin";
import { AppShell } from "@/components/shell/app-shell";
import { PageContent, PageHeader } from "@/components/shell/page-header";
import { createServerApiClient, getMe } from "@/lib/api/server";
import type { ApprovedModel, ModelProfile } from "@/lib/model-profiles";
import { isAdmin } from "@/lib/navigation";

export const metadata: Metadata = { title: "Model profiles · Pre Sales Agent Framework" };

type ListResult =
  | { kind: "ok"; profiles: ModelProfile[]; approved: ApprovedModel[] }
  | { kind: "forbidden" }
  | { kind: "error" };

async function listProfiles(): Promise<ListResult> {
  try {
    const api = await createServerApiClient();
    const [profiles, approved] = await Promise.all([
      api.GET("/api/v1/registry/model-profiles"),
      api.GET("/api/v1/registry/approved-models"),
    ]);
    if (profiles.data && approved.data) {
      return { kind: "ok", profiles: profiles.data.items, approved: approved.data.items };
    }
    const status = (profiles.data ? approved.response : profiles.response).status;
    if (status === 403) return { kind: "forbidden" };
    console.error(`GET model profiles failed: status=${status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET model profiles failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

function NoAccess() {
  return <p>You don&apos;t have access to this page</p>;
}

export default async function AdminModelProfilesPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  if (!isAdmin(result.me.permissions)) {
    return (
      <AppShell me={result.me}>
        <PageHeader title="No access" />
        <PageContent>
          <NoAccess />
        </PageContent>
      </AppShell>
    );
  }

  const list = await listProfiles();
  return (
    <AppShell me={result.me}>
      <AdminHeader />
      <PageContent>
        <AdminNav current="/admin/model-profiles" />
        <ModelProfileSubnav current="/admin/model-profiles" />
        {list.kind === "forbidden" ? <NoAccess /> : null}
        {list.kind === "error" ? (
          <p>The platform is not reachable right now. Try again in a moment.</p>
        ) : null}
        {list.kind === "ok" ? (
          <ModelProfilesAdmin initialProfiles={list.profiles} approved={list.approved} />
        ) : null}
      </PageContent>
    </AppShell>
  );
}
