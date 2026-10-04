import { impactLabel, impactLevel, type Impact } from "@/lib/gaps";

/** A Gap's impact: its label and a neutral 3-segment bar (High fills 3, Medium 2, Low 1).
 * The bar repeats the label, so it is hidden from assistive technology; no colour is used
 * to rank. */
export function ImpactBar({ impact }: { impact: Impact }) {
  const level = impactLevel(impact);
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5" data-impact={impact}>
      <span aria-hidden="true" data-testid="impact-bar" className="inline-flex items-end gap-px">
        {[1, 2, 3].map((segment) => (
          <span
            key={segment}
            data-filled={segment <= level ? "" : undefined}
            className={`w-1 rounded-[1px] ${segment === 1 ? "h-1.5" : segment === 2 ? "h-2" : "h-2.5"} ${
              segment <= level ? "bg-foreground" : "bg-border"
            }`}
          />
        ))}
      </span>
      <span className="w-12 text-label text-foreground">{impactLabel(impact)}</span>
    </span>
  );
}
