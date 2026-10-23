import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { CreateOpportunityForm } from "@/components/opportunities/create-form";
import { AppShell } from "@/components/shell/app-shell";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import { buttonVariants } from "@/components/ui/button";
import { getMe } from "@/lib/api/server";
import { CREATE_FORM_ID } from "@/lib/opportunities";
import { canCreateOpportunity } from "@/lib/shortcuts";

export const metadata: Metadata = { title: "New Opportunity · Pre Sales Agent Framework" };

/** Create an Opportunity (with `opportunities.opportunity.create`; the API decides). */
export default async function NewOpportunityPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const canCreate = canCreateOpportunity(result.me.permissions);
  return (
    <AppShell me={result.me}>
      <PageHeader
        title="New Opportunity"
        subtitle={PAGE_SUBTITLES.newOpportunity}
        action={
          canCreate ? (
            // Submits the form below (the form's own button stays at its end).
            <button
              type="submit"
              form={CREATE_FORM_ID}
              className={`${buttonVariants({ variant: "default" })} text-body-strong`}
            >
              Create Opportunity
            </button>
          ) : undefined
        }
      />
      <PageContent>
        {canCreate ? (
          <CreateOpportunityForm />
        ) : (
          <p>You don&apos;t have access to create Opportunities.</p>
        )}
      </PageContent>
    </AppShell>
  );
}
