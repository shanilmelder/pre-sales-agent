"use client";

import {
  CaptionsIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  ClockIcon,
  FileTextIcon,
  MailIcon,
  StickyNoteIcon,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { loadSources, retryParse, type RetryParseResult } from "@/app/opportunities/actions";
import { SourceUpload, type SourceUploadHandle } from "@/components/opportunities/source-upload";
import { useAnnounce } from "@/components/shell/live-region";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import {
  formatDateTime,
  isParsePending,
  mergeSources,
  NO_SOURCES,
  PARSE_POLL_LIMIT_MS,
  PARSE_POLL_MS,
  PARSE_STATUS_LABELS,
  parseFailureReason,
  SOURCE_KIND_LABELS,
  withSource,
  type Source,
  type SourceKind,
  type SourceParse,
} from "@/lib/sources";

const KIND_ICONS: Record<SourceKind, LucideIcon> = {
  email: MailIcon,
  note: StickyNoteIcon,
  transcript: CaptionsIcon,
  document: FileTextIcon,
};

export const RETRY = "Retry";
export const PASTE_INSTEAD = "Paste text instead";
const RETRY_FAILED = "The retry failed. Try again.";
const RETRY_NOT_ALLOWED = "Only the owner and collaborators can retry parsing.";

const pillClass =
  "inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground";
const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

/** A Source version's parse state: an icon (or the running dot) and a label, never colour
 * alone. Parse failed has a red icon; its reason is shown next to it by the row. */
export function ParseStatusPill({ parse }: { parse: SourceParse }) {
  const label = PARSE_STATUS_LABELS[parse.status] ?? parse.status;
  let mark;
  switch (parse.status) {
    case "parsing":
      mark = (
        <span
          aria-hidden="true"
          data-testid="running-dot"
          className="mx-0.5 size-1.5 shrink-0 animate-pulse rounded-full bg-agent motion-reduce:animate-none"
        />
      );
      break;
    case "parsed":
      mark = <CircleCheckIcon aria-hidden="true" className="size-3 shrink-0 text-resolved" />;
      break;
    case "failed":
      mark = <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0 text-blocker" />;
      break;
    default:
      mark = <ClockIcon aria-hidden="true" className="size-3 shrink-0 text-muted-foreground" />;
  }
  return (
    <span className={pillClass} data-status={parse.status}>
      {mark}
      {label}
    </span>
  );
}

/** The Opportunity's Sources, newest first: kind, file name, version, parse status, uploader
 * and time (of the latest version). A failed parse shows its reason and, for those who may
 * add Sources, **Retry** and **Paste text instead**. */
export function SourcesList({
  sources,
  canAdd = false,
  retrying = new Set<string>(),
  retryMessages = {},
  onRetry,
  onPasteInstead,
}: {
  sources: readonly Source[];
  canAdd?: boolean;
  /** Sources whose Retry is in flight. */
  retrying?: ReadonlySet<string>;
  /** A Retry's failure sentence, by Source id. */
  retryMessages?: Readonly<Record<string, string>>;
  onRetry?: (source: Source) => void;
  onPasteInstead?: () => void;
}) {
  if (sources.length === 0) {
    return <p className="text-muted-foreground">{NO_SOURCES}</p>;
  }
  return (
    <table className="w-full table-fixed border-collapse text-left">
      <caption className="sr-only">Sources, newest first</caption>
      <thead className="text-label text-muted-foreground">
        <tr className="h-row border-b border-border">
          <th scope="col" className="w-32 pr-2 font-medium">
            Kind
          </th>
          <th scope="col" className="px-2 font-medium">
            File
          </th>
          <th scope="col" className="w-20 px-2 font-medium">
            Version
          </th>
          <th scope="col" className="w-72 px-2 font-medium">
            Status
          </th>
          <th scope="col" className="w-40 px-2 font-medium">
            Added by
          </th>
          <th scope="col" className="w-48 px-2 font-medium">
            Added
          </th>
        </tr>
      </thead>
      <tbody>
        {sources.map((source) => {
          const Icon = KIND_ICONS[source.kind] ?? FileTextIcon;
          const failed = source.parse?.status === "failed";
          const busy = retrying.has(source.id);
          const retryMessage = retryMessages[source.id];
          return (
            <tr key={source.id} className="h-row border-b border-border align-top">
              <td className="py-1.5 pr-2">
                <span className="inline-flex items-center gap-1.5">
                  <Icon aria-hidden className="size-3.5 text-muted-foreground" />
                  {SOURCE_KIND_LABELS[source.kind] ?? source.kind}
                </span>
              </td>
              <td className="truncate px-2 py-1.5" title={source.filename}>
                {source.filename}
              </td>
              <td className="px-2 py-1.5 text-numeric">v{source.version}</td>
              <td className="px-2 py-1.5">
                {source.parse ? (
                  <div className="flex flex-col items-start gap-1">
                    <ParseStatusPill parse={source.parse} />
                    {failed ? (
                      <>
                        <span className="text-meta text-blocker">
                          {parseFailureReason(source.parse.error_code)}
                        </span>
                        {canAdd ? (
                          <span className="flex flex-wrap gap-1.5">
                            {/* Retrying can't help a format with no parser yet. */}
                            {source.parse.error_code !== "not_supported" ? (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => onRetry?.(source)}
                                aria-label={`${RETRY}: ${source.filename}`}
                                className={actionClass}
                              >
                                {RETRY}
                              </button>
                            ) : null}
                            <button
                              type="button"
                              onClick={() => onPasteInstead?.()}
                              aria-label={`${PASTE_INSTEAD}: ${source.filename}`}
                              className={actionClass}
                            >
                              {PASTE_INSTEAD}
                            </button>
                          </span>
                        ) : null}
                      </>
                    ) : null}
                    {retryMessage ? (
                      <span className="text-meta text-destructive">{retryMessage}</span>
                    ) : null}
                  </div>
                ) : null}
              </td>
              <td className="truncate px-2 py-1.5">{source.uploaded_by.name}</td>
              <td className="px-2 py-1.5 text-numeric">{formatDateTime(source.uploaded_at)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function retryMessage(result: RetryParseResult): string | null {
  switch (result.kind) {
    case "ok":
    case "conflict":
      return null;
    case "forbidden":
      return RETRY_NOT_ALLOWED;
    case "not-found":
      return NO_ACCESS_TO_OPPORTUNITY;
    default:
      return RETRY_FAILED;
  }
}

/** The Sources tab's content: the upload area (only when the caller may add Sources; the
 * API decides on every upload) and the list, which takes each added Source as it lands.
 * While any Source is Queued or Parsing, the list is re-read every 2 s: paused while the
 * tab is hidden, and stopped after 15 minutes of continuous pending. */
export function SourcesSection({
  opportunityId,
  canAdd,
  initial,
}: {
  opportunityId: string;
  canAdd: boolean;
  initial: readonly Source[];
}) {
  const announce = useAnnounce();
  const [sources, setSources] = useState<Source[]>(() => [...initial]);
  const [retrying, setRetrying] = useState<ReadonlySet<string>>(() => new Set());
  const [retryMessages, setRetryMessages] = useState<Record<string, string>>({});
  /** Bumped after every poll (and to poll again at once), so the next one is scheduled. */
  const [pollTick, setPollTick] = useState(0);
  const uploadRef = useRef<SourceUploadHandle>(null);
  /** Bumped on every local change (an add, a Retry); a poll that started before one is
   * dropped, so it can't put back what the change replaced. */
  const mutation = useRef(0);
  /** When the list last became pending (reset by a local change); polling stops after
   * `PARSE_POLL_LIMIT_MS` of it. */
  const pendingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const pending = sources.some(isParsePending);

  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!pending) {
      pendingSince.current = null;
      return;
    }
    pendingSince.current ??= Date.now();
    // Paused while the tab is hidden; stopped once pending for too long.
    if (!visible || Date.now() - pendingSince.current >= PARSE_POLL_LIMIT_MS) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const startedAt = mutation.current;
      try {
        const result = await loadSources(opportunityId);
        if (!cancelled && result.kind === "ok" && mutation.current === startedAt) {
          setSources((current) => mergeSources(result.sources, current));
        }
      } catch {
        // A failed poll is retried on the next tick.
      }
      if (!cancelled) setPollTick((tick) => tick + 1);
    }, PARSE_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pending, visible, opportunityId, pollTick]);

  /** Applies a local change to the list (see `mutation`). */
  function change(update: (current: Source[]) => Source[]) {
    mutation.current += 1;
    pendingSince.current = null;
    setSources(update);
  }

  function setRetryMessage(id: string, message: string | null) {
    setRetryMessages((current) => {
      const next = { ...current };
      if (message === null) delete next[id];
      else next[id] = message;
      return next;
    });
  }

  async function retry(source: Source) {
    if (retrying.has(source.id)) return;
    setRetrying((current) => new Set(current).add(source.id));
    setRetryMessage(source.id, null);
    let result: RetryParseResult;
    try {
      result = await retryParse(opportunityId, source.id);
    } catch {
      result = { kind: "error" };
    }
    setRetrying((current) => {
      const next = new Set(current);
      next.delete(source.id);
      return next;
    });
    if (result.kind === "ok") {
      change((current) => withSource(current, result.source));
      announce(`${source.filename}: ${PARSE_STATUS_LABELS.queued}`);
    } else if (result.kind === "conflict") {
      // Someone else retried, or it already changed: show what is stored now.
      try {
        const listed = await loadSources(opportunityId);
        if (listed.kind === "ok") change((current) => mergeSources(listed.sources, current));
      } catch {
        // The list stays as it is.
      }
    } else {
      const message = retryMessage(result) ?? RETRY_FAILED;
      setRetryMessage(source.id, message);
      announce(`${source.filename}: ${message}`);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {canAdd ? (
        <SourceUpload
          ref={uploadRef}
          opportunityId={opportunityId}
          onAdded={(source) => change((current) => withSource(current, source))}
        />
      ) : null}
      <SourcesList
        sources={sources}
        canAdd={canAdd}
        retrying={retrying}
        retryMessages={retryMessages}
        onRetry={(source) => void retry(source)}
        onPasteInstead={() => uploadRef.current?.openPaste()}
      />
    </div>
  );
}
