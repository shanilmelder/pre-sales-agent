import { Pill } from "@/components/ui/pill";
import { pillToneFor } from "@/lib/pill-tone";
import { severityInfo, type Severity } from "@/lib/red-team";

/** A Finding's severity: always an icon and a label, never colour alone. A tint-filled Pill
 * (blocker for Critical, gap for High). */
export function SeverityPill({ severity }: { severity: Severity }) {
  const known = severityInfo(severity);
  const Icon = known.icon;
  return (
    <Pill
      data-severity={known.value}
      tone={pillToneFor(known.tone)}
      icon={<Icon />}
      className="w-[5.5rem] shrink-0"
    >
      {known.label}
    </Pill>
  );
}
