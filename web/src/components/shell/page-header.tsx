import type { ReactNode } from "react";

import { RightPaneToggle } from "@/components/shell/right-pane-toggle";

/** The header band on every shell page except the Opportunity workspace: the page's h1, a
 * subtitle, an optional primary action, then the right-pane toggle. */
export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: ReactNode;
  /** The page's primary action (a link or button), shown before the pane toggle. */
  action?: ReactNode;
}) {
  return (
    <header
      data-testid="page-header"
      className="flex shrink-0 items-center gap-4 border-b border-border bg-surface px-page pt-7 pb-5"
    >
      <div className="min-w-0 flex-1">
        <h1 className="text-title">{title}</h1>
        {subtitle ? (
          <div className="mt-0.5 text-[13px] leading-[1.5] text-text-secondary">{subtitle}</div>
        ) : null}
      </div>
      {action}
      <RightPaneToggle />
    </header>
  );
}

/** The page frame's padding: 28px top, 32px sides, 40px bottom. `PageContent` and the
 * Opportunity workspace's tab wrappers use it. */
export const PAGE_PADDING = "px-page pt-7 pb-10";

/** The content area under a `PageHeader`: `PAGE_PADDING`, sections 24px apart. */
export function PageContent({ children }: { children: ReactNode }) {
  return (
    <div data-testid="page-content" className={`flex flex-col gap-6 ${PAGE_PADDING}`}>
      {children}
    </div>
  );
}

/** The mockup's header subtitles. */
export const PAGE_SUBTITLES = {
  opportunities: "Opportunities with their derived status, open items and current Estimate.",
  newOpportunity: "Create the Opportunity, then add Sources.",
  inbox: "Review requests and notifications.",
  knowledge: "Knowledge Sources, Checklists and coverage.",
  reports: "Estimate accuracy, pipeline and cost across Opportunities.",
  admin: "Users, agents, catalogue and evaluations.",
  settings: "Saved in this browser.",
} as const;
