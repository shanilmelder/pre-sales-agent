import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AppShell, PlaceholderPage } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";
import { isAdmin } from "@/lib/navigation";

export const metadata: Metadata = { title: "Admin · Pre-Sales Agent" };

export default async function AdminPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  return (
    <AppShell me={result.me}>
      {isAdmin(result.me.roles) ? (
        <PlaceholderPage title="Admin" />
      ) : (
        <div className="p-gutter">
          <p>You don&apos;t have access to this page</p>
        </div>
      )}
    </AppShell>
  );
}
