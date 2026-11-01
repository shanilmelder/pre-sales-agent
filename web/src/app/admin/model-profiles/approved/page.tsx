import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AdminHeader } from "@/components/admin/admin-header";
import { AdminNav } from "@/components/admin/admin-nav";
import { ModelProfileApproved } from "@/components/admin/model-profile-approved";
import { ModelProfileSubnav } from "@/components/admin/model-profile-subnav";
import { AppShell } from "@/components/shell/app-shell";
import { PageContent, PageHeader } from "@/components/shell/page-header";
import { createServerApiClient, getMe } from "@/lib/api/server";
import type { ApprovedModel } from "@/lib/model-profiles";
import { isAdmin } from "@/lib/navigation";

export const metadata: Metadata = { title: "Approved models · Pre Sales Agent Framework" };

type ListResult = { kind: "ok"; models: ApprovedModel[] } | { kind: "forbidden" } | { kind: "error" };

async function listModels(): Promise<ListResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/registry/approved-models");
    if (data) return { kind: "ok", models: data.items };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET approved models failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET approved models failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

function NoAccess() {
  return <p>You don&apos;t have access to this page</p>;
}

export default async function AdminApprovedModelsPage() {
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

  const list = await listModels();
  return (
    <AppShell me={result.me}>
      <AdminHeader />
      <PageContent>
        <AdminNav current="/admin/model-profiles" />
        <ModelProfileSubnav current="/admin/model-profiles/approved" />
        {list.kind === "forbidden" ? <NoAccess /> : null}
        {list.kind === "error" ? (
          <p>The platform is not reachable right now. Try again in a moment.</p>
        ) : null}
        {list.kind === "ok" ? <ModelProfileApproved initialModels={list.models} /> : null}
      </PageContent>
    </AppShell>
  );
}
