"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { DISABLE_EFFECT, ENABLE_EFFECT } from "@/lib/admin";

/** **Disable** (an enabled Agent) or **Enable** (any other), confirmed first in a dialog that
 * states the effect (Story 7.3). Focus goes back to the button when the dialog closes. */
export function AgentStatusDialog({
  agentName,
  enabled,
  busy = false,
  onConfirm,
}: {
  agentName: string;
  /** The Agent is `active` now, so the action disables it. */
  enabled: boolean;
  /** A write is in flight. */
  busy?: boolean;
  onConfirm: () => void;
}) {
  const [open, setOpen] = useState(false);
  const action = enabled ? "Disable" : "Enable";
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        disabled={busy}
        render={<Button type="button" variant="outline" size="sm" />}
      >
        {action}
      </DialogTrigger>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{`${action} ${agentName}?`}</DialogTitle>
          <DialogDescription>{enabled ? DISABLE_EFFECT : ENABLE_EFFECT}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button
            variant={enabled ? "destructive" : "default"}
            disabled={busy}
            onClick={() => {
              setOpen(false);
              onConfirm();
            }}
          >
            {action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
