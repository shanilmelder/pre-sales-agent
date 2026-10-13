"use client";

import { DownloadIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, useTransition } from "react";

import {
  addVersion,
  editSource,
  loadSource,
  loadText,
  markReviewed,
  retireSource,
  retryParse,
  type SourceResult,
} from "@/app/knowledge/actions";
import { RetiredLabel, StaleLabel } from "@/components/knowledge/sources-table";
import type { IntegrationTypeOption } from "@/components/knowledge/source-register-form";
import { InlineField } from "@/components/opportunities/inline-field";
import { ParseStatusPill } from "@/components/opportunities/sources-list";
import { useAnnounce } from "@/components/shell/live-region";
import type { Role } from "@/lib/navigation";
import {
  ACCEPTED_FILES,
  canWrite,
  exceedsTransportLimit,
  fieldError,
  formatDate,
  formatDateTime,
  formatSize,
  PRODUCT_VERSION_MAX,
  REASON_MAX,
  parseFailureReason,
  staleChangeMessage,
  TOO_LARGE,
  type KnowledgeSource,
  type KnowledgeSourceVersion,
} from "@/lib/knowledge-sources";

const SAVE_FAILED = "The change could not be saved. Try again.";
const NO_ACCESS = "Only a platform administrator or the owner can change this Source.";
const GONE = "This Knowledge Source no longer exists.";
const RETIRED = "This Knowledge Source is retired and can't be changed.";
const NO_TAGS = "Choose at least one Integration Type.";

type Notice = { kind: "stale" } | { kind: "error"; message: string };

const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";
const inputClass =
  "h-7 w-full rounded-md border border-input bg-transparent px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary";

/** The selected Knowledge Source in the right pane: its metadata, the version history with
 * a download link for every version, and the extracted text. Only a platform administrator
 * or the owner sees the actions: Mark reviewed, edit title, product and Integration Type
 * tags, upload a new version, Retire, and Retry for a failed parse. Writes carry the row
 * version as `If-Match`; a 412 shows a notice with Reload and overwrites nothing. */
