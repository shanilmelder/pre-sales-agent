// The Opportunities list: one server component, with All, Mine and Due in 14 days views.
import { PlusIcon } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import {
  getFacets,
  listOpportunities,
  parsePage,
  type ListScope,
} from "@/app/opportunities/data";
import {
  dueSoonFilters,
  filtersHref,
  hasFilters,
  isDueSoon,
  parseFilters,
  type Filters,
} from "@/app/opportunities/filters";
import { AccessGate, hasAccess } from "@/components/access-gate";
import { FilterBar } from "@/components/opportunities/filter-bar";
import { OpportunityViews } from "@/components/opportunities/opportunity-views";
import {
  OpportunitiesCard,
  OpportunitiesTable,
} from "@/components/opportunities/opportunities-table";
import { AppShell } from "@/components/shell/app-shell";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import { buttonVariants } from "@/components/ui/button";
import { getMe } from "@/lib/api/server";
import { MY_OPPORTUNITIES_HREF } from "@/lib/navigation";
import { utcToday, type OpportunityPage } from "@/lib/opportunities";
import { canCreateOpportunity, NEW_OPPORTUNITY_HREF } from "@/lib/shortcuts";

const linkClass =
  "rounded-md border border-border px-2 py-1 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

const BASE_PATH = "/opportunities";

/** The list's link for `scope`, `filters` and `page`. Mine carries no filters. */
function listHref(scope: ListScope, filters: Filters, page = 1): string {
  if (scope === "all") return filtersHref(BASE_PATH, filters, page);
  return page > 1 ? `${MY_OPPORTUNITIES_HREF}&page=${page}` : MY_OPPORTUNITIES_HREF;
}

function Pagination({
  page,
  scope,
  filters,
}: {
  page: OpportunityPage;
  scope: ListScope;
  filters: Filters;
}) {
  const first = (page.page - 1) * page.page_size + 1;
  const last = first + page.items.length - 1;
  const hasPrevious = page.page > 1;
  const hasNext = last < page.total;
  if (!hasPrevious && !hasNext && page.items.length === 0) return null;
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-2">
      <p className="text-meta text-muted-foreground text-numeric">
        {page.items.length > 0 ? `${first}–${last} of ${page.total}` : null}
      </p>
      <div className="flex gap-2">
        {hasPrevious ? (
          <Link className={linkClass} href={listHref(scope, filters, page.page - 1)}>
            Previous
          </Link>
        ) : null}
        {hasNext ? (
          <Link className={linkClass} href={listHref(scope, filters, page.page + 1)}>
            Next
          </Link>
        ) : null}
      </div>
    </nav>
  );
}

/** A paginated Opportunity list with New Opportunity for those who may create. `?view=mine`
 * lists the user's own Opportunities; otherwise it lists every Opportunity with the filter
 * bar, whose filters live in the URL query and are kept by the page links. Invalid filter
 * values are dropped. */
export async function OpportunityListPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const query = await searchParams;
  const scope: ListScope = query?.view === "mine" ? "mine" : "all";
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
    redirect(listHref(scope, filters, total > 0 ? Math.ceil(total / page_size) : 1));
  }
  const filtered = hasFilters(filters);
  const canCreate = canCreateOpportunity(result.me.permissions);
  const today = utcToday();
  const view = !filterable ? "mine" : isDueSoon(filters, today) ? "due" : "all";

  return (
    <AppShell me={result.me}>
      <PageHeader
        title="Opportunities"
        subtitle={PAGE_SUBTITLES.opportunities}
        action={
          canCreate ? (
            <Link
              href={NEW_OPPORTUNITY_HREF}
              title="New Opportunity (C)"
              className={`${buttonVariants({ variant: "default" })} text-body-strong`}
            >
              <PlusIcon className="size-4" aria-hidden="true" />
              New Opportunity
            </Link>
          ) : undefined
        }
      />
      <PageContent>
        <div className="flex flex-wrap items-center gap-2">
          <OpportunityViews
            current={view}
            dueHref={filtersHref(BASE_PATH, dueSoonFilters(today))}
          />
          <div className="flex-1" />
          {filterable ? (
            <FilterBar
              basePath={BASE_PATH}
              filters={filters}
              facets={facets?.kind === "ok" ? facets.facets : null}
            />
          ) : null}
        </div>
        {list.kind === "error" ? (
          <OpportunitiesCard>
            <p className="px-6 py-14 text-center text-text-secondary">
              The platform is not reachable right now. Try again in a moment.
            </p>
          </OpportunitiesCard>
        ) : (
          <>
            <OpportunitiesTable
              items={list.page.items}
              caption="Opportunities"
              canCreate={canCreate}
              clearFiltersHref={filtered ? BASE_PATH : undefined}
            />
            <Pagination page={list.page} scope={scope} filters={filters} />
          </>
        )}
      </PageContent>
    </AppShell>
  );
}
