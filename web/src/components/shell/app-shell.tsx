"use client";

import { PanelRightIcon } from "lucide-react";
import type { ReactNode } from "react";

import { CheatSheet } from "@/components/shell/cheat-sheet";
import { CommandPalette } from "@/components/shell/command-palette";
import { KeyboardShortcuts } from "@/components/shell/keyboard-shortcuts";
import { ReadOnlyNotice } from "@/components/shell/read-only-notice";
import { RightPane } from "@/components/shell/right-pane";
import { RIGHT_PANE_TOGGLE_ID, useShell } from "@/components/shell/shell-context";
import { Sidebar } from "@/components/shell/sidebar";
import type { Me } from "@/lib/api/server";

function RightPaneToggle() {
  const { rightPaneOpen, toggleRightPane } = useShell();
  return (
    <button
      id={RIGHT_PANE_TOGGLE_ID}
      type="button"
      aria-label="Right pane"
      aria-pressed={rightPaneOpen}
      title="Show or hide the right pane (])"
      onClick={toggleRightPane}
      className="flex size-7 items-center justify-center rounded-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-pressed:bg-muted"
    >
      <PanelRightIcon className="size-4" aria-hidden="true" />
    </button>
  );
}

/** The signed-in app shell: sidebar, main pane and right pane, plus the palette, cheat
 * sheet and global shortcuts. Its state and the live region come from `ShellProviders`
 * in the root layout, so they survive navigation. Render it only after the page's access
 * gate: it never decides who may see `children`. */
export function AppShell({ me, children }: { me: Me; children: ReactNode }) {
  return (
    <>
      <div className="flex h-dvh min-h-0 w-full overflow-hidden">
        <Sidebar me={me} />
        <div className="relative flex min-w-0 flex-1">
          <main className="flex min-w-0 flex-1 flex-col overflow-auto">
            <ReadOnlyNotice />
            <div className="flex h-12 shrink-0 items-center justify-end border-b border-border px-gutter">
              <RightPaneToggle />
            </div>
            <div className="flex flex-1 flex-col">{children}</div>
          </main>
          <RightPane />
        </div>
      </div>
      <CommandPalette roles={me.roles} />
      <CheatSheet />
      <KeyboardShortcuts />
    </>
  );
}

/** A page that isn't built yet: its title and "Not available yet." (or other text). */
export function PlaceholderPage({
  title,
  message = "Not available yet.",
}: {
  title: string;
  message?: string;
}) {
  return (
    <div className="flex flex-col gap-1 p-gutter">
      <h1 className="text-title">{title}</h1>
      <p className="text-muted-foreground">{message}</p>
    </div>
  );
}
