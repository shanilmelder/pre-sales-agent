"use client";

import { FileUpIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useEffect,
  useId,
  useRef,
  useState,
  useTransition,
  type FormEvent,
  type ReactNode,
} from "react";

import {
  createOpportunity,
  importFile,
  loadImport,
  type CreateField,
  type CreateInput,
  type ImportFileResult,
} from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import {
  applySuggestions,
  clearSuggestions,
  EMPTY_VALUES,
  DEFAULT_DATE_LABEL,
  fieldCount,
  filledCount,
  IMPORT_ACCEPTED_FILES,
  IMPORT_FAILED,
  IMPORT_POLL_LIMIT_MS,
  IMPORT_POLL_MS,
  IMPORT_UNUSABLE,
  IMPORT_UPLOAD_FAILED,
  type FillKind,
  type FormValues,
  type FromFile,
  type ImportField,
  withDefaultDate,
} from "@/lib/opportunity-import";
import { codePointLength as len, utcToday } from "@/lib/opportunities";
import { exceedsTransportLimit, TOO_LARGE } from "@/lib/sources";

/** Field limits, mirroring the API's (which decides). */
const LIMITS = { title: 200, customer_name: 200, industry: 100, product: 100, products: 20 };

const FIELD_ORDER: readonly CreateField[] = [
  "title",
  "customer_name",
  "products",
  "industry",
  "target_proposal_date",
];

const SERVER_MESSAGES: Record<CreateField, string> = {
  title: `Use at most ${LIMITS.title} characters.`,
  customer_name: `Enter the customer name (at most ${LIMITS.customer_name} characters).`,
  products: `Enter 1 to ${LIMITS.products} products, one per line, each at most ${LIMITS.product} characters.`,
  industry: `Enter the industry (at most ${LIMITS.industry} characters).`,
  target_proposal_date: "Choose a date that is not in the past.",
};

type Errors = Partial<Record<CreateField, string>>;

/** Product names from the textarea: one per line, trimmed, blank lines dropped,
 * de-duplicated ignoring case (the first spelling wins). */
export function parseProducts(text: string): string[] {
  const seen = new Set<string>();
  const products: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    const name = line.trim();
    const key = name.toLocaleLowerCase();
    if (name && !seen.has(key)) {
      seen.add(key);
      products.push(name);
    }
  }
  return products;
}

/** Client-side checks so most mistakes show before a round trip. Lengths count code points
 * and `today` is the UTC date, as the API does. */
export function validate(input: CreateInput, today: string): Errors {
  const errors: Errors = {};
  if (len(input.title.trim()) > LIMITS.title) errors.title = SERVER_MESSAGES.title;
  const customer = input.customer_name.trim();
  if (!customer) errors.customer_name = "Enter the customer name.";
  else if (len(customer) > LIMITS.customer_name) {
    errors.customer_name = `Use at most ${LIMITS.customer_name} characters.`;
  }
  if (input.products.length === 0) errors.products = "Enter at least one product.";
  else if (input.products.length > LIMITS.products) {
    errors.products = `Enter at most ${LIMITS.products} products.`;
  } else if (input.products.some((p) => len(p) > LIMITS.product)) {
    errors.products = `Each product name can have at most ${LIMITS.product} characters.`;
  }
  const industry = input.industry.trim();
  if (!industry) errors.industry = "Enter the industry.";
  else if (len(industry) > LIMITS.industry) {
    errors.industry = `Use at most ${LIMITS.industry} characters.`;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input.target_proposal_date)) {
    errors.target_proposal_date = "Choose the target proposal date.";
  } else if (input.target_proposal_date < today) {
    errors.target_proposal_date = SERVER_MESSAGES.target_proposal_date;
  }
  return errors;
}

const inputClass =
  "h-8 w-full rounded-md border border-input bg-transparent px-2 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive";

const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

