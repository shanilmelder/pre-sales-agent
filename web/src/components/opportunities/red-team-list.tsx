"use client";

import { Link2Icon, ListChecksIcon, SigmaIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  loadRedTeam,
  startRedTeamReview,
  type StartRedTeamReviewResult,
} from "@/app/opportunities/actions";
import { Chip } from "@/components/ui/chip";
import { useAnnounce } from "@/components/shell/live-region";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import {
  findingCount,
  isReviewing,
  NOTHING_TO_REVIEW,
  REVIEW_POLL_LIMIT_MS,
  REVIEW_POLL_MS,
  reviewFailure,
  reviewLabel,
  REVIEWING,
  type RedTeamView,
} from "@/lib/red-team";

const RETRY_FAILED = "The retry failed. Try again.";
const RETRY_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can start a Red Team review.";

const COUNT_NOUNS = {
  requirement: [" Requirement", " Requirements"],
  line: [" Estimate line", " Estimate lines"],
  finding: [" cited Finding", " cited Findings"],
} as const;

/** A count chip: how many Requirements, Estimate lines or (Story 6.4, the Critic's) specialist
 * Findings the Finding cites. */
export function CountChip({
  count,
  kind,
}: {
  count: number;
  kind: "requirement" | "line" | "finding";
}) {
  const Icon = kind === "requirement" ? ListChecksIcon : kind === "line" ? SigmaIcon : Link2Icon;
  const noun = COUNT_NOUNS[kind][count === 1 ? 0 : 1];
  return (
    <Chip className="shrink-0">
      <Icon aria-hidden="true" className="size-3 shrink-0" />
      <span className="[font-variant-numeric:tabular-nums]">{count}</span>
      <span className="sr-only">{noun}</span>
    </Chip>
  );
}

function retryMessage(result: StartRedTeamReviewResult): string {
  switch (result.kind) {
    case "forbidden":
      return RETRY_NOT_ALLOWED;
    case "not-found":
      return NO_ACCESS_TO_OPPORTUNITY;
    default:
      return RETRY_FAILED;
  }
}

export type RedTeamState = {
  /** The Red Team view, or null when it could not be loaded. */
  view: RedTeamView | null;
  /** Polling has stopped while still reviewing. */
  stalled: boolean;
  /** A Retry is in flight. */
  busy: boolean;
  /** A Retry's failure sentence. */
  message: string | null;
  /** Start a new review (Retry). */
  retry: () => void;
};

/** The Assessments tab's Red Team state. While a review is queued or running it is re-read
 * every 2 s: paused while the tab is hidden, and stopped after 15 minutes. When the review
 * finishes the outcome is announced. Retry starts a new review; a 409 re-reads what is
 * stored. `initial` null (the read failed) gives a null view and no polling. */
export function useRedTeam(
  opportunityId: string,
  initial: RedTeamView | null,
): RedTeamState {
  const announce = useAnnounce();
  const [view, setView] = useState<RedTeamView | null>(initial);
  const [syncedFrom, setSyncedFrom] = useState(initial);
  const [stalled, setStalled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  /** Bumped after every poll, so the next one is scheduled. */
  const [pollTick, setPollTick] = useState(0);
  /** Bumped on every local change (a Retry); a poll that started before one is dropped. */
  const mutation = useRef(0);
  const reviewingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const reviewing = isReviewing(view?.run);

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setView(initial);
    setStalled(false);
  }

  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!reviewing) {
      reviewingSince.current = null;
      return;
    }
    reviewingSince.current ??= Date.now();
    if (!visible) return;
    if (Date.now() - reviewingSince.current >= REVIEW_POLL_LIMIT_MS) {
      // Past the limit (e.g. hidden through it): say so instead of pulsing forever.
      setStalled(true);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const startedAt = mutation.current;
      try {
        const result = await loadRedTeam(opportunityId);
        if (!cancelled && result.kind === "ok" && mutation.current === startedAt) {
          setView(result.redTeam);
          const { run, review } = result.redTeam;
          if (!isReviewing(run)) {
            announce(
              run?.status === "failed"
                ? reviewFailure(run.error_code)
                : review
                  ? `${reviewLabel(review)}: ${findingCount(review.findings.length)}`
                  : NOTHING_TO_REVIEW,
            );
          }
        }
      } catch {
        // A failed poll is retried on the next tick.
      }
      if (cancelled) return;
      const since = reviewingSince.current;
      if (since !== null && Date.now() - since >= REVIEW_POLL_LIMIT_MS) setStalled(true);
      setPollTick((tick) => tick + 1);
    }, REVIEW_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [reviewing, visible, opportunityId, pollTick, announce]);

  async function retry() {
    if (!view) return;
    if (busy) return;
    setBusy(true);
    setMessage(null);
    let result: StartRedTeamReviewResult;
    try {
      result = await startRedTeamReview(opportunityId);
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      const { run } = result;
      mutation.current += 1;
      reviewingSince.current = null;
      setStalled(false);
      setView((current) => (current ? { ...current, run } : current));
      announce(REVIEWING);
    } else if (result.kind === "conflict") {
      // One is already queued or running: show what is stored now.
      try {
        const loaded = await loadRedTeam(opportunityId);
        if (loaded.kind === "ok") {
          mutation.current += 1;
          setView(loaded.redTeam);
        }
      } catch {
        // The section stays as it is.
      }
    } else {
      const sentence = retryMessage(result);
      setMessage(sentence);
      announce(sentence);
    }
  }

  return {
    view,
    stalled,
    busy,
    message,
    retry: () => void retry(),
  };
}
