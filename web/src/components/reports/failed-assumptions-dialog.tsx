"use client";

import { ExternalLinkIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { loadFailedAssumptions, type FailedListResult } from "@/app/reports/actions";
import { AssumptionKindIcon } from "@/components/opportunities/failed-assumption-list";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  failedKindLabel,
  assumptionTraceHref,
  failedAssumptionText,
  OPEN_IN_TRACE,
} from "@/lib/estimates";
import {
  FAILED_LIST_EMPTY,
  FAILED_LIST_FAILED,
  LOADING_FAILED_LIST,
  failedCount,
  failedDialogTitle,
  reportHref,
  type GroupBy,
  type ReportParams,
  type VarianceGroup,
} from "@/lib/reports";

/** Story 10.4: a group's "N failed Assumptions" as a link-styled button opening the group's
 * list in a Dialog ("Failed Assumptions · {group}"): one item per failed Assumption with its
 * kind icon, "A{n}", wording, the Opportunity and line, and a link to that Opportunity's
 * Trace filtered to the Assumption. With none, the count stays text. */
export function FailedAssumptionsButton({
  group,
  groupBy,
  params,
}: {
  group: Pick<VarianceGroup, "key" | "label" | "failed_assumptions">;
  groupBy: GroupBy;
  params: ReportParams;
}) {
  const [open, setOpen] = useState(false);
  const text = failedCount(group);
  if (group.failed_assumptions === 0) return <span>{text}</span>;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-label={`${text} in ${group.label}: show them`}
        className="rounded text-link underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
      >
        {text}
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[560px] max-w-[calc(100vw-32px)]">
          <DialogHeader>
            <DialogTitle className="text-[20px] leading-7 font-semibold">
              {failedDialogTitle(group.label)}
            </DialogTitle>
            <DialogDescription>{`${text}, under the report's filters.`}</DialogDescription>
          </DialogHeader>
          {open ? <FailedList groupKey={group.key} groupBy={groupBy} params={params} /> : null}
        </DialogContent>
      </Dialog>
    </>
  );
}

function FailedList({
  groupKey,
  groupBy,
  params,
}: {
  groupKey: string;
  groupBy: GroupBy;
  params: ReportParams;
}) {
  const search = reportHref(params).split("?")[1] ?? "";
  const [result, setResult] = useState<FailedListResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let loaded: FailedListResult;
      try {
        loaded = await loadFailedAssumptions(search, groupBy, groupKey);
      } catch {
        loaded = { kind: "error" };
      }
      if (!cancelled) setResult(loaded);
    })();
    return () => {
      cancelled = true;
    };
  }, [search, groupBy, groupKey]);

  if (result === null) {
    return (
      <div aria-busy="true" className="flex flex-col gap-2" data-failed-list-loading="">
        <p className="sr-only">{LOADING_FAILED_LIST}</p>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    );
  }
  if (result.kind !== "ok") {
    return <p className="text-meta text-text-secondary">{FAILED_LIST_FAILED}</p>;
  }
  if (result.list.items.length === 0) {
    return <p className="text-meta text-text-secondary">{FAILED_LIST_EMPTY}</p>;
  }
  return (
    <ul className="flex max-h-[60vh] flex-col divide-y divide-border overflow-y-auto" data-failed-list="">
      {result.list.items.map((item) => {
        const kind = item.kind ?? "condition";
        const label = failedKindLabel(kind, item.position);
        return (
          <li
            key={item.assumption_id}
            className="flex flex-col gap-1 py-3"
            data-failed-item={item.assumption_id}
          >
            <p className="flex items-center gap-1.5 text-meta text-text-secondary">
              <AssumptionKindIcon kind={kind} />
              {label}
            </p>
            <p className="text-body break-words">
              {failedAssumptionText({ ...item, kind }) || "Wording unavailable"}
            </p>
            <p className="text-meta text-text-secondary">
              {item.line_label
                ? `${item.opportunity_title} · ${item.line_label}`
                : `${item.opportunity_title} · Unplanned work`}
            </p>
            <Link
              href={assumptionTraceHref(item.opportunity_id, item.assumption_id)}
              aria-label={`${OPEN_IN_TRACE}: ${label}, ${item.opportunity_title}`}
              className="inline-flex w-fit items-center gap-1 rounded text-meta text-link no-underline outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
            >
              <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
              {OPEN_IN_TRACE}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
