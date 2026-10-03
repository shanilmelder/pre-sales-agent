"use client";

import { XIcon } from "lucide-react";

import { RIGHT_PANE_ID, useShell } from "@/components/shell/shell-context";

/** The right-pane container (inspector or activity rail in later stories). Docked at
 * 1440px and wider; below that it overlays the main pane. */
export function RightPane() {
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  if (!rightPaneOpen) return null;
  return (
    <aside
      id={RIGHT_PANE_ID}
      aria-label="Details"
      className="absolute inset-y-0 right-0 z-10 flex w-inspector max-w-full shrink-0 flex-col border-l border-border bg-surface-inspector shadow-lg min-[1440px]:static min-[1440px]:shadow-none"
    >
      <div className="flex h-12 items-center justify-between border-b border-border px-gutter">
        <h2 className="text-section">Details</h2>
        <button
          type="button"
          aria-label="Close right pane"
          onClick={() => setRightPaneOpen(false)}
          className="flex size-7 items-center justify-center rounded-sm outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
        >
          <XIcon className="size-4" aria-hidden="true" />
        </button>
      </div>
      <p className="p-gutter text-muted-foreground">Nothing selected.</p>
    </aside>
  );
}
