import { type OpportunityStatus, STATUSES } from "@/lib/opportunities";
import { cn } from "@/lib/utils";

/** An Opportunity's derived status (computed by the API, never here): always an icon and a
 * label, never colour alone. 20px, fully rounded, neutral outline; only the icon is tinted. */
export function StatusPill({ status }: { status: OpportunityStatus }) {
  const known = STATUSES[status];
  const Icon = known.icon;
  return (
    <span
      className="inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground"
    >
      <Icon className={cn("size-3 shrink-0", known.tone)} aria-hidden="true" />
      {known.label}
    </span>
  );
}
