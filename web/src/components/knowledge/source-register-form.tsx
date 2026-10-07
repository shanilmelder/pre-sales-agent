"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { registerSource, searchOwners, type SourceResult } from "@/app/knowledge/actions";
import { useAnnounce } from "@/components/shell/live-region";
import {
  ACCEPTED_FILES,
  exceedsTransportLimit,
  fieldError,
  PRODUCT_MAX,
  PRODUCT_VERSION_MAX,
  TITLE_MAX,
  TOO_LARGE,
  type KnowledgeSource,
} from "@/lib/knowledge-sources";

export type IntegrationTypeOption = { id: string; name: string };

const FAILED = "The upload failed. Try again.";
const NOT_ALLOWED = "You don't have access to register Knowledge Sources.";
const NO_TAGS = "Choose at least one Integration Type.";

const inputClass =
  "h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary";
const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

function failure(result: SourceResult): string | null {
  switch (result.kind) {
    case "ok":
      return null;
    case "rejected":
      return result.reason;
    case "invalid":
      return result.detail;
    case "forbidden":
      return NOT_ALLOWED;
    default:
      return FAILED;
  }
}

/** Register a Knowledge Source: a file (.pdf, .docx, .txt or .md, up to 50 MB), a title,
 * product, product version and at least one active Integration Type. The owner is the
 * person registering; administrators may pick someone else. The API decides what is
 * accepted and says why when it isn't ("Rejected: .exe files aren't allowed"). */
