import { ShieldAlertIcon } from "lucide-react";

const labelClass =
  "inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground";

/** "Mandatory": an icon and a label, never colour alone (UX-DR21). With `count`, how many
 * items are mandatory, e.g. "3 Mandatory". */
export function MandatoryLabel({ count }: { count?: number }) {
  return (
    <span data-label="mandatory" className={labelClass}>
      <ShieldAlertIcon aria-hidden="true" className="size-3 shrink-0 text-blocker" />
      {count === undefined ? "Mandatory" : `${count} Mandatory`}
    </span>
  );
}
