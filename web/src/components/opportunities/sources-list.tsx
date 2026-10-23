"use client";

import {
  CircleAlertIcon,
  CircleCheckIcon,
  ClockIcon,
  FileTextIcon,
  MailIcon,
  MessageSquareReplyIcon,
  StickyNoteIcon,
  LoaderCircleIcon,
  MicIcon,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { loadSources, retryParse, type RetryParseResult } from "@/app/opportunities/actions";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyTabCard } from "@/components/ui/empty-tab-card";
import { Pill, type PillTone } from "@/components/ui/pill";
import { SourceInspector } from "@/components/opportunities/source-inspector";
import { SourceUpload, type SourceUploadHandle } from "@/components/opportunities/source-upload";
import { useAnnounce } from "@/components/shell/live-region";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import { useSourceEvents } from "@/lib/opportunity-events";
import {
  formatDateTime,
  CHOOSE_FILES,
  isParsePending,
  mergeSources,
  NO_SOURCES,
  NO_SOURCES_BODY,
  PARSE_POLL_LIMIT_MS,
  PARSE_POLL_MS,
  PARSE_STATUS_LABELS,
  parseFailureReason,
  parseSummary,
  sourceMeta,
  withSource,
  type Source,
  type SourceKind,
  type SourceParse,
} from "@/lib/sources";

const KIND_ICONS: Record<SourceKind, LucideIcon> = {
  email: MailIcon,
  note: StickyNoteIcon,
  transcript: MicIcon,
  document: FileTextIcon,
  clarification_answer: MessageSquareReplyIcon,
};

export const RETRY = "Retry";
export const PASTE_INSTEAD = "Paste text instead";
export const EXTRACTING_TEXT = "Extracting text";
const RETRY_FAILED = "The retry failed. Try again.";
const RETRY_NOT_ALLOWED = "Only the owner and collaborators can retry parsing.";

/** Row actions sit above the open button's stretched hit area. */
const actionClass = "relative z-10";

/** A Source version's parse state: an icon (or the running dot) and a label, never colour
 * alone. Parse failed has a red icon; its reason is shown next to it by the row. */
export function ParseStatusPill({ parse }: { parse: SourceParse }) {
  const label = PARSE_STATUS_LABELS[parse.status] ?? parse.status;
  let mark;
  let tone: PillTone = "neutral";
  switch (parse.status) {
    case "parsing":
      mark = <LoaderCircleIcon data-testid="running-dot" />;
      tone = "agent";
      break;
    case "parsed":
      mark = <CircleCheckIcon />;
      tone = "resolved";
      break;
    case "failed":
      mark = <CircleAlertIcon />;
      tone = "blocker";
      break;
    default:
      mark = <ClockIcon />;
  }
  return (
    <Pill data-status={parse.status} tone={tone} icon={mark} className="shrink-0">
      {label}
    </Pill>
  );
}

/** The indeterminate bar under a Parsing pill: the Assessments sweep (under reduced motion, a
 * still, pale full-width bar). The API reports no percentage. */
function ParsingBar() {
  return (
    <div className="flex w-full flex-col gap-0.5">
      <div
        aria-hidden="true"
        data-testid="parsing-bar"
        className="relative h-1.5 w-full overflow-hidden rounded-full bg-surface-alt"
      >
        <div className="h-full w-full animate-in duration-[1.6s] ease-in-out slide-in-from-left-full repeat-infinite motion-reduce:animate-none">
          <div className="ml-[60%] h-full w-2/5 rounded-full bg-primary motion-reduce:ml-0 motion-reduce:w-full motion-reduce:opacity-40" />
        </div>
      </div>
      <span className="text-meta text-text-secondary">{EXTRACTING_TEXT}</span>
    </div>
  );
}

/** The Opportunity's Sources card, newest first. Each row: the kind icon, file name and a meta
 * line (kind, version of count, size); the parse pill (with a bar while Parsing; the reason
 * and, for those who may add Sources, **Retry** and **Paste text instead** when it failed);
 * and the uploader and time of the latest version. With `onOpen`, each file name is a button
 * (one Tab stop per row) whose hit area covers the row; it opens the Source in the inspector,
 * by click or Enter. */
