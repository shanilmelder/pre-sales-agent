"use client";

import { CheckIcon, MessageSquareWarningIcon, RedoIcon, RefreshCwIcon } from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import {
  confirmChallenge,
  declineChallenge,
  loadChallenge,
  loadChallengeSuggestions,
  raiseChallenge,
  type ChallengeLoad,
  type ChallengeResult,
} from "@/app/opportunities/actions";
import { ReasonInput } from "@/components/opportunities/reason-input";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Pill } from "@/components/ui/pill";
import { Textarea } from "@/components/ui/textarea";
import { codePointLength } from "@/lib/opportunities";
import {
  ALWAYS_RERUN_LINE,
  ASSESSMENTS_TO_RERUN,
  CANCEL,
  CHALLENGE,
  CHALLENGE_DECLINED,
  CHALLENGE_FAILED,
  CHALLENGE_FORBIDDEN,
  CHALLENGE_HELPER,
  CHALLENGE_NOT_LOADED,
  CHALLENGE_RAISED,
  CHALLENGE_REASON_LABEL,
  CHALLENGE_REASON_MAX,
  CHALLENGE_REASON_PLACEHOLDER,
  CHALLENGE_STALE,
  CHALLENGE_STATUSES,
  CLOSE,
  CONFIRM_DECLINE,
  DECLINE,
  DECLINE_REASON_LABEL,
  LOADING_CHALLENGE,
  RAISE_CHALLENGE,
  REASSESSMENT_STARTED,
  SUGGESTION_TAGS,
  challengeSupersededDetail,
  challengerReasonLabel,
  raiseOnLabel,
  reassessmentLabel,
  rerunLabel,
  type ChallengeStatus,
  type ChallengeSuggestion,
  type ChallengeSuggestions,
  type ChallengeTargetKind,
  type ChallengeView,
} from "@/lib/reviews";
import { cn } from "@/lib/utils";
import { tabHref } from "@/lib/workspace";

/** What a Challenge targets: an Estimate Version, an Assessment or one of its Findings. */
export type ChallengeTarget = { kind: ChallengeTargetKind; id: string };

/** What the dialog does: raise a new Challenge of `target` (optionally from the caller's
 * Review Request, with a prefilled reason), or show an existing one (the owner confirms or
 * declines it there). */
export type ChallengeMode =
  | { kind: "raise"; target: ChallengeTarget; reviewRequestId?: string; reason?: string }
  | { kind: "existing"; challengeId: string };

/** A Challenge's status as a pill: its icon and label, never colour alone. */
export function ChallengeStatusPill({ status }: { status: ChallengeStatus }) {
  const style = CHALLENGE_STATUSES[status];
  const Icon = style.icon;
  return (
    <Pill tone={style.tone} icon={<Icon />} data-challenge-status={status} className="shrink-0">
      {style.label}
    </Pill>
  );
}

/** One `aria-pressed` toggle card per suggested Assessment (the mockup's `dlgChallenge`
 * cards, as in the Request review dialog): the agent, why it is affected and its tag. When
 * not `editable` the cards only inform (`aria-disabled`). */
function SuggestionCards({
  suggestions,
  ticked,
  editable,
  busy,
  onToggle,
}: {
  suggestions: ChallengeSuggestion[];
  ticked: string[];
  editable: boolean;
  busy: boolean;
  onToggle: (agent: string) => void;
}) {
  const headingId = useId();
  return (
    <div role="group" aria-labelledby={headingId} className="flex flex-col gap-1.5">
      <h3 id={headingId} className="text-muted-foreground uppercase">
        <span className="text-eyebrow">{ASSESSMENTS_TO_RERUN}</span>
      </h3>
      {suggestions.map((s) => {
        const on = ticked.includes(s.agent);
        return (
          <button
            key={s.agent}
            type="button"
            aria-pressed={on}
            aria-disabled={editable ? undefined : true}
            disabled={busy}
            data-suggestion-card={s.agent}
            onClick={() => {
              if (editable) onToggle(s.agent);
            }}
            className={cn(
              "flex items-center gap-3 rounded-lg border px-3 py-2.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary",
              on
                ? "border-primary bg-primary-tint"
                : "border-border-strong bg-transparent",
              !editable && "cursor-default",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "flex size-[18px] shrink-0 items-center justify-center rounded-[5px] border-[1.5px]",
                on ? "border-primary bg-primary text-primary-foreground" : "border-border-strong",
              )}
            >
              {on ? <CheckIcon className="size-3" /> : null}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-body-strong">{s.label}</span>
              <span className="block text-meta text-text-secondary">{s.why}</span>
            </span>
            <span className="shrink-0 text-meta font-medium text-primary-text">
              {SUGGESTION_TAGS[s.tag]}
            </span>
          </button>
        );
      })}
      <p className="flex items-center gap-2 text-meta text-text-secondary" data-always-rerun="">
        <RefreshCwIcon aria-hidden="true" className="size-3.5 shrink-0" />
        {ALWAYS_RERUN_LINE}
      </p>
    </div>
  );
}

