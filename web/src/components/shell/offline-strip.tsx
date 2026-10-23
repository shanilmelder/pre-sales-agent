"use client";

import { WifiOffIcon } from "lucide-react";

import { useShell } from "@/components/shell/shell-context";
import { MAIN_ID } from "@/components/shell/skip-link";
import { Button } from "@/components/ui/button";

export const OFFLINE_MESSAGE = "Offline — edits disabled";

/** The shell's Offline strip (Story 17.2c): top of the main pane while the Opportunity
 * workspace's event stream has been down 60 s. Retry reopens the stream at once. A polite live
 * region that stays mounted, so the change is read out. */
export function OfflineStrip() {
  const { streamStatus, retryStream } = useShell();
  const offline = streamStatus === "offline";

  function retry() {
    retryStream?.();
    // The strip goes when the stream opens: keep focus in the pane meanwhile.
    document.getElementById(MAIN_ID)?.focus();
  }

  return (
    <div aria-live="polite" aria-atomic="true" data-testid="offline-strip">
      {offline ? (
        <div className="flex items-center gap-2 border-b border-border bg-muted px-page py-2 text-body">
          <WifiOffIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <span className="flex-1">{OFFLINE_MESSAGE}</span>
          <Button type="button" variant="outline" size="sm" onClick={retry}>
            Retry
          </Button>
        </div>
      ) : null}
    </div>
  );
}
