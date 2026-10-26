import { QuoteIcon } from "lucide-react";

import { Chip } from "@/components/ui/chip";
import {
  OUTCOME_TONES,
  REVIEW_OUTCOMES_TITLE,
  outcomeRows,
  type ReviewEvidence,
  type ReviewPanel,
} from "@/lib/reviews";
import { cn } from "@/lib/utils";

/** An Evidence chip of a reply: the quote icon and its label (`R4`, `S1 · call.vtt`). */
export function ReplyEvidenceChip({ evidence }: { evidence: ReviewEvidence }) {
  return (
    <Chip data-reply-evidence={evidence.id}>
      <QuoteIcon aria-hidden="true" className="size-3 shrink-0" />
      {evidence.label}
    </Chip>
  );
}

/** The Review outcomes list (Story 9.4; the mockup review block's outcomes): a 12px uppercase
 * heading, then one row per decision and per reply, oldest first, each with its tone icon,
 * "**who** · what", the time and a note (a reason or the reply's message); a reply row lists
 * its Evidence chips. Nothing before the first decision. */
export function ReviewOutcomes({ panel }: { panel: Pick<ReviewPanel, "decisions" | "replies"> }) {
  const rows = outcomeRows(panel);
  if (rows.length === 0) return null;
  return (
    <section
      aria-label={REVIEW_OUTCOMES_TITLE}
      className="border-t border-border pt-3"
      data-review-outcomes=""
    >
      <h4 className="mb-2 text-[12px] leading-4 font-semibold tracking-[.04em] text-text-secondary uppercase">
        {REVIEW_OUTCOMES_TITLE}
      </h4>
      <ul className="flex flex-col">
        {rows.map((row) => {
          const tone = OUTCOME_TONES[row.tone];
          const Icon = tone.icon;
          return (
            <li key={row.id} className="flex items-start gap-2.5 py-2" data-outcome={row.tone}>
              <Icon aria-hidden="true" className={cn("mt-0.5 size-4 shrink-0", tone.className)} />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] leading-5">
                  <b className="font-semibold">{row.who}</b>
                  {` · ${row.what}`}
                </p>
                {row.when ? (
                  <p className="text-[12px] leading-4 text-text-secondary">{row.when}</p>
                ) : null}
                {row.note ? (
                  <p className="mt-0.5 text-[13px] leading-5 whitespace-pre-wrap break-words">
                    {row.note}
                  </p>
                ) : null}
                {row.evidence.length > 0 ? (
                  <ul aria-label="Evidence" className="mt-1 flex flex-wrap gap-1.5">
                    {row.evidence.map((e) => (
                      <li key={`${e.kind}-${e.id}-${e.version ?? ""}`}>
                        <ReplyEvidenceChip evidence={e} />
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
