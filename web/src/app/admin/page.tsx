import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { AppShell } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";
import { isAdmin } from "@/lib/navigation";

export const metadata: Metadata = { title: "Admin · Pre-Sales Agent" };

/** Administrators go straight to the first section, Users & roles (Catalogue is next to it). */
export default async function AdminPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  if (isAdmin(result.me.roles)) redirect("/admin/users");

  return (
    <AppShell me={result.me}>
      <div className="p-gutter">
        <p>You don&apos;t have access to this page</p>
      </div>
    </AppShell>
  );
}
