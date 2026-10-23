import { impactLabel, impactLevel, impactTone, type Impact } from "@/lib/gaps";

const LIT: Record<ReturnType<typeof impactTone>, string> = {
  "text-blocker": "bg-blocker",
  "text-gap": "bg-gap",
  "text-neutral": "bg-neutral",
};

/** A Gap's impact: its label and a 3-segment bar (High fills 3, Medium 2, Low 1). The bar
 * repeats the label, so it is hidden from assistive technology. By default it is neutral and
 * no colour is used to rank; `coloured` (the Gaps tab) tints the lit bars and the label by
 * impact (High blocker, Medium gap, Low neutral) on `border-strong` unlit bars. */
export function ImpactBar({ impact, coloured = false }: { impact: Impact; coloured?: boolean }) {
  const level = impactLevel(impact);
  const tone = impactTone(impact);
  const lit = coloured ? LIT[tone] : "bg-foreground";
  const unlit = coloured ? "bg-border-strong" : "bg-border";
  const heights = coloured ? ["h-1.5", "h-2.5", "h-3.5"] : ["h-1.5", "h-2", "h-2.5"];
  return (
    <span
      className={`inline-flex shrink-0 items-center ${coloured ? "gap-2" : "gap-1.5"}`}
      data-impact={impact}
    >
      <span
        aria-hidden="true"
        data-testid="impact-bar"
        className={`inline-flex items-end ${coloured ? "gap-0.5" : "gap-px"}`}
      >
        {[1, 2, 3].map((segment) => (
          <span
            key={segment}
            data-filled={segment <= level ? "" : undefined}
            className={`w-1 rounded-[1px] ${heights[segment - 1]} ${
              segment <= level ? lit : unlit
            }`}
          />
        ))}
      </span>
      <span className={coloured ? `text-control ${tone}` : "w-12 text-label text-foreground"}>
        {impactLabel(impact)}
      </span>
    </span>
  );
}
