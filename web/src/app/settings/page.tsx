import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { SettingsForm } from "@/components/settings-form";
import { AppShell } from "@/components/shell/app-shell";
import { PageHeader } from "@/components/shell/page-header";
import { getMe } from "@/lib/api/server";
import { getPreferences } from "@/lib/preferences";

export const metadata: Metadata = { title: "Settings · Pre Sales Agent Framework" };

export default async function SettingsPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const preferences = await getPreferences();
  return (
    <AppShell me={result.me}>
      <div className="flex w-full flex-col">
        <PageHeader title="Settings" subtitle="Theme, density and keyboard shortcuts." />
        <div className="px-gutter pb-gutter">
          <SettingsForm initial={preferences} />
        </div>
      </div>
    </AppShell>
  );
}