type Problem = { kind: "stale" } | { kind: "message"; text: string };

function problemOf(result: Exclude<ChallengeResult, { kind: "ok" }>): Problem {
  switch (result.kind) {
    case "stale":
      return { kind: "stale" };
    case "invalid":
      return { kind: "message", text: result.detail };
    case "forbidden":
      return { kind: "message", text: result.detail ?? CHALLENGE_FORBIDDEN };
    case "not-found":
      return { kind: "message", text: CHALLENGE_FORBIDDEN };
    default:
      return { kind: "message", text: CHALLENGE_FAILED };
  }
}

type Loaded =
  | { kind: "suggestions"; value: ChallengeSuggestions }
  | { kind: "challenge"; value: ChallengeView };

type Loadable = ChallengeLoad<ChallengeSuggestions> | ChallengeLoad<ChallengeView>;

/** Reads what the form shows for `mode`; never throws. */
async function fetchLoadable(opportunityId: string, mode: ChallengeMode): Promise<Loadable> {
  try {
    return mode.kind === "raise"
      ? await loadChallengeSuggestions({
          opportunityId,
          targetKind: mode.target.kind,
          targetId: mode.target.id,
        })
      : await loadChallenge({ opportunityId, challengeId: mode.challengeId });
  } catch {
    return { kind: "error" };
  }
}

function preselected(suggestions: ChallengeSuggestion[]): string[] {
  return suggestions.filter((s) => s.preselected).map((s) => s.agent);
}

/** The run line once a reassessment started: "Reassessment started (run 4)" with a link to
 * the Assessments tab, where the run header shows it. */
function RunLine({ opportunityId, view }: { opportunityId: string; view: ChallengeView }) {
  return (
    <p className="flex flex-wrap items-center gap-2 text-body" data-challenge-run="">
      <span>{reassessmentLabel(view.run_number)}</span>
      <Link
        href={tabHref(opportunityId, "assessments")}
        className="text-body-strong text-primary-text outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
      >
        Open Assessments
      </Link>
    </p>
  );
}

/** The Challenge form (Story 9.5; the mockup's 520px `dlgChallenge`), in a dialog or inline
 * (the Inbox detail pane). One form serves every role, from the API's flags:
 *
 * - **Reviewer raising:** "Reason (required)", the suggested cards for information only
 *   (`aria-disabled`) and **Raise Challenge**, disabled until a reason is typed.
 * - **Owner raising:** the cards are editable and **Rerun N Assessments** (disabled until a
 *   reason and one tick) raises and confirms at once.
 * - **Owner confirming** (an existing Challenge): the reviewer's reason read-only, editable
 *   cards, **Rerun N Assessments** and **Decline**, which reveals a required reason. When the
 *   version in context was superseded it shows the blocked sentence and **Raise on v4** (a
 *   new Challenge on the current version, the reason prefilled).
 *
 * "Critic and Red Team always rerun" is a line, never a card. A 412 shows the inline alert
 * with Reload. Success announces "Challenge raised", "Reassessment started" or "Challenge
 * declined" and shows the run line with a link to the Assessments tab. */
