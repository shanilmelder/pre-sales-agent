"use client";

import { ArrowDownIcon, ArrowUpDownIcon, ArrowUpIcon, ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { Fragment, useId, useState } from "react";

import { BaselinePill } from "@/components/opportunities/set-baseline";
import { VarianceBar } from "@/components/reports/variance-bar";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  EXPORT_LATER,
  ariaSort,
  formatHours,
  groupByLabel,
  groupSubline,
  nextSort,
  plural,
  reportHref,
  sortGroups,
  type GroupBy,
  type ReportParams,
  type SortKey,
  type SortState,
  type VarianceGroup,
} from "@/lib/reports";
import { cn } from "@/lib/utils";
import { tabHref } from "@/lib/workspace";

const GRID = "grid grid-cols-[minmax(0,1fr)_90px_90px_220px_minmax(0,1fr)] items-center gap-4 px-5";
/** Row padding: the density's 12px (6px compact) plus 6px, as the mockup. */
const ROW = `${GRID} border-t border-border py-[18px] [[data-density=compact]_&]:py-3`;
const LINK =
  "rounded text-link no-underline outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary";

function SortHeader({
  label,
  sortKey,
  sort,
  onSort,
  align = "left",
}: {
  label: string;
  sortKey: SortKey;
  sort: SortState;
  onSort: (key: SortKey) => void;
  align?: "left" | "right";
}) {
  const order = ariaSort(sort, sortKey);
  const Icon =
    order === "descending" ? ArrowDownIcon : order === "ascending" ? ArrowUpIcon : ArrowUpDownIcon;
  return (
    <span role="columnheader" aria-sort={order} className={align === "right" ? "text-right" : undefined}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="inline-flex items-center gap-1 rounded outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
      >
        {label}
        <Icon className="size-3.5" aria-hidden="true" />
        <span className="sr-only">{`, sort by ${label.toLowerCase()}`}</span>
      </button>
    </span>
  );
}

/** The grouped "Estimate versus actual" table: one row per group, expandable to the group's
 * Opportunities. Every figure is the server's; sorting only reorders them. */
export function VarianceTable({
  groups,
  groupBy,
  closedOpportunities,
  params,
}: {
  groups: readonly VarianceGroup[];
  groupBy: GroupBy;
  closedOpportunities: number;
  params: ReportParams;
}) {
  const id = useId();
  const [sort, setSort] = useState<SortState>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const label = groupByLabel(groupBy);
  const rows = sortGroups(groups, sort);

  const toggle = (key: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <Card className="min-w-0 gap-0 overflow-hidden py-0">
      <div className="flex items-center gap-3 px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 id={`${id}-title`} className="text-[16px] leading-6 font-semibold">
            {`Estimate versus actual by ${label}`}
          </h2>
          <p className="text-[13px] text-text-secondary">
            {`${plural(closedOpportunities, "closed Opportunity", "closed Opportunities")} · hours`}
          </p>
        </div>
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                aria-disabled="true"
                className={`${buttonVariants({ variant: "outline" })} text-control`}
              />
            }
          >
            Export
            <span className="sr-only">{`. ${EXPORT_LATER}`}</span>
          </TooltipTrigger>
          <TooltipContent>{EXPORT_LATER}</TooltipContent>
        </Tooltip>
      </div>
      <div role="table" aria-labelledby={`${id}-title`} className="text-body">
        <div role="rowgroup">
          <div
            role="row"
            className={`${GRID} bg-surface-alt py-2.5 text-[12px] font-medium text-text-secondary`}
          >
            <SortHeader label={label} sortKey="label" sort={sort} onSort={(k) => setSort(nextSort(sort, k))} />
            <SortHeader
              label="Estimate h"
              sortKey="estimate"
              sort={sort}
              onSort={(k) => setSort(nextSort(sort, k))}
              align="right"
            />
            <SortHeader
              label="Actual h"
              sortKey="actual"
              sort={sort}
              onSort={(k) => setSort(nextSort(sort, k))}
              align="right"
            />
            <SortHeader label="Variance" sortKey="variance" sort={sort} onSort={(k) => setSort(nextSort(sort, k))} />
            <span role="columnheader">Main cause</span>
          </div>
        </div>
        <div role="rowgroup">
          {rows.map((group) => {
            const open = expanded.has(group.key);
            const panel = `${id}-${group.key}`;
            return (
              <Fragment key={group.key}>
                <div role="row" className={ROW} data-group={group.key}>
                  <span role="cell" className="flex min-w-0 items-start gap-1.5">
                    <button
                      type="button"
                      aria-expanded={open}
                      aria-controls={open ? panel : undefined}
                      onClick={() => toggle(group.key)}
                      className="mt-0.5 shrink-0 rounded text-text-secondary outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
                    >
                      <ChevronRightIcon
                        aria-hidden="true"
                        className={cn("size-4 transition-transform motion-reduce:transition-none", open && "rotate-90")}
                      />
                      <span className="sr-only">{`${open ? "Hide" : "Show"} the Opportunities in ${group.label}`}</span>
                    </button>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{group.label}</span>
                      <span className="text-meta text-text-secondary">{groupSubline(group)}</span>
                    </span>
                  </span>
                  <span role="cell" className="text-right text-numeric">
                    {formatHours(group.estimate_hours)}
                  </span>
                  <span role="cell" className="text-right text-numeric">
                    {formatHours(group.actual_hours)}
                  </span>
                  <span role="cell">
                    <VarianceBar variance={group.variance} />
                  </span>
                  <span role="cell" className="min-w-0 truncate text-[13px]">
                    {group.main_cause ? (
                      <Link
                        href={reportHref({ ...params, cause: group.main_cause.value })}
                        className={LINK}
                        aria-label={`${group.main_cause.label}: show only this cause`}
                      >
                        {group.main_cause.label}
                      </Link>
                    ) : (
                      <span className="text-text-secondary">—</span>
                    )}
                  </span>
                </div>
                {open
                  ? group.opportunities.map((opp, index) => (
                      <div
                        key={`${opp.opportunity_id}-${opp.estimate_version_id}`}
                        id={index === 0 ? panel : undefined}
                        role="row"
                        className={`${ROW} bg-canvas`}
                        data-opportunity={opp.opportunity_id}
                      >
                        <span role="cell" className="flex min-w-0 items-center gap-2 pl-6">
                          <Link href={tabHref(opp.opportunity_id, "overview")} className={cn(LINK, "truncate")}>
                            {opp.title}
                          </Link>
                          <span className="shrink-0 text-meta text-text-secondary text-numeric">{`v${opp.estimate_version}`}</span>
                          {opp.is_baseline ? <BaselinePill className="shrink-0" /> : null}
                        </span>
                        <span role="cell" className="text-right text-numeric">
                          {formatHours(opp.estimate_hours)}
                        </span>
                        <span role="cell" className="text-right text-numeric">
                          {formatHours(opp.actual_hours)}
                        </span>
                        <span role="cell">
                          <VarianceBar variance={opp.variance} />
                        </span>
                        <span role="cell" className="min-w-0 truncate text-[13px]">
                          {opp.main_cause ? (
                            <Link
                              href={tabHref(opp.opportunity_id, "actuals")}
                              className={LINK}
                              aria-label={`${opp.main_cause.label}: open the Actuals of ${opp.title}`}
                            >
                              {opp.main_cause.label}
                            </Link>
                          ) : (
                            <span className="text-text-secondary">—</span>
                          )}
                        </span>
                      </div>
                    ))
                  : null}
              </Fragment>
            );
          })}
        </div>
      </div>
    </Card>
  );
}