function Field({
  id,
  label,
  hint,
  error,
  fromFile,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  /** How the import filled this field and the quote it came from (none: typed or empty). */
  fromFile?: { quote: string; kind?: FillKind };
  children: ReactNode;
}) {
  const kind = fromFile?.kind ?? "file";
  return (
    <div className="group flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="text-label">
          {label}
        </label>
        {fromFile !== undefined ? (
          <span
            data-testid={`${id}-from-file`}
            className="rounded-sm bg-agent/10 px-1 text-meta text-foreground"
          >
            {kind === "inferred"
              ? "Inferred from file"
              : kind === "default"
                ? DEFAULT_DATE_LABEL
                : "From file"}
          </span>
        ) : null}
      </div>
      {children}
      {fromFile !== undefined && kind !== "default" ? (
        // Shown while the field is hovered or focused; always part of its description.
        <p
          id={`${id}-quote`}
          className="hidden text-meta text-muted-foreground group-focus-within:block group-hover:block"
        >
          {kind === "inferred"
            ? `Inferred from the file: “${fromFile.quote}”`
            : `From the file: “${fromFile.quote}”`}
        </p>
      ) : null}
      {hint ? (
        <p id={`${id}-hint`} className="text-meta text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="text-meta text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

type ImportState =
  | { kind: "none" }
  | { kind: "uploading"; filename: string }
  | { kind: "rejected"; message: string }
  | { kind: "reading"; id: string; filename: string; since: number }
  | { kind: "filled"; id: string; filename: string; count: string }
  | { kind: "failed"; id: string; filename: string }
  /** The API no longer has the import (404/410): its file won't be attached. */
  | { kind: "gone"; filename: string };

function importMessage(result: ImportFileResult): string {
  switch (result.kind) {
    case "rejected":
      return result.reason;
    case "forbidden":
      return "You don't have access to create Opportunities.";
    default:
      return IMPORT_UPLOAD_FAILED;
  }
}

/** New Opportunity: title (optional), customer, products, industry and target proposal
 * date. **Import from file** reads one email, transcript or document and fills the empty
 * fields with what it suggests, each marked "From file" with its quote; the file becomes the
 * Opportunity's first Source on Create. Field errors show inline and focus the first one; on
 * success it opens the new Opportunity. */
export function CreateOpportunityForm() {
  const router = useRouter();
  const announce = useAnnounce();
  const baseId = useId();
  const [values, setValues] = useState<FormValues>(EMPTY_VALUES);
  const [fromFile, setFromFile] = useState<FromFile>({});
  const [imported, setImported] = useState<ImportState>({ kind: "none" });
  const [pollTick, setPollTick] = useState(0);
  const valuesRef = useRef<FormValues>(EMPTY_VALUES);
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [today] = useState(() => utcToday());
  const fileInput = useRef<HTMLInputElement>(null);
  const importButton = useRef<HTMLButtonElement>(null);
  /** Bumped by Clear import and each new import, so a late answer can't fill the form. */
  const importSession = useRef(0);
  const ids = Object.fromEntries(FIELD_ORDER.map((f) => [f, `${baseId}-${f}`])) as Record<
    CreateField,
    string
  >;
  const importStatusId = `${baseId}-import-status`;

  const readingId = imported.kind === "reading" ? imported.id : null;
  const readingSince = imported.kind === "reading" ? imported.since : 0;
  const readingName = imported.kind === "reading" ? imported.filename : "";

  useEffect(() => {
    valuesRef.current = values;
  }, [values]);

  useEffect(() => {
    if (readingId === null) return;
    const session = importSession.current;
    /** The read gave nothing: still propose the default date if none is set. */
    const proposeDefaultDate = () => {
      const applied = withDefaultDate(valuesRef.current, {}, today);
      if (applied.values === valuesRef.current) return;
      setValues(applied.values);
      setFromFile(applied.fromFile);
    };
    const timer = setTimeout(async () => {
      if (Date.now() - readingSince >= IMPORT_POLL_LIMIT_MS) {
        proposeDefaultDate();
        setImported({ kind: "failed", id: readingId, filename: readingName });
        announce(IMPORT_FAILED);
        return;
      }
      let result: Awaited<ReturnType<typeof loadImport>>;
      try {
        result = await loadImport(readingId);
      } catch {
        result = { kind: "error" };
      }
      if (session !== importSession.current) return;
      if (result.kind === "ok" && result.import.status === "succeeded") {
        // Only empty fields fill: a value the user typed meanwhile wins.
        const suggested = applySuggestions(
          valuesRef.current,
          result.import.suggestions ?? { products: [], industry_inferred: false },
        );
        // No deadline in the file and none typed: propose today + 30 days, marked as such.
        const applied = withDefaultDate(suggested.values, suggested.fromFile, today);
        setValues(applied.values);
        setFromFile(applied.fromFile);
        const count = fieldCount(applied.fromFile);
        setImported({ kind: "filled", id: readingId, filename: readingName, count });
        announce(
          filledCount(applied.fromFile) === 0
            ? noFieldsRead(readingName)
            : `Filled ${count} from ${readingName}. Check them before you create.`,
        );
      } else if (result.kind === "ok" && result.import.status === "failed") {
        proposeDefaultDate();
        setImported({ kind: "failed", id: readingId, filename: readingName });
        announce(IMPORT_FAILED);
      } else if (result.kind === "gone") {
        setImported({ kind: "gone", filename: readingName });
        announce(importGone(readingName));
      } else {
        // Still queued or running (or a passing error): ask again.
        setPollTick((tick) => tick + 1);
      }
    }, IMPORT_POLL_MS);
    return () => clearTimeout(timer);
  }, [pollTick, readingId, readingSince, readingName, announce, today]);

  function change(field: ImportField, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    // An edited field is the user's own value now, no longer the file's.
    if (fromFile[field] && fromFile[field].value !== value) {
      setFromFile((current) => {
        const next = { ...current };
        delete next[field];
        return next;
      });
    }
  }

  async function startImport(file: File) {
    const session = ++importSession.current;
    // A new file replaces the previous import: its suggestions go (values the user typed
    // stay), and so does its file.
    setValues((current) => clearSuggestions(current, fromFile));
    setFromFile({});
    if (exceedsTransportLimit(file.size)) {
      setImported({ kind: "rejected", message: TOO_LARGE });
      announce(`${file.name}: ${TOO_LARGE}`);
      return;
    }
    setImported({ kind: "uploading", filename: file.name });
    const form = new FormData();
    form.append("file", file);
    let result: ImportFileResult;
    try {
      result = await importFile(form);
    } catch {
      result = { kind: "error" };
    }
    if (session !== importSession.current) return;
    if (result.kind === "ok") {
      setImported({
        kind: "reading",
        id: result.import.id,
        filename: result.import.filename,
        since: Date.now(),
      });
      announce(`Reading ${result.import.filename}`);
    } else {
      const message = importMessage(result);
      setImported({ kind: "rejected", message });
      announce(`${file.name}: ${message}`);
    }
  }

  function clearImport() {
    importSession.current++;
    setValues((current) => clearSuggestions(current, fromFile));
    setFromFile({});
    setImported({ kind: "none" });
    announce("Import cleared");
    importButton.current?.focus();
  }

  function showErrors(next: Errors) {
    setErrors(next);
    const first = FIELD_ORDER.find((field) => next[field]);
    if (first) {
      document.getElementById(ids[first])?.focus();
      announce(`Check the form: ${next[first]}`);
    }
  }

  const importId =
    imported.kind === "reading" || imported.kind === "filled" || imported.kind === "failed"
      ? imported.id
      : undefined;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // While a file uploads its import id isn't known yet: creating now would drop the file.
    if (pending || imported.kind === "uploading") return;
    const input: CreateInput = {
      title: values.title,
      customer_name: values.customer_name,
      products: parseProducts(values.products),
      industry: values.industry,
      target_proposal_date: values.target_proposal_date,
      ...(importId ? { importId } : {}),
    };
    setFormError(null);
    const found = validate(input, today);
    if (Object.keys(found).length > 0) {
      showErrors(found);
      return;
    }
    setErrors({});
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof createOpportunity>>;
      try {
        result = await createOpportunity(input);
      } catch {
        result = { kind: "error" };
      }
      switch (result.kind) {
        case "ok":
          announce("Opportunity created");
          router.push(`/opportunities/${result.id}`);
          return;
        case "invalid":
          if (result.fields.length > 0) {
            showErrors(Object.fromEntries(result.fields.map((f) => [f, SERVER_MESSAGES[f]])));
          } else {
            setFormError("Some fields are not valid. Check them and try again.");
          }
          return;
        case "import-unusable":
          setFormError(IMPORT_UNUSABLE);
          announce(IMPORT_UNUSABLE);
          return;
        case "forbidden":
          setFormError("You don't have access to create Opportunities.");
          announce("You don't have access to create Opportunities.");
          return;
        default:
          setFormError("The Opportunity could not be created. Try again.");
          announce("The Opportunity could not be created. Try again.");
      }
    });
  }

  function describedBy(field: CreateField, hint = false): string | undefined {
    const parts = [
      fromFile[field] ? `${ids[field]}-quote` : null,
      hint ? `${ids[field]}-hint` : null,
      errors[field] ? `${ids[field]}-error` : null,
    ];
    const joined = parts.filter(Boolean).join(" ");
    return joined || undefined;
  }

  const busy = imported.kind === "uploading" || imported.kind === "reading";
  const uploading = imported.kind === "uploading";
  const showClear =
    importId !== undefined || uploading || Object.keys(fromFile).length > 0;

  return (
    <form
      noValidate
      onSubmit={onSubmit}
      aria-busy={pending}
      className="flex max-w-xl flex-col gap-4 p-gutter"
    >
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <button
            ref={importButton}
            type="button"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
            aria-describedby={importStatusId}
            className={`${buttonClass} inline-flex items-center gap-1`}
          >
            <FileUpIcon aria-hidden className="size-3.5" />
            Import from file
          </button>
          {showClear ? (
            <button type="button" onClick={clearImport} className={buttonClass}>
              Clear import
            </button>
          ) : null}
        </div>
        <input
          ref={fileInput}
          type="file"
          accept={IMPORT_ACCEPTED_FILES}
          hidden
          tabIndex={-1}
          data-testid="import-file-input"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void startImport(file);
          }}
        />
        <p
          id={importStatusId}
          className={
            imported.kind === "rejected" || imported.kind === "failed" || imported.kind === "gone"
              ? "text-meta text-destructive"
              : "text-meta text-muted-foreground"
          }
        >
          {importStatus(imported)}
        </p>
      </div>
      <Field
        id={ids.customer_name}
        label="Customer name"
        error={errors.customer_name}
        fromFile={fromFile.customer_name}
      >
        <input
          id={ids.customer_name}
          name="customer_name"
          required
          autoFocus
          autoComplete="off"
          value={values.customer_name}
          onChange={(event) => change("customer_name", event.target.value)}
          aria-invalid={errors.customer_name ? true : undefined}
          aria-describedby={describedBy("customer_name")}
          className={inputClass}
        />
      </Field>
      <Field
        id={ids.title}
        label="Title (optional)"
        hint="Leave empty to use the customer name."
        error={errors.title}
        fromFile={fromFile.title}
      >
        <input
          id={ids.title}
          name="title"
          autoComplete="off"
          value={values.title}
          onChange={(event) => change("title", event.target.value)}
          aria-invalid={errors.title ? true : undefined}
          aria-describedby={describedBy("title", true)}
          className={inputClass}
        />
      </Field>
      <Field
        id={ids.products}
        label="Products in scope"
        hint={`One per line, up to ${LIMITS.products}.`}
        error={errors.products}
        fromFile={fromFile.products}
      >
        <textarea
          id={ids.products}
          name="products"
          required
          rows={4}
          value={values.products}
          onChange={(event) => change("products", event.target.value)}
          aria-invalid={errors.products ? true : undefined}
          aria-describedby={describedBy("products", true)}
          className="w-full rounded-md border border-input bg-transparent px-2 py-1 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive"
        />
      </Field>
      <Field
        id={ids.industry}
        label="Industry"
        error={errors.industry}
        fromFile={fromFile.industry}
      >
        <input
          id={ids.industry}
          name="industry"
          required
          autoComplete="off"
          value={values.industry}
          onChange={(event) => change("industry", event.target.value)}
          aria-invalid={errors.industry ? true : undefined}
          aria-describedby={describedBy("industry")}
          className={inputClass}
        />
      </Field>
      <Field
        id={ids.target_proposal_date}
        label="Target proposal date"
        error={errors.target_proposal_date}
        fromFile={fromFile.target_proposal_date}
      >
        <input
          id={ids.target_proposal_date}
          name="target_proposal_date"
          type="date"
          required
          min={today}
          value={values.target_proposal_date}
          onChange={(event) => change("target_proposal_date", event.target.value)}
          aria-invalid={errors.target_proposal_date ? true : undefined}
          aria-describedby={describedBy("target_proposal_date")}
          className={`${inputClass} w-48`}
        />
      </Field>
      {formError ? <p className="text-meta text-destructive">{formError}</p> : null}
      <div>
        <button
          type="submit"
          aria-disabled={pending || uploading || undefined}
          className="h-8 rounded-md bg-primary px-3 text-label text-primary-foreground outline-none hover:bg-primary/80 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
        >
          {pending ? "Creating…" : "Create Opportunity"}
        </button>
      </div>
    </form>
  );
}

function importStatus(state: ImportState): string {
  switch (state.kind) {
    case "none":
      return "An email, transcript or document: the empty fields fill in from it, and it becomes the first Source.";
    case "uploading":
      return `Uploading ${state.filename}…`;
    case "rejected":
      return state.message;
    case "reading":
      return `Reading ${state.filename}…`;
    case "filled":
      if (state.count === "0 fields") return noFieldsRead(state.filename);
      return `Filled ${state.count} from ${state.filename}. Check them before you create; ${state.filename} becomes the first Source.`;
    case "failed":
      return `${IMPORT_FAILED}. ${state.filename} still becomes the first Source unless you clear the import.`;
    case "gone":
      return importGone(state.filename);
  }
}

function noFieldsRead(filename: string): string {
  return `No fields could be read from ${filename}; it still becomes the first Source.`;
}

function importGone(filename: string): string {
  return `The import is no longer available: ${filename} won't be attached. Choose it again or continue by hand.`;
}
