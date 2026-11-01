import Link from "next/link";

import { cn } from "@/lib/utils";

const VIEWS = [
  { href: "/admin/model-profiles", label: "Profiles" },
  { href: "/admin/model-profiles/approved", label: "Approved models" },
] as const;

export type ModelProfileView = (typeof VIEWS)[number]["href"];

/** Admin → Model profiles' views as a segmented control: the profiles and the approved-model
 * allowlist, one link each, the current one marked (as `AgentsSubnav`). */
export function ModelProfileSubnav({ current }: { current: ModelProfileView }) {
  return (
    <nav
      aria-label="Model profile views"
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
