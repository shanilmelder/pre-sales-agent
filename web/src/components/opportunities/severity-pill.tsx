import { severityInfo, type Severity } from "@/lib/red-team";
import { cn } from "@/lib/utils";

/** A Finding's severity: always an icon and a label, never colour alone. 20px, fully
 * rounded, neutral outline, like the status pill; only the icon is tinted (blocker red for
 * Critical, gap amber for High). */
export function SeverityPill({ severity }: { severity: Severity }) {
  const known = severityInfo(severity);
  const Icon = known.icon;
  return (
    <span
      data-severity={known.value}
      className="inline-flex h-5 w-[5.5rem] shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground"
    >
      <Icon className={cn("size-3 shrink-0", known.tone)} aria-hidden="true" />
      {known.label}
    </span>
  );
}
