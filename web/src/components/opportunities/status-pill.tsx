import { Pill } from "@/components/ui/pill";
import { type OpportunityStatus, STATUSES } from "@/lib/opportunities";
import { pillToneFor } from "@/lib/pill-tone";

/** An Opportunity's derived status (computed by the API, never here): always an icon and a
 * label, never colour alone. A tint-filled Pill in the status's tone. */
export function StatusPill({ status }: { status: OpportunityStatus }) {
  const known = STATUSES[status];
  const Icon = known.icon;
  return (
    <Pill tone={pillToneFor(known.tone)} icon={<Icon />} className="shrink-0">
      {known.label}
    </Pill>
  );
}