export function ChallengeForm({
  opportunityId,
  mode: initialMode,
  layout,
  onDone,
}: {
  opportunityId: string;
  mode: ChallengeMode;
  layout: "dialog" | "inline";
  /** After a raise, confirm or decline (the form shows the outcome). */
  onDone?: (view: ChallengeView) => void;
}) {
  const announce = useAnnounce();
  const reasonId = useId();
  const reasonRuleId = useId();
  const headingId = useId();
  const [mode, setMode] = useState<ChallengeMode>(initialMode);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [reason, setReason] = useState(
    initialMode.kind === "raise" ? (initialMode.reason ?? "") : "",
  );
  const [ticked, setTicked] = useState<string[]>([]);
  const [declining, setDeclining] = useState(false);
  const [declineReason, setDeclineReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [done, setDone] = useState<ChallengeView | null>(null);
  const declineRef = useRef<HTMLTextAreaElement>(null);

  const apply = useCallback((next: ChallengeMode, result: Loadable) => {
    if (result.kind === "ok") {
      const fresh: Loaded =
        next.kind === "raise"
          ? { kind: "suggestions", value: result.value as ChallengeSuggestions }
          : { kind: "challenge", value: result.value as ChallengeView };
      setLoaded(fresh);
      setTicked(
        fresh.kind === "challenge" && fresh.value.confirmed
          ? fresh.value.confirmed
          : preselected(fresh.value.suggested),
      );
      setLoadProblem(null);
    } else {
      setLoadProblem(result.kind === "invalid" ? result.detail : CHALLENGE_NOT_LOADED);
    }
  }, []);

  const read = useCallback(
    async (next: ChallengeMode) => apply(next, await fetchLoadable(opportunityId, next)),
    [opportunityId, apply],
  );

  useEffect(() => {
    let cancelled = false;
    fetchLoadable(opportunityId, mode).then((result) => {
      if (!cancelled) apply(mode, result);
    });
    return () => {
      cancelled = true;
    };
  }, [opportunityId, mode, apply]);

  useEffect(() => {
    if (declining) declineRef.current?.focus();
  }, [declining]);

  function toggle(agent: string) {
    setTicked((now) => (now.includes(agent) ? now.filter((a) => a !== agent) : [...now, agent]));
  }

  function fail(result: Exclude<ChallengeResult, { kind: "ok" }>) {
    const next = problemOf(result);
    setProblem(next);
    announce(next.kind === "stale" ? CHALLENGE_STALE : next.text);
    // A version superseded under the form: read the Challenge again to show the block.
    if (result.kind === "invalid" && result.code === "challenge_version_superseded") {
      void read(mode);
    }
  }

  function succeed(view: ChallengeView, announcement: string) {
    announce(announcement);
    setDone(view);
    setLoaded({ kind: "challenge", value: view });
    setDeclining(false);
    onDone?.(view);
  }

  async function reload() {
    setReloading(true);
    try {
      await read(mode);
      setProblem(null);
    } finally {
      setReloading(false);
    }
  }

  const reasonLength = codePointLength(reason.trim());
  const reasonOk = reasonLength >= 1 && reasonLength <= CHALLENGE_REASON_MAX;
  const declineLength = codePointLength(declineReason.trim());
  const declineOk = declineLength >= 1 && declineLength <= CHALLENGE_REASON_MAX;

  async function submitRaise(suggestions: ChallengeSuggestions) {
    if (mode.kind !== "raise" || busy || !reasonOk) return;
    const owner = suggestions.can_confirm;
    const confirmed = suggestions.suggested
      .map((s) => s.agent)
      .filter((agent) => ticked.includes(agent));
    if (owner && confirmed.length === 0) return;
    setBusy(true);
    setProblem(null);
    let result: ChallengeResult;
    try {
      result = await raiseChallenge({
        opportunityId,
        targetKind: mode.target.kind,
        targetId: mode.target.id,
        reason,
        ...(mode.reviewRequestId ? { reviewRequestId: mode.reviewRequestId } : {}),
        ...(owner ? { confirmed } : {}),
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      succeed(result.value, owner ? REASSESSMENT_STARTED : CHALLENGE_RAISED);
      return;
    }
    fail(result);
  }

  async function submitConfirm(view: ChallengeView) {
    const confirmed = view.suggested.map((s) => s.agent).filter((a) => ticked.includes(a));
    if (busy || confirmed.length === 0) return;
    setBusy(true);
    setProblem(null);
    let result: ChallengeResult;
    try {
      result = await confirmChallenge({
        opportunityId,
        challengeId: view.id,
        rowVersion: view.row_version,
        confirmed,
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") succeed(result.value, REASSESSMENT_STARTED);
    else fail(result);
  }

  async function submitDecline(view: ChallengeView) {
    if (busy || !declineOk) return;
    setBusy(true);
    setProblem(null);
    let result: ChallengeResult;
    try {
      result = await declineChallenge({
        opportunityId,
        challengeId: view.id,
        rowVersion: view.row_version,
        reason: declineReason,
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") succeed(result.value, CHALLENGE_DECLINED);
    else fail(result);
  }

  function raiseAgain(view: ChallengeView) {
    const target: ChallengeTarget =
      view.target.kind === "estimate_version" && view.superseded_by_id
        ? { kind: "estimate_version", id: view.superseded_by_id }
        : { kind: view.target.kind, id: view.target.id };
    setLoaded(null);
    setProblem(null);
    setDone(null);
    setReason(view.reason);
    setMode({ kind: "raise", target, reason: view.reason });
  }

  const title = (text: string) =>
    layout === "dialog" ? (
      <DialogHeader>
        <DialogTitle>{text}</DialogTitle>
      </DialogHeader>
    ) : (
      <h2 id={headingId} className="text-[16px] leading-6 font-semibold">
        {text}
      </h2>
    );

  const cancel =
    layout === "dialog" ? (
      <DialogClose render={<Button type="button" variant="outline" />}>
        {done ? CLOSE : CANCEL}
      </DialogClose>
    ) : null;

  if (!loaded) {
    return (
      <div className="flex flex-col gap-3.5" data-challenge-form="">
        {title(CHALLENGE)}
        <p
          className={cn("text-meta", loadProblem ? "text-destructive" : "text-muted-foreground")}
          role={loadProblem ? "alert" : undefined}
        >
          {loadProblem ?? LOADING_CHALLENGE}
        </p>
        {cancel ? <DialogFooter>{cancel}</DialogFooter> : null}
      </div>
    );
  }

  const problemBlock =
    problem?.kind === "stale" ? (
      <InlineAlert lead={CHALLENGE_STALE} onReload={() => void reload()} reloading={reloading} />
    ) : problem ? (
      <p
        role="alert"
        data-challenge-problem=""
        className="rounded-md border border-blocker/30 bg-blocker-tint px-3 py-2 text-meta text-blocker"
      >
        {problem.text}
      </p>
    ) : null;

  // --- raising ---------------------------------------------------------------------------
  if (loaded.kind === "suggestions") {
    const s = loaded.value;
    const owner = s.can_confirm;
    const count = s.suggested.filter((x) => ticked.includes(x.agent)).length;
    const ready = s.can_raise && reasonOk && (!owner || count > 0);
    return (
      <form
        noValidate
        data-challenge-form="raise"
        aria-labelledby={layout === "inline" ? headingId : undefined}
        aria-busy={busy || undefined}
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          void submitRaise(s);
        }}
        className="flex flex-col gap-3.5"
      >
        {title(s.title)}
        <div className="flex flex-col gap-1">
          <label htmlFor={reasonId} className="text-label">
            {CHALLENGE_REASON_LABEL}
          </label>
          <Textarea
            id={reasonId}
            rows={3}
            value={reason}
            disabled={busy}
            placeholder={CHALLENGE_REASON_PLACEHOLDER}
            aria-invalid={reasonLength > CHALLENGE_REASON_MAX ? true : undefined}
            aria-describedby={reasonRuleId}
            onChange={(event) => setReason(event.target.value)}
          />
          <span
            id={reasonRuleId}
            className={cn(
              "text-meta [font-variant-numeric:tabular-nums]",
              reasonLength > CHALLENGE_REASON_MAX ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {`${reasonLength}/${CHALLENGE_REASON_MAX}`}
          </span>
        </div>
        <SuggestionCards
          suggestions={s.suggested}
          ticked={ticked}
          editable={owner}
          busy={busy}
          onToggle={toggle}
        />
        <p className="text-meta text-text-secondary">{CHALLENGE_HELPER}</p>
        {problemBlock}
        <DialogFooterOrRow layout={layout}>
          {cancel}
          <Button type="submit" disabled={!ready || busy}>
            {owner ? rerunLabel(count) : RAISE_CHALLENGE}
          </Button>
        </DialogFooterOrRow>
      </form>
    );
  }

  // --- an existing Challenge -------------------------------------------------------------
  const view = loaded.value;
  const confirming = view.can_confirm && !done;
  const superseded = view.superseded_by != null && view.status === "awaiting_confirmation";
  const count = view.suggested.filter((x) => ticked.includes(x.agent)).length;
  return (
    <div
      data-challenge-form="existing"
      role={layout === "inline" ? "group" : undefined}
      aria-labelledby={layout === "inline" ? headingId : undefined}
      aria-busy={busy || undefined}
      className="flex flex-col gap-3.5"
    >
      {title(view.title)}
      <div className="flex flex-wrap items-center gap-2">
        <ChallengeStatusPill status={view.status} />
        <span className="text-meta text-muted-foreground">
          {`Estimate v${view.estimate_version}`}
        </span>
      </div>
      <div className="flex flex-col gap-1" data-challenge-reason="">
        <span className="text-label">{challengerReasonLabel(view.challenger.name)}</span>
        <p className="rounded-md border border-border bg-surface-alt px-3 py-2 whitespace-pre-wrap break-words text-body">
          {view.reason}
        </p>
      </div>
      <SuggestionCards
        suggestions={view.suggested}
        ticked={ticked}
        editable={confirming && !superseded}
        busy={busy}
        onToggle={toggle}
      />
      <p className="text-meta text-text-secondary">{CHALLENGE_HELPER}</p>
      {view.status === "declined" && view.decline_reason ? (
        <div className="flex flex-col gap-1" data-decline-reason="">
          <span className="text-label">{CHALLENGE_DECLINED}</span>
          <p className="whitespace-pre-wrap break-words text-body">{view.decline_reason}</p>
        </div>
      ) : null}
      {view.workflow_run_id ? <RunLine opportunityId={opportunityId} view={view} /> : null}
      {superseded && view.superseded_by != null ? (
        <div className="flex flex-col gap-2" data-challenge-superseded="">
          <p
            role="alert"
            className="flex items-start gap-2 rounded-md border border-gap/40 bg-gap-tint px-3 py-2 text-meta text-foreground"
          >
            <MessageSquareWarningIcon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
            {challengeSupersededDetail(view.estimate_version, view.superseded_by)}
          </p>
          {view.can_confirm ? (
            <Button
              type="button"
              variant="outline"
              className="self-start"
              onClick={() => raiseAgain(view)}
            >
              <RedoIcon aria-hidden="true" />
              {raiseOnLabel(view.superseded_by)}
            </Button>
          ) : null}
        </div>
      ) : null}
      {problemBlock}
      {confirming && declining ? (
        <div className="flex flex-col gap-2" data-decline-form="">
          <ReasonInput
            label={DECLINE_REASON_LABEL}
            value={declineReason}
            onChange={setDeclineReason}
            error={null}
            disabled={busy}
            inputRef={declineRef}
            max={CHALLENGE_REASON_MAX}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              disabled={!declineOk || busy}
              onClick={() => void submitDecline(view)}
            >
              {CONFIRM_DECLINE}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setDeclining(false);
                setDeclineReason("");
              }}
            >
              {CANCEL}
            </Button>
          </div>
        </div>
      ) : null}
      <DialogFooterOrRow layout={layout}>
        {cancel}
        {confirming && view.can_decline && !declining ? (
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => setDeclining(true)}
          >
            {DECLINE}
          </Button>
        ) : null}
        {confirming && !superseded ? (
          <Button
            type="button"
            disabled={count === 0 || busy}
            onClick={() => void submitConfirm(view)}
          >
            {rerunLabel(count)}
          </Button>
        ) : null}
      </DialogFooterOrRow>
    </div>
  );
}

function DialogFooterOrRow({
  layout,
  children,
}: {
  layout: "dialog" | "inline";
  children: ReactNode;
}) {
  if (layout === "dialog") return <DialogFooter>{children}</DialogFooter>;
  return <div className="flex flex-wrap justify-end gap-2">{children}</div>;
}

/** The Challenge dialog (520px, the default `DialogContent` width) around `ChallengeForm`.
 * Controlled: the caller owns `open`. The form is mounted only while open, so it reads
 * afresh each time. */
export function ChallengeDialog({
  opportunityId,
  mode,
  open,
  onOpenChange,
  onDone,
}: {
  opportunityId: string;
  mode: ChallengeMode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone?: (view: ChallengeView) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false}>
        {open ? (
          <ChallengeForm
            opportunityId={opportunityId}
            mode={mode}
            layout="dialog"
            {...(onDone ? { onDone } : {})}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

/** An outline **Challenge** button that opens the dialog on `target` (the Assessments tab's
 * Finding inspector and Assessment card). Shown only when the API's `can_challenge` says the
 * caller may; the API checks again. */
export function ChallengeButton({
  opportunityId,
  target,
  onDone,
  size,
}: {
  opportunityId: string;
  target: ChallengeTarget;
  onDone?: (view: ChallengeView) => void;
  size?: "sm" | "default";
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size={size}
        data-challenge-button={target.kind}
        onClick={() => setOpen(true)}
      >
        <MessageSquareWarningIcon aria-hidden="true" />
        {CHALLENGE}
      </Button>
      <ChallengeDialog
        opportunityId={opportunityId}
        mode={{ kind: "raise", target }}
        open={open}
        onOpenChange={setOpen}
        {...(onDone ? { onDone } : {})}
      />
    </>
  );
}
