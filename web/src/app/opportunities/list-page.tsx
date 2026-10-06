// The My Opportunities and All Opportunities pages: one server component, two scopes.
import { PlusIcon } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import {
  getFacets,
  listOpportunities,
  parsePage,
  type ListScope,
} from "@/app/opportunities/data";
import { filtersHref, hasFilters, parseFilters, type Filters } from "@/app/opportunities/filters";
import { AccessGate, hasAccess } from "@/components/access-gate";
import { FilterBar } from "@/components/opportunities/filter-bar";
import { OpportunitiesTable } from "@/components/opportunities/opportunities-table";
import { AppShell } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";
import type { OpportunityPage } from "@/lib/opportunities";
import { canCreateOpportunity, NEW_OPPORTUNITY_HREF } from "@/lib/shortcuts";

const linkClass =
  "rounded-md border border-border px-2 py-1 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

function Pagination({
  page,
  basePath,
  filters,
}: {
  page: OpportunityPage;
  basePath: string;
  filters: Filters;
}) {
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
          <Link className={linkClass} href={filtersHref(basePath, filters, page.page - 1)}>
            Previous
          </Link>
        ) : null}
        {hasNext ? (
          <Link className={linkClass} href={filtersHref(basePath, filters, page.page + 1)}>
            Next
          </Link>
        ) : null}
      </div>
    </nav>
  );
}

/** A paginated Opportunity list with New Opportunity for those who may create. All
 * Opportunities (`scope="all"`) also has the filter bar; its filters live in the URL query
 * and are kept by the page links. Invalid filter values are dropped. */
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

  const query = await searchParams;
  const page = parsePage(query?.page);
  const filterable = scope === "all";
  const filters: Filters = filterable ? parseFilters(query) : {};
  const [list, facets] = await Promise.all([
    listOpportunities(scope, page, filters),
    filterable ? getFacets() : Promise.resolve(null),
  ]);
  if (list.kind === "ok" && list.page.items.length === 0 && page > 1) {
    // Past the last page (e.g. a hand-edited URL): go to the last one, or to the list
    // itself when there is nothing at all. Filters are kept.
    const { total, page_size } = list.page;
    redirect(filtersHref(basePath, filters, total > 0 ? Math.ceil(total / page_size) : 1));
  }
  const filtered = hasFilters(filters);
  const canCreate = canCreateOpportunity(result.me.permissions);

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
        {filterable ? (
          <FilterBar
            basePath={basePath}
            filters={filters}
            facets={facets?.kind === "ok" ? facets.facets : null}
          />
        ) : null}
        {list.kind === "error" ? (
          <p className="p-gutter">The platform is not reachable right now. Try again in a moment.</p>
        ) : (
          <>
            <OpportunitiesTable
              items={list.page.items}
              caption={title}
              canCreate={canCreate}
              clearFiltersHref={filtered ? basePath : undefined}
            />
            <Pagination page={list.page} basePath={basePath} filters={filters} />
          </>
        )}
      </div>
    </AppShell>
  );
}
