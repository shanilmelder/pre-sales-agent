import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { SettingsForm } from "@/components/settings-form";
import { AppShell } from "@/components/shell/app-shell";
import { getMe } from "@/lib/api/server";
import { getPreferences } from "@/lib/preferences";

export const metadata: Metadata = { title: "Settings · Pre-Sales Agent" };

export default async function SettingsPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const preferences = await getPreferences();
  return (
    <AppShell me={result.me}>
      <div className="flex w-full max-w-xl flex-col p-gutter">
        <h1 className="text-title">Settings</h1>
        <p className="text-meta text-muted-foreground">Saved in this browser.</p>
        <SettingsForm initial={preferences} />
      </div>
    </AppShell>
  );
}
