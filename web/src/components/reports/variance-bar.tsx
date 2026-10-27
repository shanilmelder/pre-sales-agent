import { barClass, toneClass, type ReportVariance } from "@/lib/reports";
import { cn } from "@/lib/utils";

/** The diverging variance bar: an 8px track centred at 50 % with a tick, the server's fill
 * (`bar_left`, `bar_width`) and the signed figure, with "over"/"under" for screen readers so
 * colour never carries the meaning alone. */
export function VarianceBar({ variance }: { variance: ReportVariance }) {
  return (
    <div className="flex items-center gap-2.5" data-tone={variance.tone}>
      <div aria-hidden="true" className="relative h-2 flex-1 rounded-[4px] bg-surface-alt">
        <div
          data-testid="variance-fill"
          className={cn("absolute top-0 h-2 rounded-[4px]", barClass(variance))}
          style={{ left: `${variance.bar_left}%`, width: `${variance.bar_width}%` }}
        />
        <div className="absolute top-[-2px] left-1/2 h-3 w-px bg-border-strong" />
      </div>
      <span
        className={cn("w-16 text-right font-semibold text-numeric", toneClass(variance))}
        data-testid="variance-figure"
      >
        {variance.display}
        <span className="sr-only">{` ${variance.sr_label}`}</span>
      </span>
    </div>
  );
}
