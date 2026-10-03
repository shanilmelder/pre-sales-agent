"use client";

import { SettingsIcon } from "lucide-react";
import { useRouter } from "next/navigation";

import { useShell } from "@/components/shell/shell-context";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import type { Role } from "@/lib/navigation";
import { visibleNav } from "@/lib/navigation";

/** ⌘K/Ctrl+K: navigation commands (Admin only for admins) and Settings, fuzzy-filtered. */
export function CommandPalette({ roles }: { roles: readonly Role[] }) {
  const router = useRouter();
  const { dialog, openDialog, closeDialog } = useShell();

  function go(href: string) {
    closeDialog();
    router.push(href);
  }

  return (
    <CommandDialog
      open={dialog === "palette"}
      onOpenChange={(open) => (open ? openDialog("palette") : closeDialog())}
      title="Command palette"
      description="Search for a page or command, then press Enter."
      showCloseButton
      // Room for the close button beside the search field.
      className="[&_[data-slot=command-input-wrapper]]:pr-10"
    >
      <Command label="Command palette" loop>
        <CommandInput placeholder="Type a command or search" />
        <CommandList>
          <CommandEmpty>No matching commands.</CommandEmpty>
          <CommandGroup heading="Go to">
            {visibleNav(roles).map((item) => {
              const Icon = item.icon;
              return (
                <CommandItem key={item.id} value={item.label} onSelect={() => go(item.href)}>
                  <Icon aria-hidden="true" />
                  {item.label}
                </CommandItem>
              );
            })}
          </CommandGroup>
          <CommandGroup heading="Account">
            <CommandItem value="Settings" onSelect={() => go("/settings")}>
              <SettingsIcon aria-hidden="true" />
              Settings
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
