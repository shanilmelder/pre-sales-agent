"use client";

import { ChevronDownIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useId,
  useState,
  useTransition,
  type ChangeEvent,
  type MouseEvent,
  type ReactNode,
} from "react";

import {
  filtersHref,
  hasFilters,
  isCalendarDate,
  withFilter,
  type FilterKey,
  type Filters,
} from "@/app/opportunities/filters";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  formatDate,
  formatShortDate,
  STATUSES,
  type OpportunityFacets,
  type OpportunityStatus,
  utcToday,
} from "@/lib/opportunities";
import { cn } from "@/lib/utils";

/** The label for an owner from the URL whose name isn't among the facets (or the facets
 * couldn't be loaded): the id is still applied, but there is no name to show. */
export const SELECTED_OWNER = "Selected owner";
export const RANGE_ERROR = "From must be on or before To";

const controlClass =
  "h-8 rounded-md border border-input bg-background px-2 text-body text-foreground outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive";
const labelClass = "flex flex-col gap-1 text-meta text-muted-foreground";

/** The quiet "Clear filters" link that follows the chips. */
export const clearFiltersClass =
  "inline-flex items-center rounded-md px-2.5 py-[5px] text-text-secondary outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary text-[13px] leading-[1.4]";

type DateKey = "from" | "to";
type Drafts = Record<DateKey, string>;

const draftsOf = (filters: Filters): Drafts => ({ from: filters.from ?? "", to: filters.to ?? "" });

/** A date the user has finished entering: a real calendar date with a four-digit year from
 * 1000 on. While a year is being typed the input reports values like `0002-11-01`; those
 * are not committed (blur commits whatever valid date is left). */
function isCompleteDate(value: string): boolean {
  return isCalendarDate(value) && Number(value.slice(0, 4)) >= 1000;
}

/** The Opportunities list filters: a dashed chip per filter, each opening its labelled
 * control(s) in a popover, then Clear filters once one is applied. Values come from the URL
 * (`filters`) and every change replaces the URL, on page 1, so filters survive reload and
 * sharing without piling up history. Owner and product choices come from the facets; a value
 * from a shared URL that isn't among them is still shown so the control never lies about
 * what is applied. */
