// All Opportunities filters in the URL query (Story 1.7 Part B). Safe on server and client.
import { STATUSES, UUID_RE, type OpportunityStatus } from "@/lib/opportunities";

/** The filters, as the API takes them. Every one is optional; they combine with AND. */
export type Filters = {
  status?: OpportunityStatus;
  owner?: string;
  product?: string;
  from?: string;
  to?: string;
};

export type FilterKey = keyof Filters;
export const FILTER_KEYS: readonly FilterKey[] = ["status", "owner", "product", "from", "to"];

/** The API's product name limit (code points). */
const PRODUCT_MAX = 100;

type SearchParams = Record<string, string | string[] | undefined> | URLSearchParams;

function first(params: SearchParams | undefined, key: string): string | undefined {
  if (!params) return undefined;
  if (params instanceof URLSearchParams) return params.get(key) ?? undefined;
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

/** A real calendar date as `YYYY-MM-DD`. */
export function isCalendarDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const [, y, m, d] = match.map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

/** The filters in `params`. Invalid values are dropped (the list is then unfiltered by
 * them), so a hand-edited URL never gets a 422 from the API. A reversed range drops both
 * dates. */
export function parseFilters(params: SearchParams | undefined): Filters {
  const filters: Filters = {};
  const status = first(params, "status");
  if (status && Object.hasOwn(STATUSES, status)) filters.status = status as OpportunityStatus;
  const owner = first(params, "owner");
  if (owner && UUID_RE.test(owner)) filters.owner = owner.toLowerCase();
  const product = first(params, "product")?.trim();
  if (product && Array.from(product).length <= PRODUCT_MAX) filters.product = product;
  const from = first(params, "from");
  const to = first(params, "to");
  const validFrom = from && isCalendarDate(from) ? from : undefined;
  const validTo = to && isCalendarDate(to) ? to : undefined;
  if (!(validFrom && validTo && validFrom > validTo)) {
    if (validFrom) filters.from = validFrom;
    if (validTo) filters.to = validTo;
  }
  return filters;
}

export function hasFilters(filters: Filters): boolean {
  return FILTER_KEYS.some((key) => filters[key] !== undefined);
}

/** `path?…` with the filters (in a fixed order) and the page when it is past the first. */
export function filtersHref(path: string, filters: Filters, page = 1): string {
  const query = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const value = filters[key];
    if (value) query.set(key, value);
  }
  if (page > 1) query.set("page", String(page));
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

/** The filters with `key` set to `value` (cleared when blank). */
export function withFilter(filters: Filters, key: FilterKey, value: string): Filters {
  const next: Filters = { ...filters };
  if (value) (next as Record<FilterKey, string>)[key] = value;
  else delete next[key];
  return next;
}
