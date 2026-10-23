import { ChevronRightIcon, ClockIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { countdownLabel, daysUntil } from "@/lib/opportunities";

/** "All Opportunities > title": the title is the current item, truncated, not a link. */
export function Breadcrumb({ title }: { title: string }) {
  return (
    <nav aria-label="Breadcrumb" className="min-w-0 text-label text-muted-foreground">
      <ol className="flex min-w-0 items-center gap-1.5">
        <li className="shrink-0">
          <Link
            href="/opportunities"
            className="rounded-sm outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-primary"
          >
            All Opportunities
          </Link>
        </li>
        <li aria-hidden="true" className="shrink-0">
          <ChevronRightIcon className="size-3" />
        </li>
        <li aria-current="page" className="min-w-0 max-w-xl truncate text-foreground">
          {title}
        </li>
      </ol>
    </nav>
  );
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = Array.from(words[0])[0] ?? "";
  const last = words.length > 1 ? (Array.from(words[words.length - 1])[0] ?? "") : "";
  return (first + last).toUpperCase();
}

/** A person as a chip: initials avatar, name, and a visually hidden role prefix. */
export function PersonChip({ name, role }: { name: string; role: "Owner" | "Collaborator" }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border py-0.5 pr-2.5 pl-0.5 text-label text-foreground">
      <Avatar className="size-5">
        <AvatarFallback aria-hidden="true">{initials(name)}</AvatarFallback>
      </Avatar>
      <span className="min-w-0 max-w-64 truncate">
        <span className="sr-only">{role}: </span>
        {name}
      </span>
    </span>
  );
}

/** The days left (or overdue) to the proposal date, always an icon and text. Overdue takes
 * the blocker tone. `today` comes from the server so server and client agree. */
export function DueCountdown({ date, today }: { date: string; today: string }) {
  const days = daysUntil(date, today);
  if (Number.isNaN(days)) return null;
  const overdue = days < 0;
  const Icon = overdue ? TriangleAlertIcon : ClockIcon;
  return (
    <span
      className={`inline-flex items-center gap-1 text-label ${overdue ? "text-blocker" : "text-muted-foreground"}`}
    >
      <Icon className="size-3 shrink-0" aria-hidden="true" />
      {countdownLabel(days)}
    </span>
  );
}
