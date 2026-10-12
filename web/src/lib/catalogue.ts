import type { components } from "@/lib/api/client";

export type CatalogueEntry = components["schemas"]["CatalogueEntry"];
export type CatalogueVersion = components["schemas"]["CatalogueVersion"];
export type CatalogueKind = CatalogueEntry["kind"];

export const CODE_MAX = 40;
export const NAME_MAX = 120;
export const DEFINITION_MAX = 2000;
export const REASON_MAX = 500;

export const EMPTY_STATE =
  "No catalogue entries yet. Press c to add an Integration Type or Work Package.";

export const KINDS: readonly { kind: CatalogueKind; label: string; plural: string }[] = [
  { kind: "integration_type", label: "Integration Type", plural: "Integration Types" },
  { kind: "work_package", label: "Work Package", plural: "Work Packages" },
];

export function kindLabel(kind: CatalogueKind): string {
  return KINDS.find((k) => k.kind === kind)?.label ?? kind;
}

/** The entries of each kind, in the order given, as the two groups of the list. */
export function groupByKind(
  entries: readonly CatalogueEntry[],
): { kind: CatalogueKind; label: string; plural: string; entries: CatalogueEntry[] }[] {
  return KINDS.map((k) => ({ ...k, entries: entries.filter((e) => e.kind === k.kind) }));
}

/** The 412 notice. `changedBy` is the person who saved the latest version (null: unknown). */
export function staleMessage(changedBy: string | null): string {
  return `Changed by ${changedBy ?? "another administrator"} since you opened it.`;
}

/** Characters as the API counts them (code points), after trimming. */
function length(text: string): number {
  return Array.from(text.trim()).length;
}

/** The reason a field can't be saved, or null. Mirrors the API's rules; the API decides. */
export function fieldError(
  field: "code" | "name" | "definition" | "reason",
  value: string,
): string | null {
  const max = { code: CODE_MAX, name: NAME_MAX, definition: DEFINITION_MAX, reason: REASON_MAX }[
    field
  ];
  const size = length(value);
  if (size === 0) return `The ${field} is required.`;
  if (size > max) return `The ${field} must be at most ${max.toLocaleString("en-US")} characters.`;
  return null;
}

/** Entries after `entry` replaced (matching id) or added, keeping each kind sorted by name. */
export function upsert(entries: readonly CatalogueEntry[], entry: CatalogueEntry): CatalogueEntry[] {
  const without = entries.filter((e) => e.id !== entry.id);
  return [...without, entry].sort(
    (a, b) =>
      a.kind.localeCompare(b.kind) ||
      a.name.toLocaleLowerCase().localeCompare(b.name.toLocaleLowerCase()),
  );
}
