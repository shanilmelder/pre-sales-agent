"use client";

import { ChevronDownIcon } from "lucide-react";
import { useId } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  areaFilterOptions,
  IMPACT_FILTER_OPTIONS,
  QUESTION_FILTER_OPTIONS,
  type Gap,
  type GapFilters,
} from "@/lib/gaps";
import { cn } from "@/lib/utils";

/** One filter: a dashed trigger ("Impact") that opens a popover of radio options, Any first.
 * With a value picked the trigger reads "Impact: High" on a solid border. */
function GapFilter<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T | null;
  onChange: (value: T | null) => void;
}) {
  const name = useId();
  // A picked value no longer offered (its last Gap went) still shows, so it can be cleared.
  const picked = value === null ? undefined : (options.find((o) => o.value === value)?.label ?? value);
  const choices: { value: T | null; label: string }[] = [{ value: null, label: "Any" }, ...options];
  return (
    <Popover>
      <PopoverTrigger
        data-gap-filter={label}
        className={`${cn(
          "inline-flex h-7 items-center gap-1 rounded-md border px-2.5 outline-none focus-visible:ring-2 focus-visible:ring-primary",
          picked
            ? "border-solid border-primary-tint bg-primary-tint text-primary-text"
            : "border-dashed border-border-strong bg-transparent text-text-secondary hover:text-foreground",
        )} text-control`}
      >
        {picked ? `${label}: ${picked}` : label}
        <ChevronDownIcon className="size-3" strokeWidth={1.75} aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent aria-label={`${label} filter`} className="min-w-44 p-1.5">
        <fieldset className="flex flex-col">
          <legend className="sr-only">{label}</legend>
          {choices.map((choice) => (
            <label
              key={choice.value ?? ""}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-body hover:bg-muted"
            >
              <input
                type="radio"
                name={name}
                checked={choice.value === value}
                onChange={() => onChange(choice.value)}
                className="accent-primary"
              />
              {choice.label}
            </label>
          ))}
        </fieldset>
      </PopoverContent>
    </Popover>
  );
}

/** The Gaps tab's three client-side filters (Impact, Area, Question status). Area offers the
 * categories present in `items`. Nothing is persisted. */
export function GapsFilters({
  items,
  filters,
  onChange,
}: {
  items: readonly Pick<Gap, "category">[];
  filters: GapFilters;
  onChange: (filters: GapFilters) => void;
}) {
  return (
    <div role="group" aria-label="Filters" className="flex flex-wrap items-center gap-2">
      <GapFilter
        label="Impact"
        options={IMPACT_FILTER_OPTIONS}
        value={filters.impact}
        onChange={(impact) => onChange({ ...filters, impact })}
      />
      <GapFilter
        label="Area"
        options={areaFilterOptions(items)}
        value={filters.category}
        onChange={(category) => onChange({ ...filters, category })}
      />
      <GapFilter
        label="Question status"
        options={QUESTION_FILTER_OPTIONS}
        value={filters.question}
        onChange={(question) => onChange({ ...filters, question })}
      />
    </div>
  );
}
