"use client";

import { ClipboardCheckIcon, ExternalLinkIcon, ShieldPlusIcon } from "lucide-react";
import Link from "next/link";
import { useId } from "react";

import { PaneLabel } from "@/components/opportunities/estimate-item-parts";
import { EvidenceList } from "@/components/opportunities/lineage-section";
import { buttonVariants } from "@/components/ui/button";
import type { FailedAssumption } from "@/lib/actuals";
import {
  failedKindLabel,
  assumptionTraceHref,
  failedAcceptedLabel,
  failedAssumptionText,
  OPEN_IN_TRACE,
} from "@/lib/estimates";

export const FAILED_ASSUMPTIONS = "Failed Assumptions";

/** The kind icon of a failed Assumption, as the Assumptions Register draws it. */
export function AssumptionKindIcon({ kind }: { kind: string }) {
  const Icon = kind === "contingency" ? ShieldPlusIcon : ClipboardCheckIcon;
  return <Icon aria-hidden="true" className="size-3.5 shrink-0 text-text-secondary" />;
}

/** Story 10.4: the Actual Inspector's read-only **Failed Assumptions** (every role): one row
 * per failed Assumption with its kind icon and "Condition · A{n}", the wording (a
 * Contingency's hours first), who accepted it and when, its Evidence chips, and **Open in
 * Trace** to the Assumption's trace. Nothing here edits. */
export function FailedAssumptionList({
  opportunityId,
  assumptions,
}: {
  opportunityId: string;
  assumptions: readonly FailedAssumption[];
}) {
  const id = useId();
  if (assumptions.length === 0) return null;
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2" data-failed-assumptions="">
      <PaneLabel>
        <span id={id}>{FAILED_ASSUMPTIONS}</span>
      </PaneLabel>
      <ul className="flex flex-col gap-3">
        {assumptions.map((a) => {
          const label = failedKindLabel(a.kind, a.position);
          return (
            <li
              key={a.assumption_id}
              className="flex flex-col gap-1 rounded-lg border border-border bg-background p-3"
              data-failed-assumption={a.assumption_id}
            >
              <p className="flex items-center gap-1.5 text-meta text-text-secondary">
                <AssumptionKindIcon kind={a.kind} />
                {label}
              </p>
              <p className="text-body break-words">{failedAssumptionText(a) || "Wording unavailable"}</p>
              <p className="text-meta text-text-secondary">{failedAcceptedLabel(a)}</p>
              {a.evidence && a.evidence.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  <EvidenceList opportunityId={opportunityId} evidence={a.evidence} />
                </div>
              ) : null}
              <Link
                href={assumptionTraceHref(opportunityId, a.assumption_id)}
                data-open-in-trace=""
                aria-label={`${OPEN_IN_TRACE}: ${label}`}
                className={`${buttonVariants({ variant: "outline", size: "sm" })} mt-1 w-fit text-control`}
              >
                <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
                {OPEN_IN_TRACE}
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
