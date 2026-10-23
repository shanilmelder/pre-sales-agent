import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { CreateOpportunityForm } from "@/components/opportunities/create-form";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { getMe } from "@/lib/api/server";
import { canCreateOpportunity } from "@/lib/shortcuts";

export const metadata: Metadata = { title: "New Opportunity · Pre Sales Agent Framework" };

/** Create an Opportunity (with `opportunities.opportunity.create`; the API decides). */
export default async function NewOpportunityPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  return (
    <AppShell me={result.me}>
      <div className="flex flex-col">
        <PageHeader
          title="New Opportunity"
          subtitle="Import a file or enter the customer details to start."
        />
        {canCreateOpportunity(result.me.permissions) ? (
          <CreateOpportunityForm />
        ) : (
          <p className="p-gutter">You don&apos;t have access to create Opportunities.</p>
        )}
      </div>
    </AppShell>
  );
}
