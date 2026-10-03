"use client";

import { useRouter } from "next/navigation";
import { useId, useState, useTransition, type FormEvent, type ReactNode } from "react";

import { createOpportunity, type CreateField, type CreateInput } from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { codePointLength as len, utcToday } from "@/lib/opportunities";

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

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-label">
        {label}
      </label>
      {children}
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

/** New Opportunity: title (optional), customer, products, industry and target proposal
 * date. Field errors show inline and focus the first one; on success it opens the new
 * Opportunity. */
export function CreateOpportunityForm() {
  const router = useRouter();
  const announce = useAnnounce();
  const baseId = useId();
  const [errors, setErrors] = useState<Errors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [today] = useState(() => utcToday());
  const ids = Object.fromEntries(FIELD_ORDER.map((f) => [f, `${baseId}-${f}`])) as Record<
    CreateField,
    string
  >;

  function showErrors(next: Errors) {
    setErrors(next);
    const first = FIELD_ORDER.find((field) => next[field]);
    if (first) {
      document.getElementById(ids[first])?.focus();
      announce(`Check the form: ${next[first]}`);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const data = new FormData(event.currentTarget);
    const input: CreateInput = {
      title: String(data.get("title") ?? ""),
      customer_name: String(data.get("customer_name") ?? ""),
      products: parseProducts(String(data.get("products") ?? "")),
      industry: String(data.get("industry") ?? ""),
      target_proposal_date: String(data.get("target_proposal_date") ?? ""),
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
    const parts = [hint ? `${ids[field]}-hint` : null, errors[field] ? `${ids[field]}-error` : null];
    const joined = parts.filter(Boolean).join(" ");
    return joined || undefined;
  }

  return (
    <form
      noValidate
      onSubmit={onSubmit}
      aria-busy={pending}
      className="flex max-w-xl flex-col gap-4 p-gutter"
    >
      <Field id={ids.customer_name} label="Customer name" error={errors.customer_name}>
        <input
          id={ids.customer_name}
          name="customer_name"
          required
          autoFocus
          autoComplete="off"
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
      >
        <input
          id={ids.title}
          name="title"
          autoComplete="off"
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
      >
        <textarea
          id={ids.products}
          name="products"
          required
          rows={4}
          aria-invalid={errors.products ? true : undefined}
          aria-describedby={describedBy("products", true)}
          className="w-full rounded-md border border-input bg-transparent px-2 py-1 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary aria-invalid:border-destructive"
        />
      </Field>
      <Field id={ids.industry} label="Industry" error={errors.industry}>
        <input
          id={ids.industry}
          name="industry"
          required
          autoComplete="off"
          aria-invalid={errors.industry ? true : undefined}
          aria-describedby={describedBy("industry")}
          className={inputClass}
        />
      </Field>
      <Field
        id={ids.target_proposal_date}
        label="Target proposal date"
        error={errors.target_proposal_date}
      >
        <input
          id={ids.target_proposal_date}
          name="target_proposal_date"
          type="date"
          required
          min={today}
          aria-invalid={errors.target_proposal_date ? true : undefined}
          aria-describedby={describedBy("target_proposal_date")}
          className={`${inputClass} w-48`}
        />
      </Field>
      {formError ? <p className="text-meta text-destructive">{formError}</p> : null}
      <div>
        <button
          type="submit"
          aria-disabled={pending || undefined}
          className="h-8 rounded-md bg-primary px-3 text-label text-primary-foreground outline-none hover:bg-primary/80 focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
        >
          {pending ? "Creating…" : "Create Opportunity"}
        </button>
      </div>
    </form>
  );
}
