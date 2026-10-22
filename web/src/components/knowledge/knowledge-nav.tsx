import Link from "next/link";

const TABS = [
  { id: "sources", label: "Sources", href: "/knowledge" },
  { id: "checklists", label: "Checklists", href: "/knowledge/checklists" },
] as const;

/** Knowledge's sub-tabs as links (the Coverage tab comes with Story 3.5). */
export function KnowledgeNav({ current }: { current: (typeof TABS)[number]["id"] }) {
  return (
    <nav aria-label="Knowledge sections" className="flex gap-4 border-b border-border px-gutter">
      {TABS.map((tab) => {
        const active = tab.id === current;
        return (
          <Link
            key={tab.id}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`-mb-px border-b-2 py-2 text-label outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              active
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
