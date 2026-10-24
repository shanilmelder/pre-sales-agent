import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AdminHeader } from "@/components/admin/admin-header";
import { AdminNav } from "@/components/admin/admin-nav";
import { AgentsSubnav } from "@/components/admin/agents-subnav";
import { ToolDenialsFilters } from "@/components/admin/tool-denials-filters";
import { ToolDenialsTable } from "@/components/admin/tool-denials-table";
import { AppShell } from "@/components/shell/app-shell";
import { PageContent, PageHeader } from "@/components/shell/page-header";
import {
  denialsHref,
  hasDenialFilters,
  NO_DENIALS,
  NO_MATCHING_DENIALS,
  parseDenialFilters,
  type DenialFilters,
  type RegistryAgent,
  type ToolDenialPage,
} from "@/lib/admin";
import { createServerApiClient, getMe } from "@/lib/api/server";
import { isAdmin } from "@/lib/navigation";

export const metadata: Metadata = { title: "Denied tool calls · Pre Sales Agent Framework" };

const PAGE_SIZE = 50;

type ListResult = { kind: "ok"; page: ToolDenialPage } | { kind: "forbidden" } | { kind: "error" };

/** `?page=` as a positive integer (1 for anything else). */
function parsePage(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || !/^[1-9]\d{0,5}$/.test(raw)) return 1;
  return Number(raw);
}

async function listDenials(filters: DenialFilters, page: number): Promise<ListResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/registry/tool-denials", {
      params: { query: { ...filters, page, page_size: PAGE_SIZE } },
    });
    if (data) return { kind: "ok", page: data };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET tool denials failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET tool denials failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** The registered Agents for the filter; none when they can't be read (the filter then offers
 * only "Any agent" and the URL's agent). */
async function listAgents(): Promise<RegistryAgent[]> {
  try {
    const api = await createServerApiClient();
    const { data } = await api.GET("/api/v1/registry/agents");
    return data?.items ?? [];
  } catch {
    return [];
  }
}

function NoAccess() {
  return <p>You don&apos;t have access to this page</p>;
}

/** Non-admins: a header band titled "No access" (not the section name) and the access message. */
function NoAccessPage() {
  return (
    <>
      <PageHeader title="No access" />
      <PageContent>
        <NoAccess />
      </PageContent>
    </>
  );
}

function Pagination({ page, filters }: { page: ToolDenialPage; filters: DenialFilters }) {
  const first = (page.page - 1) * page.page_size + 1;
  const last = first + page.items.length - 1;
  const hasPrevious = page.page > 1;
  const hasNext = last < page.total;
  const linkClass =
    "rounded-md border border-border px-2 py-1 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary";
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-2">
      <p className="text-meta text-muted-foreground text-numeric">
        {page.items.length > 0 ? `${first}–${last} of ${page.total}` : null}
      </p>
      <div className="flex gap-2">
        {hasPrevious ? (
          <Link className={linkClass} href={denialsHref(filters, page.page - 1)}>
            Previous
          </Link>
        ) : null}
        {hasNext ? (
          <Link className={linkClass} href={denialsHref(filters, page.page + 1)}>
            Next
          </Link>
        ) : null}
      </div>
    </nav>
  );
}

/** Admin → Agents → Denied tool calls (Story 7.4): every ToolGateway call the gateway refused,
 * newest first, filtered by Agent and date in the URL and paged like Admin → Users. Ids and
 * timings only. */
export default async function AdminToolDenialsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  if (!isAdmin(result.me.permissions)) {
    return (
      <AppShell me={result.me}>
        <NoAccessPage />
      </AppShell>
    );
  }

  const params = await searchParams;
  const filters = parseDenialFilters(params);
  const page = parsePage(params?.page);
  const [list, agents] = await Promise.all([listDenials(filters, page), listAgents()]);
  if (list.kind === "ok" && list.page.items.length === 0 && list.page.total > 0) {
    // Past the last page (a hand-edited URL): go to the last one.
    redirect(denialsHref(filters, Math.ceil(list.page.total / list.page.page_size)));
  }
  return (
    <AppShell me={result.me}>
      <AdminHeader />
      <PageContent>
        <AdminNav current="/admin/agents" />
        <AgentsSubnav current="/admin/agents/denials" />
        {list.kind === "forbidden" ? <NoAccess /> : null}
        {list.kind === "error" ? (
          <p>The platform is not reachable right now. Try again in a moment.</p>
        ) : null}
        {list.kind === "ok" ? (
          <>
            <ToolDenialsFilters filters={filters} agents={agents} />
            <ToolDenialsTable
              denials={list.page.items}
              empty={hasDenialFilters(filters) ? NO_MATCHING_DENIALS : NO_DENIALS}
            />
            <Pagination page={list.page} filters={filters} />
          </>
        ) : null}
      </PageContent>
    </AppShell>
  );
}
