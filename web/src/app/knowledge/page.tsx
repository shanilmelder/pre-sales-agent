import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AppShell, PlaceholderPage } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";

export const metadata: Metadata = { title: "Knowledge · Pre-Sales Agent" };

export default async function KnowledgePage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  return (
    <AppShell me={result.me}>
      <PlaceholderPage title="Knowledge" />
    </AppShell>
  );
}
