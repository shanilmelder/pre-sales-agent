import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AppShell, PlaceholderPage } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";

export const metadata: Metadata = { title: "Inbox · Pre Sales Agent Framework" };

export default async function InboxPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  return (
    <AppShell me={result.me}>
      <PlaceholderPage
        title="Inbox"
        subtitle="Updates and requests that need your attention."
        message="Nothing waiting for you."
      />
    </AppShell>
  );
}
