import type { Metadata } from "next";

import { getOpportunity } from "@/app/opportunities/data";
import { AccessGate, hasAccess } from "@/components/access-gate";
import { Collaborators } from "@/components/opportunities/collaborators";
import { StatusPill } from "@/components/opportunities/status-pill";
import { AppShell } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";
import { formatDate, NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";

// The title stays generic: customer names are not put in the tab title or history.
export const metadata: Metadata = { title: "Opportunity · Pre-Sales Agent" };

function Detail({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[12rem_1fr] items-baseline gap-2">
      <dt className="text-label text-muted-foreground">{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** One Opportunity: its fields, derived status, owner and collaborators. */
export default async function OpportunityPage({ params }: { params: Promise<{ id: string }> }) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const { id } = await params;
  const loaded = await getOpportunity(id);

  return (
    <AppShell me={result.me}>
      {loaded.kind === "not-found" ? (
        <div className="p-gutter">
          <p>{NO_ACCESS_TO_OPPORTUNITY}</p>
        </div>
      ) : loaded.kind === "error" ? (
        <p className="p-gutter">The platform is not reachable right now. Try again in a moment.</p>
      ) : (
        <div className="flex flex-col gap-6 p-gutter">
          <div className="flex flex-col gap-2">
            <h1 className="text-title">{loaded.opportunity.title}</h1>
            <div>
              <StatusPill status={loaded.opportunity.status} />
            </div>
          </div>
          <dl className="flex flex-col gap-2">
            <Detail term="Customer">{loaded.opportunity.customer_name}</Detail>
            <Detail term="Products in scope">
              <ul className="flex flex-col">
                {loaded.opportunity.products.map((product) => (
                  <li key={product}>{product}</li>
                ))}
              </ul>
            </Detail>
            <Detail term="Industry">{loaded.opportunity.industry}</Detail>
            <Detail term="Target proposal date">
              <span className="text-numeric">
                {formatDate(loaded.opportunity.target_proposal_date)}
              </span>
            </Detail>
            <Detail term="Owner">{loaded.opportunity.owner.name}</Detail>
          </dl>
          <Collaborators key={loaded.opportunity.id} initial={loaded.opportunity} />
        </div>
      )}
    </AppShell>
  );
}
