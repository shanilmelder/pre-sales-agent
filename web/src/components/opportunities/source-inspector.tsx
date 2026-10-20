"use client";

import { DownloadIcon } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { loadSourceText } from "@/app/opportunities/actions";
import { ParseStatusPill } from "@/components/opportunities/sources-list";
import { formatSize } from "@/lib/knowledge-sources";
import {
  formatDateTime,
  NO_TEXT_EXTRACTED,
  parseFailureReason,
  SOURCE_KIND_LABELS,
  sourceDownloadHref,
  TEXT_LOAD_FAILED,
  TEXT_PENDING,
  type Source,
} from "@/lib/sources";

export const DOWNLOAD_ORIGINAL = "Download original";

/** The loaded text, for the version `key` (`<source id>:<version>`); none yet: loading. */
type Text =
  | { kind: "ok"; key: string; body: string }
  | { kind: "failed"; key: string };

/** The selected Opportunity Source in the right pane (Story 2.3): its kind, file name,
 * version, size, who added it and when, and its parse pill (with the reason when it failed);
 * the extracted text, loaded by itself once the version is parsed; and **Download original**
 * (the version's file, unchanged, through the same-origin download route). Read-only: anyone
 * who can read the Opportunity sees the same. */
export function SourceInspector({
  opportunityId,
  source,
  focusRequest = 0,
}: {
  opportunityId: string;
  source: Source;
  /** Bump to move keyboard focus to the inspector's heading (0: leave focus alone). */
  focusRequest?: number;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [text, setText] = useState<Text | null>(null);
  const status = source.parse?.status ?? null;
  const failed = status === "failed";
  const parsed = status === "parsed";
  const key = `${source.id}:${source.version}`;

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  // The text of the version shown, loaded once it is parsed (again for a newer version).
  useEffect(() => {
    if (!parsed) return;
    let live = true;
    loadSourceText(opportunityId, source.id, source.version)
      .then((result) => {
        if (!live) return;
        setText(result.kind === "ok" ? { kind: "ok", key, body: result.text } : { kind: "failed", key });
      })
      .catch(() => {
        if (live) setText({ kind: "failed", key });
      });
    return () => {
      live = false;
    };
  }, [opportunityId, source.id, source.version, parsed, key]);

  const shown = text?.key === key ? text : null;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-section break-all outline-none"
        >
          {source.filename}
        </h3>
        {source.parse ? (
          <div className="flex flex-wrap items-center gap-1">
            <ParseStatusPill parse={source.parse} />
          </div>
        ) : null}
        {failed ? (
          <p className="text-meta text-blocker">{parseFailureReason(source.parse?.error_code)}</p>
        ) : null}
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-body">
        <dt className="text-label text-muted-foreground">Kind</dt>
        <dd>{SOURCE_KIND_LABELS[source.kind] ?? source.kind}</dd>
        <dt className="text-label text-muted-foreground">Version</dt>
        <dd className="text-numeric">
          v{source.version} of {source.version_count}
        </dd>
        <dt className="text-label text-muted-foreground">Size</dt>
        <dd className="text-numeric">{formatSize(source.size_bytes)}</dd>
        <dt className="text-label text-muted-foreground">Added by</dt>
        <dd>{source.uploaded_by.name}</dd>
        <dt className="text-label text-muted-foreground">Added</dt>
        <dd className="text-numeric">{formatDateTime(source.uploaded_at)}</dd>
      </dl>

      <div>
        <a
          href={sourceDownloadHref(opportunityId, source.id, source.version)}
          download
          aria-label={`${DOWNLOAD_ORIGINAL}: ${source.filename}`}
          className="inline-flex h-7 items-center gap-1 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
        >
          <DownloadIcon aria-hidden className="size-3" />
          {DOWNLOAD_ORIGINAL}
        </a>
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-label text-muted-foreground">Extracted text</h4>
        {!parsed ? (
          <p className="text-meta text-muted-foreground">
            {failed ? NO_TEXT_EXTRACTED : TEXT_PENDING}
          </p>
        ) : shown?.kind === "ok" ? (
          <pre
            tabIndex={0}
            aria-label={`Extracted text of ${source.filename}`}
            className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md border border-border p-2 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            {shown.body}
          </pre>
        ) : shown?.kind === "failed" ? (
          <p className="text-meta text-destructive">{TEXT_LOAD_FAILED}</p>
        ) : (
          <p className="text-meta text-muted-foreground" aria-busy="true">
            Loading
          </p>
        )}
      </div>
    </section>
  );
}
