import Link from "next/link";

import { cn } from "@/lib/utils";

const VIEWS = [
  { href: "/admin/agents", label: "Registry" },
  { href: "/admin/agents/denials", label: "Denied tool calls" },
] as const;

export type AgentsView = (typeof VIEWS)[number]["href"];

/** Admin → Agents' views as a segmented control (Story 7.4): the Registry and the Denied
 * tool calls, one link each, the current one marked (as `AdminNav`). */
export function AgentsSubnav({ current }: { current: AgentsView }) {
  return (
    <nav
      aria-label="Agents views"
      className="flex w-fit max-w-full flex-wrap items-center gap-0.5 rounded-[9px] bg-surface-alt p-[3px]"
    >
      {VIEWS.map((view) => (
        <Link
          key={view.href}
          href={view.href}
          aria-current={view.href === current ? "page" : undefined}
          className={`${cn(
            "rounded-[7px] px-3 py-[5px] outline-none focus-visible:ring-2 focus-visible:ring-primary",
            view.href === current
              ? "bg-surface text-foreground"
              : "text-text-secondary hover:text-foreground",
          )} text-control`}
        >
          {view.label}
        </Link>
      ))}
    </nav>
  );
}
