import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { SettingsForm } from "@/components/settings-form";
import { AppShell } from "@/components/shell/app-shell";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import { getMe } from "@/lib/api/server";
import { getPreferences } from "@/lib/preferences";

export const metadata: Metadata = { title: "Settings · Pre Sales Agent Framework" };

export default async function SettingsPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const preferences = await getPreferences();
  return (
    <AppShell me={result.me}>
      <PageHeader title="Settings" subtitle={PAGE_SUBTITLES.settings} />
      <PageContent>
        <SettingsForm initial={preferences} />
      </PageContent>
    </AppShell>
  );
}
