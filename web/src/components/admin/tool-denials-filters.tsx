"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState, useTransition, type ChangeEvent, type MouseEvent } from "react";

import {
  DENIALS_PATH,
  denialsHref,
  hasDenialFilters,
  isCalendarDate,
  type DenialFilters,
} from "@/lib/admin";

export const DENIAL_RANGE_ERROR = "From must be on or before To";
/** The label for an agent id from the URL that isn't a registered Agent. */
export const SELECTED_AGENT = "Selected agent";

const controlClass =
  "h-8 rounded-md border border-input bg-background px-2 text-body text-foreground outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive";
const labelClass = "flex flex-col gap-1 text-meta text-muted-foreground";
const clearClass =
  "inline-flex items-center rounded-md px-2.5 py-[5px] text-[13px] leading-[1.4] text-text-secondary outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary";

type DateKey = "from" | "to";

/** A date the user has finished entering (a four-digit year from 1000 on). */
function isCompleteDate(value: string): boolean {
  return isCalendarDate(value) && Number(value.slice(0, 4)) >= 1000;
}

/** The denied tool call filters (Story 7.4): Agent, and a from/to date (UTC days). Values come
 * from the URL (`filters`); every change replaces the URL on page 1, so filters survive
 * reload and sharing. A reversed range is not applied: the fields say why instead. */
export function ToolDenialsFilters({
  filters,
  agents,
}: {
  filters: DenialFilters;
  /** The registered Agents' ids, for the Agent picker. */
  agents: readonly { agent_id: string; name: string }[];
}) {
  const router = useRouter();
  const id = useId();
  const [pending, startTransition] = useTransition();
  const urlKey = denialsHref(filters);
  const [shownKey, setShownKey] = useState(urlKey);
  const [values, setValues] = useState<DenialFilters>(filters);
  const [drafts, setDrafts] = useState({ from: filters.from ?? "", to: filters.to ?? "" });
  const [rangeError, setRangeError] = useState(false);
  if (shownKey !== urlKey) {
    setShownKey(urlKey);
    setValues(filters);
    setDrafts({ from: filters.from ?? "", to: filters.to ?? "" });
    setRangeError(false);
  }

  function navigate(next: DenialFilters) {
    setValues(next);
    startTransition(() => router.replace(denialsHref(next), { scroll: false }));
  }

  function withValue(key: keyof DenialFilters, value: string): DenialFilters {
    const next: DenialFilters = { ...values };
    if (value) next[key] = value;
    else delete next[key];
    return next;
  }

  function commitDate(key: DateKey, raw: string) {
    if (raw !== "" && !isCalendarDate(raw)) return;
    const next = withValue(key, raw);
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

  const choices = agents.map((agent) => ({ value: agent.agent_id, label: agent.agent_id }));
  if (values.agent_id && !choices.some((choice) => choice.value === values.agent_id)) {
    choices.push({ value: values.agent_id, label: `${values.agent_id} (${SELECTED_AGENT})` });
  }
  const errorId = `${id}-range-error`;
  const clearable = hasDenialFilters(values) || drafts.from !== "" || drafts.to !== "";

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

  return (
    <div
      role="group"
      aria-label="Filters"
      aria-busy={pending || undefined}
      className="flex flex-wrap items-end gap-3"
    >
      <label className={labelClass} htmlFor={`${id}-agent`}>
        Agent
        <select
          id={`${id}-agent`}
          className={controlClass}
          value={values.agent_id ?? ""}
          onChange={(event) => navigate(withValue("agent_id", event.target.value))}
        >
          <option value="">Any agent</option>
          {choices.map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </select>
      </label>
      {dateInput("from", "From (UTC)")}
      {dateInput("to", "To (UTC)")}
      {clearable ? (
        <Link href={DENIALS_PATH} onClick={clear} className={clearClass}>
          Clear filters
        </Link>
      ) : null}
      {rangeError ? (
        <p id={errorId} role="alert" className="basis-full text-meta text-destructive">
          {DENIAL_RANGE_ERROR}
        </p>
      ) : null}
    </div>
  );
}
