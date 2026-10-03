// The My Opportunities and All Opportunities pages: one server component, two scopes.
import { PlusIcon } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { listOpportunities, parsePage, type ListScope } from "@/app/opportunities/data";
import { AccessGate, hasAccess } from "@/components/access-gate";
import { OpportunitiesTable } from "@/components/opportunities/opportunities-table";
import { AppShell } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";
import type { OpportunityPage } from "@/lib/opportunities";
import { canCreateOpportunity, NEW_OPPORTUNITY_HREF } from "@/lib/shortcuts";

const linkClass =
  "rounded-md border border-border px-2 py-1 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

function Pagination({ page, basePath }: { page: OpportunityPage; basePath: string }) {
  const first = (page.page - 1) * page.page_size + 1;
  const last = first + page.items.length - 1;
  const hasPrevious = page.page > 1;
  const hasNext = last < page.total;
  if (!hasPrevious && !hasNext && page.items.length === 0) return null;
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-2 p-gutter">
      <p className="text-meta text-muted-foreground text-numeric">
        {page.items.length > 0 ? `${first}–${last} of ${page.total}` : null}
      </p>
      <div className="flex gap-2">
        {hasPrevious ? (
          <Link className={linkClass} href={`${basePath}?page=${page.page - 1}`}>
            Previous
          </Link>
        ) : null}
        {hasNext ? (
          <Link className={linkClass} href={`${basePath}?page=${page.page + 1}`}>
            Next
          </Link>
        ) : null}
      </div>
    </nav>
  );
}

/** A paginated Opportunity list with New Opportunity for presales engineers. */
export async function OpportunityListPage({
  title,
  scope,
  basePath,
  searchParams,
}: {
  title: string;
  scope: ListScope;
  basePath: string;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const page = parsePage((await searchParams)?.page);
  const list = await listOpportunities(scope, page);
  if (list.kind === "ok" && list.page.items.length === 0 && page > 1) {
    // Past the last page (e.g. a hand-edited URL): go to the last one, or to the list
    // itself when there is nothing at all.
    const { total, page_size } = list.page;
    redirect(total > 0 ? `${basePath}?page=${Math.ceil(total / page_size)}` : basePath);
  }
  const canCreate = canCreateOpportunity(result.me.roles);

  return (
    <AppShell me={result.me}>
      <div className="flex flex-col">
        <div className="flex items-center justify-between gap-2 p-gutter">
          <h1 className="text-title">{title}</h1>
          {canCreate ? (
            <Link
              href={NEW_OPPORTUNITY_HREF}
              title="New Opportunity (C)"
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-label text-primary-foreground outline-none hover:bg-primary/80 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
            >
              <PlusIcon className="size-4" aria-hidden="true" />
              New Opportunity
            </Link>
          ) : null}
        </div>
        {list.kind === "error" ? (
          <p className="p-gutter">The platform is not reachable right now. Try again in a moment.</p>
        ) : (
          <>
            <OpportunitiesTable items={list.page.items} caption={title} canCreate={canCreate} />
            <Pagination page={list.page} basePath={basePath} />
          </>
        )}
      </div>
    </AppShell>
  );
}
