"use client";

import { CircleAlertIcon, QuoteIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  loadRequirements,
  startExtraction,
  type StartExtractionResult,
} from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import {
  EXTRACTING,
  EXTRACTION_POLL_LIMIT_MS,
  EXTRACTION_POLL_MS,
  extractionFailure,
  groupRequirements,
  isExtracting,
  NO_REQUIREMENTS,
  noneFound,
  requirementCount,
  STILL_EXTRACTING,
  TOO_MUCH_TEXT,
  type Extraction,
  type Requirement,
  type RequirementList,
} from "@/lib/requirements";

export const RETRY = "Retry";
const RETRY_FAILED = "The retry failed. Try again.";
const RETRY_NOT_ALLOWED = "Only the owner and collaborators can extract Requirements.";

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

/** A cited passage as a static label (`S1 · call.vtt`) in meta type. Part B makes it open
 * the passage. */
function EvidenceLabel({ label }: { label: string }) {
  return (
    <span className="inline-flex h-5 max-w-full items-center gap-1 rounded-sm border border-border bg-background px-1.5 text-meta text-muted-foreground">
      <QuoteIcon aria-hidden="true" className="size-3 shrink-0" />
      <span className="truncate">{label}</span>
    </span>
  );
}

/** The Requirements grouped by classification (Functional, Integration, Data, Security,
 * Non-functional, Commercial), each group headed by its label and count; empty groups are
 * hidden. Each row shows the text and its Evidence labels. */
