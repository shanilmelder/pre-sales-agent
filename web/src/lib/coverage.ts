// Knowledge coverage display helpers (Story 3.5). Safe on server and client.
import type { components } from "@/lib/api/client";
import { UUID_RE } from "@/lib/opportunities";
import type { PillTone } from "@/components/ui/pill";

export type KnowledgeCoverage = components["schemas"]["KnowledgeCoverage"];
export type CoverageRow = components["schemas"]["CoverageRow"];
export type CoverageCell = components["schemas"]["CoverageCell"];
export type CoverageIndustry = components["schemas"]["CoverageIndustry"];
export type CoverageIntegrationType = components["schemas"]["CoverageIntegrationType"];
export type CoverageStatus = CoverageCell["status"];

export const GRAPH_HREF = "/knowledge/graph";
export const SOURCES_HREF = "/knowledge";
export const CHECKLISTS_HREF = "/knowledge/checklists";
export const COVERAGE_HREF = "/knowledge/coverage";

/** The longest product a filter link may carry (the API's longest Source product, with room). */
const PRODUCT_PARAM_MAX = 200;

/** Each status's label and pill tone (the mockup: Ready green, Partial amber, Missing
 * red). The label always shows, so the meaning never depends on colour. */
export const COVERAGE_STATUSES: Record<CoverageStatus, { label: string; tone: PillTone }> = {
  ready: { label: "Ready", tone: "resolved" },
  partial: { label: "Partial", tone: "gap" },
  missing: { label: "Missing", tone: "blocker" },
};

/** The Sources count in words: "None", "Stale" when every Source is stale (with how many),
 * else the count, with the stale ones noted. */
export function sourcesText(cell: Pick<CoverageCell, "sources" | "stale">): string {
  if (cell.sources === 0) return "None";
  if (cell.stale === cell.sources) return `Stale (${cell.sources})`;
  return cell.stale > 0 ? `${cell.sources} (${cell.stale} stale)` : String(cell.sources);
}

/** The Checklists count in words: "None" or the count. */
export function checklistsText(cell: Pick<CoverageCell, "checklists">): string {
  return cell.checklists === 0 ? "None" : String(cell.checklists);
}

function filterQuery(product: string, integrationTypeId: string): string {
  return new URLSearchParams({ product, integration_type: integrationTypeId }).toString();
}

/** Knowledge → Sources filtered to the cell's product and Integration Type. */
export function sourcesHref(product: string, integrationTypeId: string): string {
  return `${SOURCES_HREF}?${filterQuery(product, integrationTypeId)}`;
}

/** Knowledge → Checklists filtered to the cell's product and Integration Type. */
export function checklistsHref(product: string, integrationTypeId: string): string {
  return `${CHECKLISTS_HREF}?${filterQuery(product, integrationTypeId)}`;
}

/** The product and Integration Type filters a Sources or Checklists link carries
 * (`?product=&integration_type=`). Anything malformed or repeated is ignored (no filter). */
export function seededFilters(
  params: Record<string, string | string[] | undefined> | undefined,
): { product: string; integrationTypeId: string } {
  const one = (value: string | string[] | undefined) =>
    typeof value === "string" ? value : "";
  const product = one(params?.product).trim();
  const type = one(params?.integration_type).trim();
  return {
    product: product.length <= PRODUCT_PARAM_MAX ? product : "",
    integrationTypeId: UUID_RE.test(type) ? type.toLowerCase() : "",
  };
}

/** `options` with `wanted` in it: the option spelled like it (ignoring case) if there is
 * one, else `wanted` added, sorted. The value to select is `selected`. */
export function withOption(
  options: readonly string[],
  wanted: string,
): { options: string[]; selected: string } {
  if (wanted === "") return { options: [...options], selected: "" };
  const match = options.find((o) => o.toLowerCase() === wanted.toLowerCase());
  if (match !== undefined) return { options: [...options], selected: match };
  return { options: [...options, wanted].sort((a, b) => a.localeCompare(b)), selected: wanted };
}

/** The id a link asks to open (`?source=<id>`, `?checklist=<id>`), or null when missing,
 * malformed or repeated. */
export function selectedParam(
  params: Record<string, string | string[] | undefined> | undefined,
  key: "source" | "checklist",
): string | null {
  const value = params?.[key];
  return typeof value === "string" && UUID_RE.test(value.trim()) ? value.trim().toLowerCase() : null;
}

/** Knowledge → Sources with the Source open. */
export function sourceHref(sourceId: string): string {
  return `${SOURCES_HREF}?${new URLSearchParams({ source: sourceId }).toString()}`;
}

/** Knowledge → Checklists with the Checklist open. */
export function checklistHref(checklistId: string): string {
  return `${CHECKLISTS_HREF}?${new URLSearchParams({ checklist: checklistId }).toString()}`;
}

/** Knowledge → Coverage narrowed to one product (its row) or one Integration Type (its
 * column). */
export function coverageHref(filter: { product: string } | { integrationTypeId: string }): string {
  const query: Record<string, string> =
    "product" in filter
      ? { product: filter.product }
      : { integration_type: filter.integrationTypeId };
  return `${COVERAGE_HREF}?${new URLSearchParams(query).toString()}`;
}

/** The matrix narrowed to the product's row (ignoring case) and the Integration Type's
 * column; an empty filter keeps everything. Industry-only Checklists are kept. */
export function narrowCoverage(
  coverage: KnowledgeCoverage,
  filter: { product: string; integrationTypeId: string },
): KnowledgeCoverage {
  const product = filter.product.toLowerCase();
  const typeId = filter.integrationTypeId;
  const keepType = (id: string) => typeId === "" || id === typeId;
  return {
    ...coverage,
    integration_types: coverage.integration_types.filter((t) => keepType(t.id)),
    rows: coverage.rows
      .filter((row) => product === "" || row.product.toLowerCase() === product)
      .map((row) => ({ ...row, cells: row.cells.filter((c) => keepType(c.integration_type_id)) })),
  };
}
