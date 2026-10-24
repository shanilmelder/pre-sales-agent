import Link from "next/link";

import { CHECKLISTS_HREF, COVERAGE_HREF, SOURCES_HREF } from "@/lib/coverage";
import { cn } from "@/lib/utils";

/** Knowledge's sub-tabs, in order (the Graph tab comes with Story 3.6). */
export const KNOWLEDGE_TABS = [
  { id: "sources", label: "Sources", href: SOURCES_HREF },
  { id: "checklists", label: "Checklists", href: CHECKLISTS_HREF },
  { id: "coverage", label: "Coverage", href: COVERAGE_HREF },
] as const;

export type KnowledgeTab = (typeof KNOWLEDGE_TABS)[number]["id"];

/** Knowledge's sub-tabs as links, in the mockup's segmented track. */
export function KnowledgeNav({ current }: { current: KnowledgeTab }) {
  return (
    <nav
      aria-label="Knowledge sections"
      className="flex items-center gap-0.5 self-start rounded-[9px] bg-surface-alt p-[3px]"
    >
      {KNOWLEDGE_TABS.map((tab) => (
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
