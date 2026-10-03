import { getOpportunity } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { Collaborators } from "@/components/opportunities/collaborators";
import { StatusPill } from "@/components/opportunities/status-pill";
import { getMe } from "@/lib/api/server";
import { formatDate } from "@/lib/opportunities";

function Detail({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[12rem_1fr] items-baseline gap-2">
      <dt className="text-label text-muted-foreground">{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Tab 1: the Opportunity's fields, derived status, owner and collaborators. Renders nothing
 * when the user may not read it; the workspace layout shows why. */
export async function OverviewTab({ id }: { id: string }) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;

  return (
    <div className="flex flex-col gap-6 p-gutter">
      <h2 className="sr-only">Overview</h2>
      <dl className="flex flex-col gap-2">
        <Detail term="Status">
          <StatusPill status={opportunity.status} />
        </Detail>
        <Detail term="Customer">{opportunity.customer_name}</Detail>
        <Detail term="Products in scope">
          <ul className="flex flex-col">
            {opportunity.products.map((product) => (
              <li key={product}>{product}</li>
            ))}
          </ul>
        </Detail>
        <Detail term="Industry">{opportunity.industry}</Detail>
        <Detail term="Created">
          <span className="text-numeric">{formatDate(opportunity.created_at.slice(0, 10))}</span>
        </Detail>
      </dl>
      <Collaborators key={opportunity.id} initial={opportunity} />
    </div>
  );
}