export function SourceRegisterForm({
  integrationTypes,
  isAdmin,
  onRegistered,
  onCancel,
}: {
  /** The active Integration Types that can be chosen as tags. */
  integrationTypes: readonly IntegrationTypeOption[];
  isAdmin: boolean;
  onRegistered: (source: KnowledgeSource) => void;
  /** `viaKey` is true when Esc closed it. */
  onCancel: (viaKey: boolean) => void;
}) {
  const announce = useAnnounce();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [product, setProduct] = useState("");
  const [productVersion, setProductVersion] = useState("");
  const [tagIds, setTagIds] = useState<ReadonlySet<string>>(new Set());
  const [ownerQuery, setOwnerQuery] = useState("");
  const [owners, setOwners] = useState<{ id: string; name: string }[]>([]);
  const [owner, setOwner] = useState<{ id: string; name: string } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const headingId = useId();
  const fileId = useId();
  const titleId = useId();
  const productId = useId();
  const versionId = useId();
  const ownerId = useId();

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  // Administrators look owners up by name or email (two characters or more).
  useEffect(() => {
    if (!isAdmin || ownerQuery.trim().length < 2) return;
    let live = true;
    const timer = setTimeout(() => {
      searchOwners(ownerQuery)
        .then((result) => {
          if (live && result.kind === "ok") setOwners(result.users);
        })
        .catch(() => {});
    }, 250);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [isAdmin, ownerQuery]);

  const shownOwners = ownerQuery.trim().length < 2 ? [] : owners;

  function validate(): Record<string, string> {
    const next: Record<string, string> = {};
    const checks = [
      ["title", fieldError("title", title)],
      ["product", fieldError("product", product)],
      ["productVersion", fieldError("product version", productVersion)],
    ] as const;
    for (const [name, error] of checks) if (error) next[name] = error;
    if (tagIds.size === 0) next.tags = NO_TAGS;
    if (!file) next.file = "Choose a file.";
    else if (exceedsTransportLimit(file.size)) next.file = TOO_LARGE;
    return next;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const found = validate();
    setErrors(found);
    setMessage(null);
    if (Object.keys(found).length > 0 || !file) {
      announce(Object.values(found)[0] ?? "Check the form.");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    form.append("product", product);
    form.append("productVersion", productVersion);
    if (owner) form.append("ownerId", owner.id);
    for (const id of tagIds) form.append("tagId", id);
    setBusy(true);
    let result: SourceResult;
    try {
      result = await registerSource(form);
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      announce(`Registered ${result.source.title}`);
      onRegistered(result.source);
      return;
    }
    const text = failure(result) ?? FAILED;
    if (result.kind === "rejected") setErrors({ file: text });
    else setMessage(text);
    announce(text);
  }

  function toggle(id: string) {
    setTagIds((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  return (
    <form
      aria-labelledby={headingId}
      onSubmit={submit}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !event.nativeEvent.isComposing && !busy) {
          event.preventDefault();
          event.stopPropagation();
          onCancel(true);
        }
      }}
      className="flex flex-col gap-3 p-gutter"
    >
      <h3 id={headingId} className="text-section">
        Register a Knowledge Source
      </h3>

      <div className="flex flex-col gap-1">
        <label htmlFor={fileId} className="text-label text-muted-foreground">
          File
        </label>
        <input
          ref={fileRef}
          id={fileId}
          type="file"
          accept={ACCEPTED_FILES}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          aria-invalid={errors.file ? true : undefined}
          aria-describedby={`${fileId}-hint`}
          className="text-body"
        />
        <p id={`${fileId}-hint`} className="text-meta text-muted-foreground">
          .pdf, .docx, .txt or .md, up to 50 MB
        </p>
        {errors.file ? <p className="text-meta text-destructive">{errors.file}</p> : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor={titleId} className="text-label text-muted-foreground">
          Title
        </label>
        <input
          ref={titleRef}
          id={titleId}
          type="text"
          value={title}
          maxLength={TITLE_MAX * 2}
          onChange={(event) => setTitle(event.target.value)}
          aria-invalid={errors.title ? true : undefined}
          className={inputClass}
        />
        {errors.title ? <p className="text-meta text-destructive">{errors.title}</p> : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor={productId} className="text-label text-muted-foreground">
          Product
        </label>
        <input
          id={productId}
          type="text"
          value={product}
          maxLength={PRODUCT_MAX * 2}
          onChange={(event) => setProduct(event.target.value)}
          aria-invalid={errors.product ? true : undefined}
          className={inputClass}
        />
        {errors.product ? <p className="text-meta text-destructive">{errors.product}</p> : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor={versionId} className="text-label text-muted-foreground">
          Product version
        </label>
        <input
          id={versionId}
          type="text"
          value={productVersion}
          maxLength={PRODUCT_VERSION_MAX * 2}
          onChange={(event) => setProductVersion(event.target.value)}
          aria-invalid={errors.productVersion ? true : undefined}
          className={inputClass}
        />
        {errors.productVersion ? (
          <p className="text-meta text-destructive">{errors.productVersion}</p>
        ) : null}
      </div>

      <fieldset className="flex flex-col gap-1">
        <legend className="text-label text-muted-foreground">Integration Types</legend>
        {integrationTypes.length === 0 ? (
          <p className="text-meta text-muted-foreground">
            No active Integration Types yet. An administrator adds them under Admin → Catalogue.
          </p>
        ) : (
          <ul className="flex max-h-40 flex-col overflow-y-auto">
            {integrationTypes.map((type) => (
              <li key={type.id}>
                <label className="flex min-h-row items-center gap-2 text-body">
                  <input
                    type="checkbox"
                    checked={tagIds.has(type.id)}
                    onChange={() => toggle(type.id)}
                  />
                  {type.name}
                </label>
              </li>
            ))}
          </ul>
        )}
        {errors.tags ? <p className="text-meta text-destructive">{errors.tags}</p> : null}
      </fieldset>

      {isAdmin ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={ownerId} className="text-label text-muted-foreground">
            Owner {owner ? `: ${owner.name}` : "(you, unless you pick someone)"}
          </label>
          <input
            id={ownerId}
            type="search"
            value={ownerQuery}
            placeholder="Find a person by name or email"
            onChange={(event) => setOwnerQuery(event.target.value)}
            className={inputClass}
          />
          {shownOwners.length > 0 ? (
            <ul aria-label="People" className="flex flex-col">
              {shownOwners.map((person) => (
                <li key={person.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setOwner(person);
                      setOwnerQuery("");
                      setOwners([]);
                    }}
                    className="h-row w-full rounded-sm px-1 text-left text-body outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    {person.name}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {owner ? (
            <button type="button" onClick={() => setOwner(null)} className={`${buttonClass} self-start`}>
              Use me as owner
            </button>
          ) : null}
        </div>
      ) : null}

      {message ? <p className="text-meta text-destructive">{message}</p> : null}
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className={buttonClass}>
          {busy ? "Uploading" : "Register"}
        </button>
        <button type="button" disabled={busy} onClick={() => onCancel(false)} className={buttonClass}>
          Cancel
        </button>
      </div>
    </form>
  );
}
