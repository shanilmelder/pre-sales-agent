"use client";

import { DownloadIcon } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { loadSourceText } from "@/app/opportunities/actions";
import { ParseStatusPill } from "@/components/opportunities/sources-list";
import { buttonVariants } from "@/components/ui/button";
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
    <section aria-labelledby={headingId} className="flex flex-col">
      <div className="flex flex-col items-start gap-2 border-b border-border p-gutter">
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-section [overflow-wrap:anywhere] outline-none"
        >
          {source.filename}
        </h3>
        {source.parse ? <ParseStatusPill parse={source.parse} /> : null}
        {failed ? (
          <p className="text-meta text-blocker">{parseFailureReason(source.parse?.error_code)}</p>
        ) : null}

        <dl className="mt-1.5 grid w-full grid-cols-[90px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-body">
          <dt className="text-text-secondary">Kind</dt>
          <dd>{SOURCE_KIND_LABELS[source.kind] ?? source.kind}</dd>
          <dt className="text-text-secondary">Version</dt>
          <dd className="text-numeric">
            v{source.version} of {source.version_count}
          </dd>
          <dt className="text-text-secondary">Size</dt>
          <dd className="text-numeric">{formatSize(source.size_bytes)}</dd>
          <dt className="text-text-secondary">Added by</dt>
          <dd className="[overflow-wrap:anywhere]">{source.uploaded_by.name}</dd>
          <dt className="text-text-secondary">Added</dt>
          <dd className="text-numeric">{formatDateTime(source.uploaded_at)}</dd>
        </dl>

        <a
          href={sourceDownloadHref(opportunityId, source.id, source.version)}
          download
          aria-label={`${DOWNLOAD_ORIGINAL}: ${source.filename}`}
          className={`${buttonVariants({ variant: "outline", size: "sm" })} mt-1.5 text-control`}
        >
          <DownloadIcon aria-hidden />
          {DOWNLOAD_ORIGINAL}
        </a>
      </div>

      <div className="flex flex-col gap-2 p-gutter">
        <h4 className="text-eyebrow text-text-secondary uppercase">
          Extracted text
        </h4>
        {!parsed ? (
          <p className="text-body text-text-secondary">
            {failed ? NO_TEXT_EXTRACTED : TEXT_PENDING}
          </p>
        ) : shown?.kind === "ok" ? (
          <pre
            tabIndex={0}
            aria-label={`Extracted text of ${source.filename}`}
            className="max-h-[60vh] overflow-auto rounded-lg border border-border bg-background p-3.5 font-sans text-body whitespace-pre-wrap outline-none focus-visible:ring-2 focus-visible:ring-primary"
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
