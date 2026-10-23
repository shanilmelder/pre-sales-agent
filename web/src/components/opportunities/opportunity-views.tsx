import Link from "next/link";

import { MY_OPPORTUNITIES_HREF } from "@/lib/navigation";
import { cn } from "@/lib/utils";

export type OpportunityView = "all" | "mine" | "due";

/** Where each view goes; `dueHref` carries the Due range (today to today plus 14, UTC). */
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
    <nav aria-label="Views" className="flex items-center gap-1 border-b border-border">
      {views.map((view) => (
        <Link
          key={view.id}
          href={view.href}
          aria-current={view.id === current ? "page" : undefined}
          className={`${cn(
            "-mb-px rounded-sm border-b-2 px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-primary",
            view.id === current
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )} text-label`}
        >
          {view.label}
        </Link>
      ))}
    </nav>
  );
}
