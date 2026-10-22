"use client";

import { KeyboardIcon } from "lucide-react";
import { useTransition } from "react";

import { savePreferences } from "@/app/settings/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { useShell } from "@/components/shell/shell-context";
import { Button } from "@/components/ui/button";
// Types only: the preferences module imports next/headers.
import type { Preferences } from "@/lib/preferences";

// The defaults of a browser with no cookie, apart from the shortcut choice.
const BASE: Omit<Preferences, "singleKeyShortcuts"> = { theme: "system", density: "comfortable" };
const SAVE_FAILED = "Your settings could not be saved. Try again.";

/** First-run strip: single-key shortcuts start Off (WCAG 2.1.4). Either answer saves the
 * preferences cookie, which is what ends the first run. Renders nothing once answered. */
export function ShortcutHint() {
  const { firstRun, dismissFirstRun } = useShell();
  const announce = useAnnounce();
  const [pending, startTransition] = useTransition();
  if (!firstRun) return null;

  function answer(singleKeyShortcuts: boolean) {
    startTransition(async () => {
      let ok = false;
      try {
        ok = (await savePreferences({ ...BASE, singleKeyShortcuts })).ok;
      } catch {
        ok = false;
      }
      if (ok) dismissFirstRun();
      else announce(SAVE_FAILED);
    });
  }

  return (
    <section
      aria-label="Keyboard shortcuts"
      data-testid="shortcut-hint"
      className="flex flex-wrap items-center gap-3 border-b border-border bg-primary-tint px-gutter py-2.5"
    >
      <KeyboardIcon className="size-4 shrink-0 text-primary-text" aria-hidden="true" />
      <p className="min-w-0 flex-1 text-body">
        Single-key shortcuts such as c to create and j or k to move are off. Turn them on here,
        or later in Settings. Ctrl+K works either way.
      </p>
      <Button type="button" disabled={pending} onClick={() => answer(true)}>
        Turn on
      </Button>
      <Button type="button" variant="outline" disabled={pending} onClick={() => answer(false)}>
        Dismiss
      </Button>
    </section>
  );
}
