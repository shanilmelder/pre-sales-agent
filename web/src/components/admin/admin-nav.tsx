import Link from "next/link";

import { cn } from "@/lib/utils";

const SECTIONS = [
  { href: "/admin/users", label: "Users and roles" },
  { href: "/admin/agents", label: "Agents" },
  { href: "/admin/catalogue", label: "Catalogue" },
  { href: "/admin/evals", label: "Evals" },
] as const;

export type AdminSection = (typeof SECTIONS)[number]["href"];

/** Admin's sub-navigation as a segmented control: one link per section, the current one
 * marked. */
export function AdminNav({ current }: { current: AdminSection }) {
  return (
    <nav
      aria-label="Admin sections"
      className="flex w-fit max-w-full flex-wrap items-center gap-0.5 rounded-[9px] bg-surface-alt p-[3px]"
    >
      {SECTIONS.map((section) => (
        <Link
          key={section.href}
          href={section.href}
          aria-current={section.href === current ? "page" : undefined}
          className={`${cn(
            "rounded-[7px] px-3 py-[5px] outline-none focus-visible:ring-2 focus-visible:ring-primary",
            section.href === current
              ? "bg-surface text-foreground"
              : "text-text-secondary hover:text-foreground",
          )} text-control`}
        >
          {section.label}
        </Link>
      ))}
    </nav>
  );
}
