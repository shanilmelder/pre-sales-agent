"use client";

import { PlusIcon, SettingsIcon } from "lucide-react";
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
import { canCreateOpportunity, NEW_OPPORTUNITY_HREF } from "@/lib/shortcuts";

/** ⌘K/Ctrl+K: navigation commands (Admin only for admins), New Opportunity (presales
 * engineers only) and Settings, fuzzy-filtered. */
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
          {canCreateOpportunity(roles) ? (
            <CommandGroup heading="Create">
              <CommandItem value="New Opportunity" onSelect={() => go(NEW_OPPORTUNITY_HREF)}>
                <PlusIcon aria-hidden="true" />
                New Opportunity
              </CommandItem>
            </CommandGroup>
          ) : null}
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
