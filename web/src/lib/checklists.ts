// Checklist display and draft helpers (Story 3.4). Safe on server and client.
import type { components } from "@/lib/api/client";
import { IMPACTS, impactLabel } from "@/lib/gaps";
import type { Permission } from "@/lib/navigation";

export type Checklist = components["schemas"]["Checklist"];
export type ChecklistDraft = components["schemas"]["ChecklistDraft"];
export type ChecklistItem = components["schemas"]["ChecklistItem"];
export type ChecklistVersion = components["schemas"]["ChecklistVersion"];
export type ChecklistVersionSummary = components["schemas"]["ChecklistVersionSummary"];
export type DraftInput = components["schemas"]["DraftInput"];
export type DraftItemInput = components["schemas"]["DraftItemInput"];
export type ChecklistDomain = components["schemas"]["Domain"];
export type ItemKind = components["schemas"]["ItemKind"];
export type ItemImpact = DraftItemInput["impact"];
/** A whole draft as sent with `PUT …/draft`, every list present. */
export type DraftBody = Omit<DraftInput, "products" | "industry" | "integration_type_ids" | "items"> & {
  products: string[];
  industry: string | null;
  integration_type_ids: string[];
  items: DraftItemInput[];
};

export { IMPACTS, impactLabel };

export const NAME_MAX = 200;
export const PRODUCT_MAX = 100;
export const INDUSTRY_MAX = 100;
export const ITEM_TEXT_MAX = 2000;
export const REASON_MAX = 500;

/** The permission to edit a Checklist's draft: what decides whether the authoring controls
 * show. The API decides; anyone else gets 403. */
export const AUTHOR_PERMISSION = "knowledge.checklist.edit";

/** The Checklists list's empty states. */
export const EMPTY_STATE = "No Checklists yet.";
export const EMPTY_STATE_AUTHOR = "No Checklists yet. Press c to write the first one.";

export const DOMAINS: readonly { value: ChecklistDomain; label: string }[] = [
  { value: "engineering", label: "Engineering" },
  { value: "delivery", label: "Delivery" },
  { value: "security", label: "Security" },
  { value: "commercial", label: "Commercial" },
  { value: "general", label: "General" },
];

export const ITEM_KINDS: readonly { value: ItemKind; label: string }[] = [
  { value: "question", label: "Question" },
  { value: "risk", label: "Risk" },
];

export function domainLabel(value: ChecklistDomain): string {
  return DOMAINS.find((d) => d.value === value)?.label ?? value;
}

export function kindLabel(value: ItemKind): string {
  return ITEM_KINDS.find((k) => k.value === value)?.label ?? value;
}

/** True when the user may create, edit, publish and retire Checklists (engineering, PM and
 * security reviewers and platform administrators). Display only. */
export function canAuthor(permissions: readonly Permission[]): boolean {
  return permissions.includes(AUTHOR_PERMISSION);
}

/** Where the Checklist stands: Draft (never published), Published (vN, maybe with a draft
 * being edited) or Retired. */
export function checklistStatus(checklist: Pick<Checklist, "retired" | "current_version">): string {
  if (checklist.retired) return "Retired";
  return checklist.current_version === null ? "Draft" : `Published v${checklist.current_version}`;
}

/** The scope in words, e.g. "AutoStore, SAP · Retail · SAP IDoc". */
export function scopeText(
  scope: Pick<Checklist, "products" | "industry" | "integration_types">,
): string {
  const parts = [
    scope.products.join(", "),
    scope.industry ?? "",
    scope.integration_types.map((t) => t.name).join(", "),
  ].filter((part) => part.length > 0);
  return parts.length > 0 ? parts.join(" · ") : "No scope";
}

/** The stored draft as the `PUT …/draft` body. */
export function draftInput(draft: ChecklistDraft): DraftBody {
  return {
    name: draft.name,
    domain: draft.domain,
    products: draft.products,
    industry: draft.industry,
    integration_type_ids: draft.integration_types.map((t) => t.id),
    items: draft.items.map(itemInput),
  };
}

export function itemInput(item: ChecklistItem): DraftItemInput {
  return {
    id: item.id,
    kind: item.kind,
    text: item.text,
    why_it_matters: item.why_it_matters,
    affected_entry_id: item.affected_area?.id ?? null,
    impact: item.impact,
    mandatory: item.mandatory,
  };
}

/** A new, empty item (it gets its stable id when the draft is saved). */
export function newItem(): DraftItemInput {
  return {
    id: null,
    kind: "question",
    text: "",
    why_it_matters: "",
    affected_entry_id: null,
    impact: "medium",
    mandatory: false,
  };
}

/** Products typed as one comma-separated line: trimmed, blanks dropped, repeats ignoring
 * case kept once (the API does the same). */
export function parseProducts(line: string): string[] {
  const seen = new Set<string>();
  const products: string[] = [];
  for (const raw of line.split(",")) {
    const name = raw.trim();
    const key = name.toLocaleLowerCase();
    if (name && !seen.has(key)) {
      seen.add(key);
      products.push(name);
    }
  }
  return products;
}

/** Characters as the API counts them (code points), after trimming. */
function length(text: string): number {
  return Array.from(text.trim()).length;
}

/** The reason a value can't be saved, or null. Mirrors the API's rules; the API decides. */
export function fieldError(field: "name" | "reason", value: string): string | null {
  const max = field === "name" ? NAME_MAX : REASON_MAX;
  const size = length(value);
  if (size === 0) return `The ${field} is required.`;
  if (size > max) return `The ${field} must be at most ${max.toLocaleString("en-US")} characters.`;
  return null;
}

/** Checklists after `checklist` replaced (matching id) or added, sorted by name. */
export function upsert(checklists: readonly Checklist[], checklist: Checklist): Checklist[] {
  const without = checklists.filter((c) => c.id !== checklist.id);
  return [...without, checklist].sort((a, b) =>
    a.name.toLocaleLowerCase().localeCompare(b.name.toLocaleLowerCase()),
  );
}

/** The 412 notice. */
export function staleChangeMessage(): string {
  return "Changed by someone else since you opened it. Reload to see their change.";
}

const WHEN = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

export function formatWhen(iso: string): string {
  return `${WHEN.format(new Date(iso))} UTC`;
}
