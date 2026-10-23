"use client";

import { cn } from "cn";
import { PanelRightIcon } from "lucide-react";

import { RIGHT_PANE_TOGGLE_ID, useShell } from "@/components/shell/shell-context";

/** Shows or hides the right pane (`]` does the same). It sits in each page's header band:
 * 34px on plain pages (`size="default"`), 28px on the Opportunity breadcrumb row
 * (`size="compact"`). Keep one per page: `Esc` returns focus to it by id. */
export function RightPaneToggle({ size = "default" }: { size?: "default" | "compact" }) {
  const { rightPaneOpen, toggleRightPane } = useShell();
  return (
    <button
      id={RIGHT_PANE_TOGGLE_ID}
      type="button"
      aria-label="Right pane"
      aria-pressed={rightPaneOpen}
      title="Show or hide the right pane (])"
      onClick={toggleRightPane}
      data-size={size}
      className={cn(
        "flex shrink-0 items-center justify-center rounded-md border border-border bg-surface text-text-secondary outline-none hover:bg-surface-alt hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary aria-pressed:bg-primary-tint aria-pressed:text-primary-text",
        size === "compact" ? "size-7" : "size-[34px]",
      )}
    >
      <PanelRightIcon className="size-[15px]" aria-hidden="true" />
    </button>
  );
}
