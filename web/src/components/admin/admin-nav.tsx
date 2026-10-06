import Link from "next/link";

const SECTIONS = [
  { href: "/admin/users", label: "Users & roles" },
  { href: "/admin/catalogue", label: "Catalogue" },
] as const;

/** Admin's sub-navigation: the sections side by side, the current one marked. */
export function AdminNav({ current }: { current: (typeof SECTIONS)[number]["href"] }) {
  return (
    <nav aria-label="Admin sections" className="flex gap-4 border-b border-border px-gutter">
      {SECTIONS.map((section) => (
        <Link
          key={section.href}
          href={section.href}
          aria-current={section.href === current ? "page" : undefined}
          className={`-mb-px border-b-2 py-2 text-label outline-none focus-visible:ring-2 focus-visible:ring-primary ${
            section.href === current
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground"
          }`}
        >
          {section.label}
        </Link>
      ))}
    </nav>
  );
}