export function SourceInspector({
  source,
  me,
  integrationTypes,
  onChange,
  focusRequest = 0,
}: {
  source: KnowledgeSource;
  me: { id: string; roles: readonly Role[] };
  /** The active Integration Types, for retagging. */
  integrationTypes: readonly IntegrationTypeOption[];
  /** Called with the Source as stored after a change or a reload. */
  onChange: (source: KnowledgeSource) => void;
  /** Bump to move keyboard focus to the inspector's heading (0: leave focus alone). */
  focusRequest?: number;
}) {
  const announce = useAnnounce();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [fieldFailure, setFieldFailure] = useState<{
    field: "title" | "product";
    text: string;
    error: string;
  } | null>(null);
  const [versions, setVersions] = useState<KnowledgeSourceVersion[] | null>(null);
  const [text, setText] = useState<{ version: number; body: string } | "loading" | "none" | null>(
    null,
  );
  const [pending, startTransition] = useTransition();
  const [retiring, setRetiring] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  // The tag boxes the user changed; null follows the stored tags (after a save or reload).
  const [tagEdits, setTagEdits] = useState<ReadonlySet<string> | null>(null);
  const [tagError, setTagError] = useState<string | null>(null);
  const [newVersion, setNewVersion] = useState(false);
  const [versionFile, setVersionFile] = useState<File | null>(null);
  const [productVersion, setProductVersion] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const headingId = useId();
  const reasonId = useId();
  const versionId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const reasonRef = useRef<HTMLInputElement>(null);
  const writable = canWrite(source, me);
  const stale = notice?.kind === "stale";
  const locked = pending || stale;
  const sourceId = source.id;
  const rowVersion = source.row_version;

  // The history of the Source shown; it is loaded again after every change.
  useEffect(() => {
    let live = true;
    loadSource(sourceId)
      .then((result) => {
        if (live && result.kind === "ok") setVersions(result.versions);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [sourceId, rowVersion]);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  useEffect(() => {
    if (stale) reloadRef.current?.focus();
  }, [stale]);

  useEffect(() => {
    if (retiring) reasonRef.current?.focus();
  }, [retiring]);

  const storedTagIds = source.integration_types.map((t) => t.id);
  const tagIds: ReadonlySet<string> = tagEdits ?? new Set(storedTagIds);

  function fail(next: Notice, spoken: string) {
    setNotice(next);
    announce(spoken);
  }

  /** Shows a failed write; true when it was a success. */
  function handle(result: SourceResult): boolean {
    switch (result.kind) {
      case "ok":
        return true;
      case "stale":
        fail({ kind: "stale" }, staleChangeMessage());
        return false;
      case "forbidden":
        fail({ kind: "error", message: NO_ACCESS }, NO_ACCESS);
        return false;
      case "not-found":
        fail({ kind: "error", message: GONE }, GONE);
        return false;
      case "conflict":
        fail({ kind: "error", message: RETIRED }, RETIRED);
        return false;
      case "invalid":
      case "rejected": {
        const message = result.kind === "invalid" ? result.detail : result.reason;
        fail({ kind: "error", message }, message);
        return false;
      }
      default:
        fail({ kind: "error", message: SAVE_FAILED }, SAVE_FAILED);
        return false;
    }
  }

  function run(
    call: () => Promise<SourceResult>,
    done: (next: KnowledgeSource) => void,
    spoken: (next: KnowledgeSource) => string,
  ) {
    if (locked) return;
    setNotice(null);
    startTransition(async () => {
      let result: SourceResult;
      try {
        result = await call();
      } catch {
        result = { kind: "error" };
      }
      if (handle(result) && result.kind === "ok") {
        onChange(result.source);
        done(result.source);
        announce(spoken(result.source));
      }
    });
  }

  function saveField(field: "title" | "product", value: string) {
    const invalid = fieldError(field, value);
    if (invalid) {
      setFieldFailure({ field, text: value, error: invalid });
      announce(invalid);
      return;
    }
    setFieldFailure(null);
    run(
      () => editSource({ sourceId, rowVersion, [field]: value }),
      () => {},
      (next) => `Saved ${field} of ${next.title}`,
    );
  }

  function saveTags() {
    if (tagIds.size === 0) {
      setTagError(NO_TAGS);
      announce(NO_TAGS);
      return;
    }
    setTagError(null);
    run(
      () => editSource({ sourceId, rowVersion, integrationTypeIds: [...tagIds] }),
      () => setTagEdits(null),
      (next) => `Saved Integration Types of ${next.title}`,
    );
  }

  function review() {
    run(
      () => markReviewed({ sourceId, rowVersion }),
      () => headingRef.current?.focus(),
      (next) => `Marked ${next.title} reviewed`,
    );
  }

  function retire() {
    const invalid = fieldError("reason", reason);
    if (invalid) {
      setReasonError(invalid);
      reasonRef.current?.focus();
      return;
    }
    setReasonError(null);
    run(
      () => retireSource({ sourceId, rowVersion, reason }),
      () => {
        setRetiring(false);
        setReason("");
        headingRef.current?.focus();
      },
      (next) => `Retired ${next.title}`,
    );
  }

  function retry() {
    run(
      () => retryParse(sourceId),
      () => {},
      (next) => `Parsing ${next.title} again`,
    );
  }

  function uploadVersion() {
    const invalidVersion = fieldError("product version", productVersion);
    if (invalidVersion || !versionFile) {
      setUploadError(invalidVersion ?? "Choose a file.");
      return;
    }
    if (exceedsTransportLimit(versionFile.size)) {
      setUploadError(TOO_LARGE);
      return;
    }
    setUploadError(null);
    const form = new FormData();
    form.append("file", versionFile);
    form.append("sourceId", sourceId);
    form.append("rowVersion", String(rowVersion));
    form.append("productVersion", productVersion);
    if (locked) return;
    setNotice(null);
    startTransition(async () => {
      let result: SourceResult;
      try {
        result = await addVersion(form);
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "rejected") {
        setUploadError(result.reason);
        announce(result.reason);
      } else if (handle(result) && result.kind === "ok") {
        onChange(result.source);
        setNewVersion(false);
        setVersionFile(null);
        setProductVersion("");
        setText(null);
        announce(`Added version ${result.source.version} of ${result.source.title}`);
        headingRef.current?.focus();
      }
    });
  }

  function reload() {
    if (pending) return;
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof loadSource>>;
      try {
        result = await loadSource(sourceId);
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok") {
        setNotice(null);
        setFieldFailure(null);
        setTagEdits(null);
        setVersions(result.versions);
        onChange(result.source);
        headingRef.current?.focus();
        announce(`Reloaded ${result.source.title}`);
      } else if (result.kind === "not-found") {
        fail({ kind: "error", message: GONE }, GONE);
      } else if (result.kind === "forbidden") {
        fail({ kind: "error", message: NO_ACCESS }, NO_ACCESS);
      } else {
        // Keep the stale notice (and its Reload button); nothing was overwritten.
        announce("The Source could not be reloaded. Try again.");
      }
    });
  }

  async function showText() {
    setText("loading");
    try {
      const result = await loadText(sourceId, source.version);
      setText(result.kind === "ok" ? { version: source.version, body: result.text } : "none");
    } catch {
      setText("none");
    }
  }

  const tagOptions = [
    ...integrationTypes.map((t) => ({ id: t.id, name: t.name, retired: false })),
    ...source.integration_types
      .filter((t) => !integrationTypes.some((o) => o.id === t.id))
      .map((t) => ({ id: t.id, name: t.name, retired: true })),
  ];
  const failed = source.parse.status === "failed";

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-section outline-none">
          {source.title}
        </h3>
        <div className="flex flex-wrap items-center gap-1">
          {source.stale ? <StaleLabel /> : null}
          {source.retired ? <RetiredLabel /> : null}
          <ParseStatusPill parse={source.parse} />
        </div>
        {failed ? (
          <p className="text-meta text-blocker">{parseFailureReason(source.parse.error_code)}</p>
        ) : null}
        {source.retired && source.retired_reason ? (
          <p className="text-meta">Retired: {source.retired_reason}</p>
        ) : null}
      </div>

      <div className="flex flex-col gap-3" aria-busy={pending}>
        <div className="flex flex-col gap-1">
          <span className="text-label text-muted-foreground">Title</span>
          {writable ? (
            <InlineField
              label="Edit title"
              inputLabel="Title"
              type="text"
              value={source.title}
              draft={fieldFailure?.field === "title" ? fieldFailure.text : undefined}
              error={fieldFailure?.field === "title" ? fieldFailure.error : null}
              locked={locked}
              onCommit={(next) => saveField("title", next)}
              inputClassName={inputClass}
            >
              <p className="min-h-6 py-0.5 text-body">{source.title}</p>
            </InlineField>
          ) : (
            <p className="min-h-6 py-0.5 text-body">{source.title}</p>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-label text-muted-foreground">Product</span>
          {writable ? (
            <InlineField
              label="Edit product"
              inputLabel="Product"
              type="text"
              value={source.product}
              draft={fieldFailure?.field === "product" ? fieldFailure.text : undefined}
              error={fieldFailure?.field === "product" ? fieldFailure.error : null}
              locked={locked}
              onCommit={(next) => saveField("product", next)}
              inputClassName={inputClass}
            >
              <p className="min-h-6 py-0.5 text-body">{source.product}</p>
            </InlineField>
          ) : (
            <p className="min-h-6 py-0.5 text-body">{source.product}</p>
          )}
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-body">
          <dt className="text-label text-muted-foreground">Owner</dt>
          <dd>{source.owner.name}</dd>
          <dt className="text-label text-muted-foreground">Last reviewed</dt>
          <dd className="text-numeric">{formatDate(source.last_reviewed_on)}</dd>
          <dt className="text-label text-muted-foreground">Version</dt>
          <dd>
            <span className="text-numeric">{source.version}</span> (product version{" "}
            <span className="text-numeric">{source.product_version}</span>)
          </dd>
          <dt className="text-label text-muted-foreground">File</dt>
          <dd className="break-all">
            {source.filename} <span className="text-meta">({formatSize(source.size_bytes)})</span>
          </dd>
        </dl>

        <fieldset className="flex flex-col gap-1" disabled={!writable || locked}>
          <legend className="text-label text-muted-foreground">Integration Types</legend>
          {writable ? (
            <>
              <ul className="flex max-h-40 flex-col overflow-y-auto">
                {tagOptions.map((option) => (
                  <li key={option.id}>
                    <label className="flex min-h-row items-center gap-2 text-body">
                      <input
                        type="checkbox"
                        checked={tagIds.has(option.id)}
                        onChange={() => {
                          const next = new Set(tagIds);
                          if (!next.delete(option.id)) next.add(option.id);
                          setTagEdits(next);
                        }}
                      />
                      {option.name}
                      {option.retired ? <RetiredLabel /> : null}
                    </label>
                  </li>
                ))}
              </ul>
              {tagError ? <p className="text-meta text-destructive">{tagError}</p> : null}
              <div>
                <button type="button" onClick={saveTags} className={buttonClass}>
                  Save tags
                </button>
              </div>
            </>
          ) : (
            <ul className="flex flex-col">
              {source.integration_types.map((t) => (
                <li key={t.id} className="flex min-h-6 items-center gap-2 text-body">
                  {t.name}
                  {t.retired ? <RetiredLabel /> : null}
                </li>
              ))}
            </ul>
          )}
        </fieldset>
      </div>

      {notice?.kind === "stale" ? (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border p-2">
          <p className="text-meta">{staleChangeMessage()}</p>
          <button
            type="button"
            ref={reloadRef}
            onClick={reload}
            aria-disabled={pending || undefined}
            className={buttonClass}
          >
            Reload
          </button>
        </div>
      ) : null}
      {notice?.kind === "error" ? <p className="text-meta text-destructive">{notice.message}</p> : null}

      {writable ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={review}
              aria-disabled={locked || undefined}
              className={buttonClass}
            >
              Mark reviewed
            </button>
            {failed && source.parse.error_code !== "not_supported" ? (
              <button
                type="button"
                onClick={retry}
                aria-disabled={locked || undefined}
                className={buttonClass}
              >
                Retry
              </button>
            ) : null}
            <button
              type="button"
              aria-expanded={newVersion}
              onClick={() => setNewVersion((open) => !open)}
              className={buttonClass}
            >
              Upload new version
            </button>
            {!retiring ? (
              <button type="button" onClick={() => setRetiring(true)} className={buttonClass}>
                Retire
              </button>
            ) : null}
          </div>

          {newVersion ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={`${versionId}-file`} className="text-label text-muted-foreground">
                New file
              </label>
              <input
                id={`${versionId}-file`}
                type="file"
                accept={ACCEPTED_FILES}
                onChange={(event) => setVersionFile(event.target.files?.[0] ?? null)}
                className="text-body"
              />
              <label htmlFor={versionId} className="text-label text-muted-foreground">
                Product version
              </label>
              <input
                id={versionId}
                type="text"
                value={productVersion}
                maxLength={PRODUCT_VERSION_MAX * 2}
                onChange={(event) => setProductVersion(event.target.value)}
                className={inputClass}
              />
              {uploadError ? <p className="text-meta text-destructive">{uploadError}</p> : null}
              <div>
                <button
                  type="button"
                  onClick={uploadVersion}
                  aria-disabled={locked || undefined}
                  className={buttonClass}
                >
                  Upload
                </button>
              </div>
            </div>
          ) : null}

          {retiring ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={reasonId} className="text-label text-muted-foreground">
                Reason for retiring
              </label>
              <input
                id={reasonId}
                ref={reasonRef}
                type="text"
                value={reason}
                maxLength={REASON_MAX * 2}
                aria-invalid={reasonError ? true : undefined}
                onChange={(event) => setReason(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    retire();
                  } else if (event.key === "Escape") {
                    event.preventDefault();
                    event.stopPropagation();
                    setRetiring(false);
                    setReasonError(null);
                  }
                }}
                className={inputClass}
              />
              {reasonError ? <p className="text-meta text-destructive">{reasonError}</p> : null}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={retire}
                  aria-disabled={locked || undefined}
                  className={buttonClass}
                >
                  Confirm retire
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setRetiring(false);
                    setReasonError(null);
                  }}
                  className={buttonClass}
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Version history</h4>
        {versions === null ? (
          <p className="text-meta text-muted-foreground">Loading</p>
        ) : (
          <ul className="flex flex-col">
            {versions.map((v) => (
              <li
                key={v.version}
                className="flex min-h-row flex-wrap items-center justify-between gap-x-3 border-b border-border py-1"
              >
                <span className="min-w-0 text-body">
                  <span className="text-numeric">v{v.version}</span> · product{" "}
                  <span className="text-numeric">{v.product_version}</span> · {v.filename}
                  <span className="block text-meta text-muted-foreground">
                    {formatSize(v.size_bytes)} · {v.uploaded_by.name} · {formatDateTime(v.uploaded_at)}
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  <ParseStatusPill parse={v.parse} />
                  <a
                    href={`/api/knowledge/sources/${source.id}/versions/${v.version}/download`}
                    aria-label={`Download version ${v.version}: ${v.filename}`}
                    className="inline-flex h-6 items-center gap-1 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    <DownloadIcon aria-hidden className="size-3" />
                    Download
                  </a>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Extracted text</h4>
        {source.parse.status !== "parsed" ? (
          <p className="text-meta text-muted-foreground">
            {failed ? "No text was extracted from this version." : "Available once parsing finishes."}
          </p>
        ) : text && text !== "loading" && text !== "none" && text.version === source.version ? (
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border border-border p-2 text-body">
            {text.body}
          </pre>
        ) : text === "none" ? (
          <p className="text-meta text-destructive">The text could not be loaded.</p>
        ) : (
          <div>
            <button
              type="button"
              onClick={showText}
              aria-disabled={text === "loading" || undefined}
              className={buttonClass}
            >
              {text === "loading" ? "Loading" : "Show extracted text"}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
