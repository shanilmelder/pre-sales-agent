import Link from "next/link";

import { MY_OPPORTUNITIES_HREF } from "@/lib/navigation";
import { cn } from "@/lib/utils";

export type OpportunityView = "all" | "mine" | "due";

/** The views as a segmented control. Where each view goes; `dueHref` carries the Due range
 * (today to today plus 14, UTC). */
export function OpportunityViews({
  current,
  dueHref,
}: {
  current: OpportunityView;
  dueHref: string;
}) {
  const views: { id: OpportunityView; label: string; href: string }[] = [
    { id: "all", label: "All", href: "/opportunities" },
    { id: "mine", label: "Mine", href: MY_OPPORTUNITIES_HREF },
    { id: "due", label: "Due in 14 days", href: dueHref },
  ];
  return (
    <nav
      aria-label="Views"
      className="flex items-center gap-0.5 rounded-[9px] bg-surface-alt p-[3px]"
    >
      {views.map((view) => (
        <Link
          key={view.id}
          href={view.href}
          aria-current={view.id === current ? "page" : undefined}
          className={`${cn(
            "rounded-[7px] px-3 py-[5px] outline-none focus-visible:ring-2 focus-visible:ring-primary",
            view.id === current
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
