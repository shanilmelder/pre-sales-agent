"use client";

import { cn } from "cn";
import { MoonIcon, SunIcon } from "lucide-react";
import Link from "next/link";
import { useTransition } from "react";

import { savePreferences } from "@/app/settings/actions";
import { AvatarMenu } from "@/components/avatar-menu";
import { useAnnounce } from "@/components/shell/live-region";
import { useShell } from "@/components/shell/shell-context";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import type { Me } from "@/lib/api/server";
import { roleLabel } from "@/lib/roles";

const SAVE_FAILED = "Your settings could not be saved. Try again.";

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = Array.from(words[0])[0] ?? "";
  const last = words.length > 1 ? (Array.from(words[words.length - 1])[0] ?? "") : "";
  return (first + last).toUpperCase();
}

/** Sidebar footer: avatar (opens Settings), name and role, a Light/Dark toggle and the
 * account menu (Sign out). `collapsed` stacks the controls and keeps the text for screen
 * readers only. */
export function UserCard({
  me,
  collapsed,
}: {
  me: Pick<Me, "name" | "email" | "roles">;
  collapsed: boolean;
}) {
  const { density, singleKeyShortcuts } = useShell();
  const announce = useAnnounce();
  const [pending, startTransition] = useTransition();
  const role = me.roles[0] ? roleLabel(me.roles[0]) : "";

  function toggleTheme() {
    // Not `disabled`: a disabled button drops keyboard focus mid-save.
    if (pending) return;
    const root = document.documentElement;
    const wasDark = root.classList.contains("dark");
    const next = wasDark ? "light" : "dark";
    // Flip at once; the server re-render applies the saved value.
    root.classList.toggle("dark", !wasDark);
    startTransition(async () => {
      let ok = false;
      try {
        ok = (await savePreferences({ theme: next, density, singleKeyShortcuts })).ok;
      } catch {
        ok = false;
      }
      if (!ok) {
        root.classList.toggle("dark", wasDark);
        announce(SAVE_FAILED);
      }
    });
  }

  const text = collapsed ? "sr-only" : "sr-only min-[1280px]:not-sr-only";
  const wide = collapsed
    ? ""
    : "min-[1280px]:flex-row min-[1280px]:items-center min-[1280px]:gap-2.5 min-[1280px]:pl-1";

  return (
    <div
      data-testid="user-card"
      className={cn("mt-1 flex flex-col items-center gap-1.5 border-t border-border pt-2.5", wide)}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <Link
          href="/settings"
          aria-label="Open Settings"
          title="Open Settings"
          className="rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Avatar className="size-8 bg-primary-tint text-primary-text">
            <AvatarFallback aria-hidden="true" className="font-semibold">
              {initials(me.name)}
            </AvatarFallback>
          </Avatar>
        </Link>
        <div className={cn("min-w-0 flex-1", text)}>
          <p className="truncate text-[13px] leading-[1.3] font-medium">{me.name}</p>
          {role ? (
            <p className="truncate text-[12px] leading-[1.3] text-text-secondary">{role}</p>
          ) : null}
        </div>
      </div>
      <button
        type="button"
        aria-label="Toggle theme"
        title="Switch between light and dark"
        aria-disabled={pending}
        onClick={toggleTheme}
        className="flex size-[30px] shrink-0 items-center justify-center rounded-md border border-border bg-surface text-text-secondary outline-none hover:bg-surface-alt hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
      >
        <SunIcon className="hidden size-[15px] dark:block" aria-hidden="true" />
        <MoonIcon className="size-[15px] dark:hidden" aria-hidden="true" />
      </button>
      <AvatarMenu name={me.name} email={me.email} side="top" align="start" compact />
    </div>
  );
}
