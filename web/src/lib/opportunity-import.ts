// New Opportunity "Import from file" helpers (Story 1.7, import from file). Safe on server
// and client.
import type { components } from "@/lib/api/client";

export type OpportunityImport = components["schemas"]["OpportunityImport"];
export type ImportSuggestions = components["schemas"]["ImportSuggestions"];

/** What the file picker offers. The API decides what is allowed. */
export const IMPORT_ACCEPTED_FILES = ".eml,.vtt,.txt,.docx,.pdf";

/** How often the form asks whether the file has been read, and for how long. */
export const IMPORT_POLL_MS = 2_000;
export const IMPORT_POLL_LIMIT_MS = 120_000;

export const IMPORT_FAILED = "Couldn't read the file — fill the form in by hand";
export const IMPORT_UPLOAD_FAILED = "The file could not be uploaded. Try again.";
export const IMPORT_UNUSABLE =
  "The imported file can't be used any more. Clear the import and try again.";

/** The form fields a file can suggest. */
export type ImportField = "title" | "customer_name" | "industry" | "products" | "target_proposal_date";

/** The form's values as typed: products one per line. */
export type FormValues = Record<ImportField, string>;

export const EMPTY_VALUES: FormValues = {
  title: "",
  customer_name: "",
  industry: "",
  products: "",
  target_proposal_date: "",
};

/** How a field was filled: quoted from the file, inferred from it (industry only), or the
 * default target proposal date when the file states no deadline. */
export type FillKind = "file" | "inferred" | "default";

/** Which fields were filled by the import: the value put in, its quote(s) (empty for the
 * default date) and how it was filled. */
export type FromFile = Partial<
  Record<ImportField, { value: string; quote: string; kind?: FillKind }>
>;

/** Days from today the default target proposal date falls on. */
export const DEFAULT_DATE_DAYS = 30;
export const DEFAULT_DATE_LABEL = "Default: 30 days from today, not in the file";

/** `today` (`YYYY-MM-DD`, UTC) plus `days`, as `YYYY-MM-DD`. */
export function addDays(today: string, days: number): string {
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** When the file gave no deadline and the date field is empty, propose today + 30 days,
 * marked as a default. A typed date or a deadline from the file wins. */
export function withDefaultDate(
  values: FormValues,
  fromFile: FromFile,
  today: string,
): { values: FormValues; fromFile: FromFile } {
  if (values.target_proposal_date.trim() !== "" || fromFile.target_proposal_date) {
    return { values, fromFile };
  }
  const value = addDays(today, DEFAULT_DATE_DAYS);
  return {
    values: { ...values, target_proposal_date: value },
    fromFile: { ...fromFile, target_proposal_date: { value, quote: "", kind: "default" } },
  };
}

/** Fill only the empty fields with the file's suggestions (a value the user already typed
 * wins). Returns the new values and the fields filled, each with its quote. Products are one
 * per line; their quotes are joined. */
export function applySuggestions(
  values: FormValues,
  suggestions: ImportSuggestions,
): { values: FormValues; fromFile: FromFile } {
  const next = { ...values };
  const fromFile: FromFile = {};
  const singles = ["title", "customer_name", "industry", "target_proposal_date"] as const;
  for (const field of singles) {
    const suggestion = suggestions[field];
    if (suggestion && values[field].trim() === "") {
      next[field] = suggestion.value;
      const kind = field === "industry" && suggestions.industry_inferred ? "inferred" : "file";
      fromFile[field] = { value: suggestion.value, quote: suggestion.quote, kind };
    }
  }
  const products = suggestions.products ?? [];
  if (products.length > 0 && values.products.trim() === "") {
    next.products = products.map((p) => p.value).join("\n");
    fromFile.products = {
      value: next.products,
      quote: products.map((p) => `${p.value}: “${p.quote}”`).join(" · "),
      kind: "file",
    };
  }
  return { values: next, fromFile };
}

/** Undo the import: fields still holding the file's value become empty again; anything the
 * user typed or changed stays. */
export function clearSuggestions(values: FormValues, fromFile: FromFile): FormValues {
  const next = { ...values };
  for (const [field, filled] of Object.entries(fromFile) as [
    ImportField,
    { value: string } | undefined,
  ][]) {
    if (filled && next[field] === filled.value) next[field] = "";
  }
  return next;
}

/** How many fields the file itself filled (the default date doesn't count). */
export function filledCount(fromFile: FromFile): number {
  return Object.values(fromFile).filter((f) => f && f.kind !== "default").length;
}

/** "1 field" / "3 fields" (the default date doesn't count). */
export function fieldCount(fromFile: FromFile): string {
  const n = filledCount(fromFile);
  return n === 1 ? "1 field" : `${n} fields`;
}
