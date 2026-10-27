import Link from "next/link";

import { REPORT_TABS, type ReportTab } from "@/lib/reports";
import { cn } from "@/lib/utils";

/** Reports' sub-tabs as links, in the mockup's segmented pill track. */
export function ReportsNav({ current }: { current: ReportTab }) {
  return (
    <nav
      aria-label="Report sections"
      className="flex items-center gap-0.5 self-start rounded-[9px] bg-surface-alt p-[3px]"
    >
      {REPORT_TABS.map((tab) => (
        <Link
          key={tab.id}
          href={tab.href}
          aria-current={tab.id === current ? "page" : undefined}
          className={`${cn(
            "rounded-[7px] px-3.5 py-[5px] outline-none focus-visible:ring-2 focus-visible:ring-primary",
            tab.id === current
              ? "bg-surface text-foreground"
              : "text-text-secondary hover:text-foreground",
          )} text-control`}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
