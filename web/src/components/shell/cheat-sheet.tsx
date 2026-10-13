"use client";

import { Fragment } from "react";

import { useModKeyLabel } from "@/components/shell/keyboard-shortcuts";
import { useShell } from "@/components/shell/shell-context";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Permission } from "@/lib/navigation";
import { shortcutsFor } from "@/lib/shortcuts";

/** `?`: every shortcut the key handler implements for this user, from the shared
 * definition. */
export function CheatSheet({ permissions }: { permissions: readonly Permission[] }) {
  const { dialog, openDialog, closeDialog, singleKeyShortcuts } = useShell();
  const modKey = useModKeyLabel();

  return (
    <Dialog
      open={dialog === "cheat-sheet"}
      onOpenChange={(open) => (open ? openDialog("cheat-sheet") : closeDialog())}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>
            {singleKeyShortcuts
              ? "Shortcuts don't run while you are typing in a field."
              : "Single-key shortcuts are off. Turn them on in Settings."}
          </DialogDescription>
        </DialogHeader>
        <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5">
          {shortcutsFor(permissions).map((shortcut) => (
            <Fragment key={shortcut.id}>
              <dt
                className={
                  shortcut.singleKey && !singleKeyShortcuts ? "text-muted-foreground" : undefined
                }
              >
                {shortcut.description}
              </dt>
              <dd className="flex items-center justify-end gap-1">
                {shortcut.keys.map((key, index) => (
                  <Fragment key={index}>
                    {shortcut.match.kind === "sequence" && index > 0 ? (
                      <span className="text-meta text-muted-foreground">then</span>
                    ) : null}
                    <kbd className="min-w-5 rounded-sm border border-border px-1 text-center font-sans text-label">
                      {key === "Mod" ? modKey : key}
                    </kbd>
                  </Fragment>
                ))}
              </dd>
            </Fragment>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  );
}