export function FilterBar({
  basePath,
  filters,
  facets,
}: {
  basePath: string;
  filters: Filters;
  /** Null when the facets couldn't be loaded: the selects then offer only "Any". */
  facets: OpportunityFacets | null;
}) {
  const router = useRouter();
  const id = useId();
  const [pending, startTransition] = useTransition();
  // Local copies so a control shows its new value at once while the page navigates; reset
  // whenever the URL's filters change by value (not on every rerender of the parent).
  const urlKey = filtersHref("", filters);
  const [shownKey, setShownKey] = useState(urlKey);
  const [values, setValues] = useState<Filters>(filters);
  const [drafts, setDrafts] = useState<Drafts>(() => draftsOf(filters));
  const [rangeError, setRangeError] = useState(false);
  if (shownKey !== urlKey) {
    setShownKey(urlKey);
    setValues(filters);
    setDrafts(draftsOf(filters));
    setRangeError(false);
  }

  function navigate(next: Filters) {
    setValues(next);
    startTransition(() => router.replace(filtersHref(basePath, next), { scroll: false }));
  }

  function changeSelect(key: Exclude<FilterKey, DateKey>) {
    return (event: ChangeEvent<HTMLSelectElement>) =>
      navigate(withFilter(values, key, event.target.value));
  }

  /** Applies a finished date (or a cleared one). A reversed range is not applied: the
   * fields say why instead. */
  function commitDate(key: DateKey, raw: string) {
    if (raw !== "" && !isCalendarDate(raw)) return;
    const next = withFilter(values, key, raw);
    if (next.from && next.to && next.from > next.to) {
      setRangeError(true);
      return;
    }
    setRangeError(false);
    if ((next[key] ?? "") !== (values[key] ?? "")) navigate(next);
  }

  function changeDate(key: DateKey) {
    return (event: ChangeEvent<HTMLInputElement>) => {
      const raw = event.target.value;
      setDrafts((current) => ({ ...current, [key]: raw }));
      if (raw === "" || isCompleteDate(raw)) commitDate(key, raw);
    };
  }

  function clear(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    setDrafts({ from: "", to: "" });
    setRangeError(false);
    navigate({});
  }

  const owners = [...(facets?.owners ?? [])];
  if (values.owner && !owners.some((owner) => owner.id === values.owner)) {
    owners.push({ id: values.owner, name: SELECTED_OWNER });
  }
  const products = [...(facets?.products ?? [])];
  const product =
    values.product &&
    (products.find((name) => name.toLowerCase() === values.product?.toLowerCase()) ??
      values.product);
  if (product && !products.includes(product)) products.push(product);

  const errorId = `${id}-range-error`;
  const dateInput = (key: DateKey, label: string) => (
    <label className={labelClass} htmlFor={`${id}-${key}`}>
      {label}
      <input
        id={`${id}-${key}`}
        type="date"
        className={`${controlClass} text-numeric`}
        value={drafts[key]}
        max={key === "from" ? values.to : undefined}
        min={key === "to" ? values.from : undefined}
        aria-invalid={rangeError || undefined}
        aria-describedby={rangeError ? errorId : undefined}
        onChange={changeDate(key)}
        onBlur={(event) => commitDate(key, event.target.value)}
      />
    </label>
  );

  const ownerName = values.owner && owners.find((owner) => owner.id === values.owner)?.name;
  const clearable = hasFilters(values) || drafts.from !== "" || drafts.to !== "";

  return (
    <div
      role="group"
      aria-label="Filters"
      aria-busy={pending || undefined}
      className="flex flex-wrap items-center gap-2"
    >
      <FilterChip
        label="Status"
        closeOnChange
        value={values.status && STATUSES[values.status]?.label}
      >
        <label className={labelClass} htmlFor={`${id}-status`}>
          Status
          <select
            id={`${id}-status`}
            className={controlClass}
            value={values.status ?? ""}
            onChange={changeSelect("status")}
          >
            <option value="">Any status</option>
            {(Object.keys(STATUSES) as OpportunityStatus[]).map((status) => (
              <option key={status} value={status}>
                {STATUSES[status].label}
              </option>
            ))}
          </select>
        </label>
      </FilterChip>
      <FilterChip label="Owner" closeOnChange value={ownerName}>
        <label className={labelClass} htmlFor={`${id}-owner`}>
          Owner
          <select
            id={`${id}-owner`}
            className={controlClass}
            value={values.owner ?? ""}
            onChange={changeSelect("owner")}
          >
            <option value="">Any owner</option>
            {owners.map((owner) => (
              <option key={owner.id} value={owner.id}>
                {owner.name}
              </option>
            ))}
          </select>
        </label>
      </FilterChip>
      <FilterChip label="Product" closeOnChange value={product || undefined}>
        <label className={labelClass} htmlFor={`${id}-product`}>
          Product
          <select
            id={`${id}-product`}
            className={controlClass}
            value={product || ""}
            onChange={changeSelect("product")}
          >
            <option value="">Any product</option>
            {products.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </FilterChip>
      <FilterChip label="Proposal date" value={dateRangeLabel(values.from, values.to)}>
        <div className="flex gap-3">
          {dateInput("from", "Target date from")}
          {dateInput("to", "Target date to")}
        </div>
        {rangeError ? (
          <p id={errorId} role="alert" className="pt-2 text-meta text-destructive">
            {RANGE_ERROR}
          </p>
        ) : null}
      </FilterChip>
      {clearable ? (
        <Link
          href={basePath}
          onClick={clear}
          className={clearFiltersClass}
        >
          Clear filters
        </Link>
      ) : null}
    </div>
  );
}

/** The chip's value for the applied date range: "1 Nov – 15 Nov", "from 1 Nov", "until
 * 15 Nov", or nothing. */
function dateRangeLabel(from?: string, to?: string): string | undefined {
  // The year shows when the range spans years or leaves the current (UTC) one.
  const year = utcToday().slice(0, 4);
  const years = new Set([from, to].filter(Boolean).map((date) => date!.slice(0, 4)));
  const withYear = years.size > 1 || !years.has(year);
  const show = (date: string) => (withYear ? formatDate(date) : formatShortDate(date));
  if (from && to) return `${show(from)} – ${show(to)}`;
  if (from) return `from ${show(from)}`;
  if (to) return `until ${show(to)}`;
  return undefined;
}

/** A dashed chip that opens its control(s) in a popover. With a value applied it reads
 * "Label: value" in the solid primary tint. */
export function FilterChip({
  label,
  value,
  closeOnChange = false,
  children,
}: {
  label: string;
  value?: string;
  /** Close once a control inside changes (a single pick completes the filter). */
  closeOnChange?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className={`${cn(
          "inline-flex items-center gap-1 rounded-md border px-2.5 py-[5px] outline-none focus-visible:ring-2 focus-visible:ring-primary",
          value
            ? "border-solid border-primary-tint bg-primary-tint text-primary-text"
            : "border-dashed border-border-strong bg-transparent text-text-secondary hover:text-foreground",
        )} text-[13px] leading-[1.4]`}
      >
        {value ? `${label}: ${value}` : label}
        <ChevronDownIcon className="size-3" strokeWidth={1.75} aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent aria-label={`${label} filter`}>
        <div onChange={closeOnChange ? () => setOpen(false) : undefined}>{children}</div>
      </PopoverContent>
    </Popover>
  );
}