export function RequirementsList({ items }: { items: readonly Requirement[] }) {
  const groups = groupRequirements(items);
  return (
    <div className="flex flex-col gap-6">
      {groups.map((group) => {
        const headingId = `requirements-${group.classification}`;
        return (
          <section key={group.classification} aria-labelledby={headingId}>
            <h3 id={headingId} className="mb-1 flex items-baseline gap-2 text-section">
              {group.label}{" "}
              <span className="text-meta text-numeric text-muted-foreground">
                {group.items.length}
              </span>
            </h3>
            <ul className="flex flex-col">
              {group.items.map((item) => (
                <li
                  key={item.id}
                  className="flex min-h-row flex-col gap-1 border-b border-border py-1.5"
                >
                  <span>{item.text}</span>
                  {item.evidence.length > 0 ? (
                    <span className="flex flex-wrap gap-1.5">
                      <span className="sr-only">Evidence:</span>
                      {item.evidence.map((evidence) => (
                        <EvidenceLabel key={evidence.passage_id} label={evidence.label} />
                      ))}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** The extraction's state above the list: "Extracting Requirements" with a running dot while
 * queued or running ("Still extracting — reload to check." once polling has stopped);
 * "Extraction failed: <reason>" with **Retry** (only for those who may start one; never for
 * too much text, which a retry can't fix) once failed; nothing otherwise. */
export function ExtractionStatus({
  extraction,
  canStart = false,
  busy = false,
  message = null,
  stalled = false,
  onRetry,
}: {
  extraction: Extraction | null;
  canStart?: boolean;
  /** Polling has stopped while still extracting. */
  stalled?: boolean;
  /** A Retry is in flight. */
  busy?: boolean;
  /** A Retry's failure sentence. */
  message?: string | null;
  onRetry?: () => void;
}) {
  if (isExtracting(extraction) && stalled) {
    return <p className="text-label text-muted-foreground">{STILL_EXTRACTING}</p>;
  }
  if (isExtracting(extraction)) {
    return (
      <p className="flex items-center gap-2 text-label" data-status={extraction?.status}>
        <span
          aria-hidden="true"
          data-testid="running-dot"
          className="size-1.5 shrink-0 animate-pulse rounded-full bg-agent motion-reduce:animate-none"
        />
        {EXTRACTING}
      </p>
    );
  }
  if (extraction?.status !== "failed") return null;
  return (
    <div className="flex flex-col items-start gap-1">
      <p className="flex items-center gap-1.5 text-label text-blocker" data-status="failed">
        <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
        {extractionFailure(extraction.error_code)}
      </p>
      {extraction.error_code === "input_too_large" ? (
        <span className="text-meta text-muted-foreground">{TOO_MUCH_TEXT}</span>
      ) : canStart ? (
        <button type="button" disabled={busy} onClick={() => onRetry?.()} className={actionClass}>
          {RETRY}
        </button>
      ) : null}
      {message ? <span className="text-meta text-destructive">{message}</span> : null}
    </div>
  );
}

function retryMessage(result: StartExtractionResult): string {
  switch (result.kind) {
    case "forbidden":
      return RETRY_NOT_ALLOWED;
    case "not-found":
      return NO_ACCESS_TO_OPPORTUNITY;
    default:
      return RETRY_FAILED;
  }
}

/** The Requirements tab's content. While an extraction is queued or running the list is
 * re-read every 2 s: paused while the tab is hidden, and stopped after 15 minutes. */
export function RequirementsSection({
  opportunityId,
  initial,
}: {
  opportunityId: string;
  initial: RequirementList;
}) {
  const announce = useAnnounce();
  const [list, setList] = useState<RequirementList>(initial);
  const [syncedFrom, setSyncedFrom] = useState(initial);
  /** Polling stopped at its limit while still extracting. */
  const [stalled, setStalled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  /** Bumped after every poll, so the next one is scheduled. */
  const [pollTick, setPollTick] = useState(0);
  /** Bumped on every local change (a Retry); a poll that started before one is dropped. */
  const mutation = useRef(0);
  const extractingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const extracting = isExtracting(list.extraction);

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setList(initial);
    setStalled(false);
  }

  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!extracting) {
      extractingSince.current = null;
      return;
    }
    extractingSince.current ??= Date.now();
    if (!visible || Date.now() - extractingSince.current >= EXTRACTION_POLL_LIMIT_MS) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const startedAt = mutation.current;
      try {
        const result = await loadRequirements(opportunityId);
        if (!cancelled && result.kind === "ok" && mutation.current === startedAt) {
          setList(result.list);
          if (!isExtracting(result.list.extraction)) {
            announce(
              result.list.extraction?.status === "failed"
                ? extractionFailure(result.list.extraction.error_code)
                : requirementCount(result.list.items.length),
            );
          }
        }
      } catch {
        // A failed poll is retried on the next tick.
      }
      if (cancelled) return;
      const since = extractingSince.current;
      if (since !== null && Date.now() - since >= EXTRACTION_POLL_LIMIT_MS) setStalled(true);
      setPollTick((tick) => tick + 1);
    }, EXTRACTION_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [extracting, visible, opportunityId, pollTick, announce]);

  async function retry() {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    let result: StartExtractionResult;
    try {
      result = await startExtraction(opportunityId);
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      const { extraction } = result;
      mutation.current += 1;
      extractingSince.current = null;
      setStalled(false);
      setList((current) => ({ ...current, extraction }));
      announce(EXTRACTING);
    } else if (result.kind === "conflict") {
      // One is already queued or running: show what is stored now.
      try {
        const loaded = await loadRequirements(opportunityId);
        if (loaded.kind === "ok") {
          mutation.current += 1;
          setList(loaded.list);
        }
      } catch {
        // The tab stays as it is.
      }
    } else {
      const sentence = retryMessage(result);
      setMessage(sentence);
      announce(sentence);
    }
  }

  const failed = list.extraction?.status === "failed";
  const succeeded = list.extraction?.status === "succeeded";
  return (
    <div className="flex flex-col gap-4">
      <ExtractionStatus
        extraction={list.extraction}
        canStart={list.can_start_extraction}
        busy={busy}
        message={message}
        stalled={stalled}
        onRetry={() => void retry()}
      />
      {list.items.length > 0 ? (
        <RequirementsList items={list.items} />
      ) : succeeded ? (
        <p className="text-muted-foreground">{noneFound(list.extraction?.source_count)}</p>
      ) : !extracting && !failed ? (
        <p className="text-muted-foreground">{NO_REQUIREMENTS}</p>
      ) : null}
    </div>
  );
}
