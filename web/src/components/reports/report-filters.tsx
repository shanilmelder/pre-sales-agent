"use client";

import { useRouter } from "next/navigation";
import { useId, useTransition, type ChangeEvent } from "react";

import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { isCalendarDate } from "@/app/opportunities/filters";
import {
  GROUP_BY,
  reportHref,
  type GroupBy,
  type ReportCause,
  type ReportOptions,
  type ReportParams,
} from "@/lib/reports";

const LABEL = "flex min-w-0 flex-col gap-1 text-meta text-muted-foreground";
/** Selects are native and fill their label, so the label sets the width. */
const SELECT_LABEL = `${LABEL} w-44`;
const DATE =
  "h-[38px] rounded-md border border-border-strong bg-surface-alt px-2 text-body text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring text-numeric";

/** The toolbar between the sub-tabs and the KPIs: Group by, Product, Work Package, Cause, the
 * closed-date range and Include milestones. Every control is kept in the URL, so a reload or a
 * shared link shows the same report. */
export function ReportFilters({
  params,
  options,
}: {
  params: ReportParams;
  options: ReportOptions;
}) {
  const id = useId();
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  const apply = (next: ReportParams) =>
    startTransition(() => router.replace(reportHref(next), { scroll: false }));

  const select =
    (key: "product" | "workPackageId" | "cause") => (event: ChangeEvent<HTMLSelectElement>) =>
      apply({ ...params, [key]: event.target.value || undefined });

  const date = (key: "closedFrom" | "closedTo") => (event: ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    if (value === "" || isCalendarDate(value)) apply({ ...params, [key]: value || undefined });
  };

  // A product or Work Package from the URL stays selectable even when no row carries it now.
  const products = [...options.products];
  if (params.product && !products.some((p) => p.toLowerCase() === params.product?.toLowerCase())) {
    products.push(params.product);
  }
  const product =
    products.find((p) => p.toLowerCase() === params.product?.toLowerCase()) ?? "";

  return (
    <div
      role="group"
      aria-label="Report filters"
      aria-busy={pending || undefined}
      className="flex flex-wrap items-end gap-3"
    >
      <label className={SELECT_LABEL} htmlFor={`${id}-group`}>
        Group by
        <Select
          id={`${id}-group`}
          value={params.groupBy}
          onChange={(event) => apply({ ...params, groupBy: event.target.value as GroupBy })}
        >
          {GROUP_BY.map((g) => (
            <option key={g.value} value={g.value}>
              {g.label}
            </option>
          ))}
        </Select>
      </label>
      <label className={SELECT_LABEL} htmlFor={`${id}-product`}>
        Product
        <Select id={`${id}-product`} value={product} onChange={select("product")}>
          <option value="">All products</option>
          {products.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </Select>
      </label>
      <label className={SELECT_LABEL} htmlFor={`${id}-wp`}>
        Work Package
        <Select
          id={`${id}-wp`}
          value={params.workPackageId ?? ""}
          onChange={select("workPackageId")}
        >
          <option value="">All Work Packages</option>
          {options.work_packages.map((wp) => (
            <option key={wp.id} value={wp.id}>
              {wp.name}
            </option>
          ))}
          {params.workPackageId &&
          !options.work_packages.some((wp) => wp.id === params.workPackageId) ? (
            <option value={params.workPackageId}>Selected Work Package</option>
          ) : null}
        </Select>
      </label>
      <label className={SELECT_LABEL} htmlFor={`${id}-cause`}>
        Cause
        <Select
          id={`${id}-cause`}
          value={params.cause ?? ""}
          onChange={(event) =>
            apply({ ...params, cause: (event.target.value || undefined) as ReportCause | undefined })
          }
        >
          <option value="">All causes</option>
          {options.causes.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </Select>
      </label>
      <label className={LABEL} htmlFor={`${id}-from`}>
        Closed from
        <input
          id={`${id}-from`}
          type="date"
          className={DATE}
          value={params.closedFrom ?? ""}
          max={params.closedTo}
          onChange={date("closedFrom")}
        />
      </label>
      <label className={LABEL} htmlFor={`${id}-to`}>
        Closed to
        <input
          id={`${id}-to`}
          type="date"
          className={DATE}
          value={params.closedTo ?? ""}
          min={params.closedFrom}
          onChange={date("closedTo")}
        />
      </label>
      <div className={LABEL}>
        <span id={`${id}-milestones`}>Include milestones</span>
        <span className="flex h-[38px] items-center">
          <Switch
            aria-labelledby={`${id}-milestones`}
            checked={params.includeMilestones}
            onCheckedChange={(checked) => apply({ ...params, includeMilestones: checked })}
          />
        </span>
      </div>
    </div>
  );
}
