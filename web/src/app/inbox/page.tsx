import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { getInbox } from "@/app/inbox/actions";
import { AccessGate, hasAccess } from "@/components/access-gate";
import { InboxView, inboxHref } from "@/components/inbox/inbox-view";
import { AppShell } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";
import { parsePage } from "@/lib/pagination";

export const metadata: Metadata = { title: "Inbox · Pre Sales Agent Framework" };

/** The Inbox (Story 9.2): the signed-in user's own items, 25 a page (`?page=`). */
export default async function InboxPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const page = parsePage((await searchParams)?.page);
  const inbox = await getInbox(page);
  if (inbox.kind === "ok" && inbox.page.items.length === 0 && page > 1) {
    // Past the last page (e.g. a hand-edited URL, or items read elsewhere): go to the last one.
    const { total, page_size } = inbox.page;
    redirect(inboxHref(total > 0 ? Math.ceil(total / page_size) : 1));
  }

  return (
    <AppShell me={result.me}>
      <InboxView
        key={page}
        initial={inbox.kind === "ok" ? inbox.page : null}
        pageNumber={page}
      />
    </AppShell>
  );
}
