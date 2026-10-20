"use client";

import { WifiOffIcon } from "lucide-react";

import type { StreamStatus } from "@/lib/opportunity-events";

export const RECONNECTING = "Reconnecting…";
export const OFFLINE = "Offline — edits disabled";

/** The sentence for a connection state; null while connected (or still connecting). */
export function connectionMessage(status: StreamStatus): string | null {
  switch (status) {
    case "reconnecting":
      return RECONNECTING;
    case "offline":
      return OFFLINE;
    default:
      return null;
  }
}

/** The workspace's slim status bar (Story 2.3): shown only while the Opportunity's event
 * stream is down, "Reconnecting…" from the first drop and "Offline — edits disabled" after
 * 60 s. A polite live region (no toast): the region stays mounted so each change is read
 * out, and it is empty while connected. */
export function ConnectionStatus({ status }: { status: StreamStatus }) {
  const message = connectionMessage(status);
  return (
    <div role="status" aria-live="polite" data-testid="connection-status">
      {message ? (
        <p
          data-status={status}
          className="flex h-6 shrink-0 items-center gap-1.5 border-t border-border bg-muted px-gutter text-label text-foreground"
        >
          <WifiOffIcon aria-hidden="true" className="size-3 shrink-0 text-muted-foreground" />
          {message}
        </p>
      ) : null}
    </div>
  );
}
