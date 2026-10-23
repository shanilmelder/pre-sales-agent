import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "cn";

export type SegmentedNavItem = { href: string; label: ReactNode };

/** A pill-shaped track of links with the current one raised: the sub-navigation of a page.
 * The current item is bold as well as raised, never colour alone. */
export function SegmentedNav({
  label,
  items,
  current,
  className,
}: {
  label: string;
  items: readonly SegmentedNavItem[];
  /** The `href` of the current item. */
  current: string;
  className?: string;
}) {
  return (
    <nav aria-label={label} className={cn("px-gutter", className)}>
      <div className="inline-flex gap-1 rounded-full bg-muted p-1">
        {items.map((item) => {
          const isCurrent = item.href === current;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isCurrent ? "page" : undefined}
              className={`${cn(
                "rounded-full px-3 py-1 outline-none focus-visible:ring-2 focus-visible:ring-primary",
                isCurrent
                  ? "bg-surface text-foreground shadow-card"
                  : "text-muted-foreground hover:text-foreground",
              )} ${isCurrent ? "text-body-strong" : "text-label"}`}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