export function SourcesList({
  sources,
  canAdd = false,
  retrying = new Set<string>(),
  retryMessages = {},
  onRetry,
  onPasteInstead,
  onChooseFiles,
  selectedId = null,
  onOpen,
}: {
  sources: readonly Source[];
  canAdd?: boolean;
  /** The Source shown in the inspector. */
  selectedId?: string | null;
  /** `viaKeyboard` is true when the row was opened with Enter or Space, not a pointer. */
  onOpen?: (source: Source, viaKeyboard: boolean) => void;
  /** Sources whose Retry is in flight. */
  retrying?: ReadonlySet<string>;
  /** A Retry's failure sentence, by Source id. */
  retryMessages?: Readonly<Record<string, string>>;
  onRetry?: (source: Source) => void;
  onPasteInstead?: () => void;
  /** Opens the file chooser from the empty card; without it the card has no button. */
  onChooseFiles?: () => void;
}) {
  const headingId = useId();
  if (sources.length === 0) {
    return (
      <>
        <h2 className="sr-only">Sources</h2>
        <EmptyTabCard
          title={NO_SOURCES}
          body={NO_SOURCES_BODY}
          actionLabel={onChooseFiles ? CHOOSE_FILES : undefined}
          onClick={onChooseFiles}
        />
      </>
    );
  }
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-4">
        <h2 id={headingId} className="flex-1 text-section">
          Sources <span className="font-normal text-text-secondary">{sources.length}</span>
        </h2>
        <span className="text-meta text-text-secondary">{parseSummary(sources)}</span>
      </div>
      <ul aria-labelledby={headingId} className="flex flex-col">
        {sources.map((source) => {
          const Icon = KIND_ICONS[source.kind] ?? FileTextIcon;
          const status = source.parse?.status;
          const failed = status === "failed";
          const busy = retrying.has(source.id);
          const retryMessage = retryMessages[source.id];
          const selected = source.id === selectedId;
          return (
            <li
              key={source.id}
              data-selected={selected || undefined}
              className={`relative grid grid-cols-1 items-start gap-3 border-t border-border px-5 py-3.5 md:grid-cols-[minmax(0,1fr)_200px_120px] md:gap-4 ${selected ? "bg-primary-tint" : onOpen ? "hover:bg-muted/60" : ""}`}
            >
              <div className="flex min-w-0 gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-alt text-text-secondary">
                  <Icon aria-hidden className="size-[18px]" />
                </span>
                <div className="min-w-0">
                  {onOpen ? (
                    <button
                      type="button"
                      data-source-row=""
                      data-source-id={source.id}
                      aria-current={selected ? "true" : undefined}
                      // A keyboard-activated click has no pointer clicks (detail 0).
                      onClick={(event) => onOpen(source, event.detail === 0)}
                      className="text-left text-body-strong [overflow-wrap:anywhere] outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset"
                    >
                      {source.filename}
                    </button>
                  ) : (
                    <p className="text-body-strong [overflow-wrap:anywhere]">{source.filename}</p>
                  )}
                  <p className="text-meta text-text-secondary">{sourceMeta(source)}</p>
                </div>
              </div>
              <div className="flex flex-col items-start gap-1.5">
                {source.parse ? (
                  <>
                    <ParseStatusPill parse={source.parse} />
                    {status === "parsing" ? <ParsingBar /> : null}
                    {failed ? (
                      <>
                        <span className="text-meta text-blocker">
                          {parseFailureReason(source.parse.error_code)}
                        </span>
                        {canAdd ? (
                          <span className="flex flex-wrap gap-1.5">
                            {/* Retrying can't help a format with no parser yet. */}
                            {source.parse.error_code !== "not_supported" ? (
                              <Button
                                type="button"
                                variant="outline"
                                size="xs"
                                disabled={busy}
                                onClick={() => onRetry?.(source)}
                                aria-label={`${RETRY}: ${source.filename}`}
                                className={actionClass}
                              >
                                {RETRY}
                              </Button>
                            ) : null}
                            <Button
                              type="button"
                              variant="outline"
                              size="xs"
                              onClick={() => onPasteInstead?.()}
                              aria-label={`${PASTE_INSTEAD}: ${source.filename}`}
                              className={actionClass}
                            >
                              {PASTE_INSTEAD}
                            </Button>
                          </span>
                        ) : null}
                      </>
                    ) : null}
                  </>
                ) : null}
                {retryMessage ? (
                  <span className="text-meta text-destructive">{retryMessage}</span>
                ) : null}
              </div>
              <div className="min-w-0">
                <p className="text-body [overflow-wrap:anywhere]">{source.uploaded_by.name}</p>
                <p className="text-meta text-text-secondary">{formatDateTime(source.uploaded_at)}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
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
 * Story 2.3: the list follows the Opportunity's event stream: any `intake.source.*` frame,
 * or a (re)connect, re-reads it. Only while the stream isn't connected and a Source is Queued
 * or Parsing is the list re-read every 2 s instead: paused while the tab is hidden, and
 * stopped after 15 minutes of continuous pending. A selected row opens in the right pane's
 * inspector. */
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
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);
  const selected = sources.find((s) => s.id === selectedId) ?? null;

  /** Bumped as each re-read starts: only the latest-started one is applied, so a slower,
   * older response can't put back what a newer one showed. */
  const readSeq = useRef(0);

  /** Re-reads the list. One that a local change overtook (see `mutation`) is dropped and
   * run once more, so the stream's change still lands. */
  const reread = useCallback(() => {
    const run = async (again: boolean): Promise<void> => {
      const seq = ++readSeq.current;
      const startedAt = mutation.current;
      try {
        const result = await loadSources(opportunityId);
        if (seq !== readSeq.current || result.kind !== "ok") return;
        if (mutation.current !== startedAt) {
          if (again) await run(false);
          return;
        }
        setSources((current) => mergeSources(result.sources, current));
      } catch {
        // A failed re-read is retried on the next frame (or poll).
      }
    };
    return run(true);
  }, [opportunityId]);

  const live = useSourceEvents(opportunityId, () => void reread());

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(`[data-source-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function open(source: Source, viaKeyboard: boolean) {
    setSelectedId(source.id);
    returnFocusTo.current = viaKeyboard ? source.id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

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
    // The stream drives the pills while connected. Without it: paused while the tab is
    // hidden, and stopped once pending for too long.
    if (live || !visible || Date.now() - pendingSince.current >= PARSE_POLL_LIMIT_MS) return;
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
  }, [pending, visible, live, opportunityId, pollTick]);

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
    <div className="flex flex-col gap-4">
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
        onChooseFiles={canAdd ? () => uploadRef.current?.openChooser() : undefined}
        selectedId={selectedId}
        onOpen={open}
      />
      {selected ? (
        <RightPaneContent>
          <SourceInspector
            key={selected.id}
            opportunityId={opportunityId}
            source={selected}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </div>
  );
}
