import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { CreateOpportunityForm } from "@/components/opportunities/create-form";
import { AppShell } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";
import { canCreateOpportunity } from "@/lib/shortcuts";

export const metadata: Metadata = { title: "New Opportunity · Pre-Sales Agent" };

/** Create an Opportunity (presales engineers; the API decides). */
export default async function NewOpportunityPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  return (
    <AppShell me={result.me}>
      <div className="flex flex-col">
        <div className="p-gutter pb-0">
          <h1 className="text-title">New Opportunity</h1>
        </div>
        {canCreateOpportunity(result.me.roles) ? (
          <CreateOpportunityForm />
        ) : (
          <p className="p-gutter">You don&apos;t have access to create Opportunities.</p>
        )}
      </div>
    </AppShell>
  );
}
