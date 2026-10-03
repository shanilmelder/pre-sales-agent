import { type OpportunityStatus, STATUSES } from "@/lib/opportunities";

/** An Opportunity's derived status: always an icon and a label, never colour alone. */
export function StatusPill({ status }: { status: OpportunityStatus }) {
  const known = STATUSES[status];
  const Icon = known.icon;
  return (
    <span className="inline-flex h-5 items-center gap-1 rounded-sm border border-border px-1.5 text-label">
      <Icon className="size-3.5 shrink-0" aria-hidden="true" />
      {known.label}
    </span>
  );
}
