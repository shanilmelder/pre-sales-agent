import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { UsersAdmin } from "@/components/admin/users-admin";
import { AppShell } from "@/components/shell/app-shell";
import type { components } from "@/lib/api/client";
import { createServerApiClient, getMe } from "@/lib/api/server";
import { isAdmin } from "@/lib/navigation";

export const metadata: Metadata = { title: "Users & roles · Pre-Sales Agent" };

type AdminUserPage = components["schemas"]["AdminUserPage"];

const PAGE_SIZE = 50;

type ListResult = { kind: "ok"; page: AdminUserPage } | { kind: "forbidden" } | { kind: "error" };

/** `?page=` as a positive integer (1 for anything else). */
function parsePage(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || !/^[1-9]\d{0,5}$/.test(raw)) return 1;
  return Number(raw);
}

async function listUsers(page: number): Promise<ListResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/admin/users", {
      params: { query: { page, page_size: PAGE_SIZE } },
    });
    if (data) return { kind: "ok", page: data };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET admin users failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET admin users failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

function NoAccess() {
  return (
    <div className="p-gutter">
      <p>You don&apos;t have access to this page</p>
    </div>
  );
}

function Pagination({ page }: { page: AdminUserPage }) {
  const first = (page.page - 1) * page.page_size + 1;
  const last = first + page.items.length - 1;
  const hasPrevious = page.page > 1;
  const hasNext = last < page.total;
  const linkClass =
    "rounded-md border border-border px-2 py-1 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary";
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-2 p-gutter">
      <p className="text-meta text-muted-foreground text-numeric">
        {page.items.length > 0 ? `${first}–${last} of ${page.total}` : null}
      </p>
      <div className="flex gap-2">
        {hasPrevious ? (
          <Link className={linkClass} href={`/admin/users?page=${page.page - 1}`}>
            Previous
          </Link>
        ) : null}
        {hasNext ? (
          <Link className={linkClass} href={`/admin/users?page=${page.page + 1}`}>
            Next
          </Link>
        ) : null}
      </div>
    </nav>
  );
}

export default async function AdminUsersPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  if (!isAdmin(result.me.roles)) {
    return (
      <AppShell me={result.me}>
        <NoAccess />
      </AppShell>
    );
  }

  const page = parsePage((await searchParams)?.page);
  const list = await listUsers(page);
  if (list.kind === "ok" && list.page.items.length === 0 && list.page.total > 0) {
    // Past the last page (e.g. users were removed, or a hand-edited URL): go to the last one.
    redirect(`/admin/users?page=${Math.ceil(list.page.total / list.page.page_size)}`);
  }
  return (
    <AppShell me={result.me}>
      <div className="flex flex-col">
        <div className="flex flex-col gap-1 p-gutter">
          <h1 className="text-title">Users &amp; roles</h1>
          <p className="text-meta text-muted-foreground">
            Role changes apply on the person&apos;s next request.
          </p>
        </div>
        {list.kind === "forbidden" ? <NoAccess /> : null}
        {list.kind === "error" ? (
          <p className="p-gutter">The platform is not reachable right now. Try again in a moment.</p>
        ) : null}
        {list.kind === "ok" ? (
          <>
            <UsersAdmin key={list.page.page} initialUsers={list.page.items} />
            <Pagination page={list.page} />
          </>
        ) : null}
      </div>
    </AppShell>
  );
}
