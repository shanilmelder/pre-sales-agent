"use client";

import type { ReactNode } from "react";

import { CheatSheet } from "@/components/shell/cheat-sheet";
import { CommandPalette } from "@/components/shell/command-palette";
import { KeyboardShortcuts } from "@/components/shell/keyboard-shortcuts";
import { OfflineStrip } from "@/components/shell/offline-strip";
import { PageContent, PageHeader } from "@/components/shell/page-header";
import { ReadOnlyNotice } from "@/components/shell/read-only-notice";
import { ShortcutHint } from "@/components/shell/shortcut-hint";
import { RightPane } from "@/components/shell/right-pane";
import { ScreenAnnouncer } from "@/components/shell/screen-announcer";
import { MAIN_ID, SkipLink } from "@/components/shell/skip-link";
import { Sidebar } from "@/components/shell/sidebar";
import type { Me } from "@/lib/api/server";

export { RightPaneToggle } from "@/components/shell/right-pane-toggle";

/** The signed-in app shell: sidebar, main pane and right pane, plus the palette, cheat
 * sheet and global shortcuts. Its state and the live region come from `ShellProviders`
 * in the root layout, so they survive navigation. Render it only after the page's access
 * gate: it never decides who may see `children`. There is no top bar: each page renders its
 * own header band (`PageHeader`, or the Opportunity workspace header) with the right-pane
 * toggle in it. */
export function AppShell({ me, children }: { me: Me; children: ReactNode }) {
  return (
    <>
      <SkipLink />
      <ScreenAnnouncer />
      <div className="flex h-dvh min-h-0 w-full overflow-hidden">
        <Sidebar me={me} />
        <div className="relative flex min-w-0 flex-1">
          <main
            id={MAIN_ID}
            tabIndex={-1}
            className="flex min-w-0 flex-1 flex-col overflow-auto outline-none"
          >
            <ShortcutHint />
            <OfflineStrip />
            <ReadOnlyNotice />
            <div className="flex flex-1 flex-col bg-background">{children}</div>
          </main>
          <RightPane />
        </div>
      </div>
      <CommandPalette permissions={me.permissions} />
      <CheatSheet permissions={me.permissions} />
      <KeyboardShortcuts permissions={me.permissions} />
    </>
  );
}

/** A page that isn't built yet: its header band and "Not available yet." (or other text). */
export function PlaceholderPage({
  title,
  subtitle,
  message = "Not available yet.",
}: {
  title: string;
  subtitle?: string;
  message?: string;
}) {
  return (
    <>
      <PageHeader title={title} subtitle={subtitle} />
      <PageContent>
        <p className="text-muted-foreground">{message}</p>
      </PageContent>
    </>
  );
}
