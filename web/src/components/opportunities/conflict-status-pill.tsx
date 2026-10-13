import { statusInfo, type ConflictStatus } from "@/lib/conflicts";
import { cn } from "@/lib/utils";

/** A Conflict's status: always an icon and a label, never colour alone. 20px, fully
 * rounded, neutral outline; only the icon is tinted (blocker red for Open, an arrow-up for
 * Escalated). */
export function ConflictStatusPill({ status }: { status: ConflictStatus }) {
  const known = statusInfo(status);
  const Icon = known.icon;
  return (
    <span
      data-status={known.value}
      className="inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground"
    >
      <Icon className={cn("size-3 shrink-0", known.tone)} aria-hidden="true" />
      {known.label}
    </span>
  );
}
