"use client";

import { Menu } from "@base-ui/react/menu";

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = Array.from(words[0])[0] ?? "";
  const last = words.length > 1 ? (Array.from(words[words.length - 1])[0] ?? "") : "";
  return (first + last).toUpperCase();
}

export function AvatarMenu({ name, email }: { name: string; email: string }) {
  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={`Account menu for ${name}`}
        className="flex size-8 items-center justify-center rounded-full bg-muted text-xs font-medium text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span aria-hidden="true">{initials(name)}</span>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner align="end" sideOffset={6}>
          <Menu.Popup className="min-w-56 rounded-lg border border-border bg-popover p-1 text-sm text-popover-foreground shadow-md outline-none">
            <div className="px-2 py-1.5">
              <p className="font-medium">{name}</p>
              <p className="text-xs text-muted-foreground">{email}</p>
            </div>
            <Menu.Separator className="my-1 h-px bg-border" />
            <Menu.LinkItem
              href="/settings"
              className="block rounded-md px-2 py-1.5 outline-none data-highlighted:bg-muted"
            >
              Settings
            </Menu.LinkItem>
            {/* A full navigation: /auth/logout ends the app session and the Auth0 session. */}
            <Menu.LinkItem
              href="/auth/logout"
              className="block rounded-md px-2 py-1.5 outline-none data-highlighted:bg-muted"
            >
              Sign out
            </Menu.LinkItem>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}
