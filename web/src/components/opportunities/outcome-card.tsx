"use client";

import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";

import { changeOutcome, loadOpportunity, type OutcomeResult } from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  codePointLength,
  formatDate,
  NO_ACCESS_TO_OPPORTUNITY,
  staleMessage,
  type Opportunity,
} from "@/lib/opportunities";
import {
  CANCEL,
  CONTRACT_END_LABEL,
  hasBaseline,
  NEEDS_BASELINE,
  OUTCOME_DIALOGS,
  OUTCOME_FAILED,
  OUTCOME_FORBIDDEN,
  OUTCOME_HEADING,
  OUTCOME_LABELS,
  OUTCOME_REASON_MAX,
  REASON_LABEL,
  retentionLine,
  type OutcomeCommand,
} from "@/lib/outcome";
import { cn } from "@/lib/utils";

type Problem = { kind: "stale"; changedBy: string | null } | { kind: "message"; text: string };

function problemOf(result: Exclude<OutcomeResult, { kind: "ok" }>): Problem {
  switch (result.kind) {
    case "stale":
      return { kind: "stale", changedBy: result.changedBy };
    case "invalid":
      return { kind: "message", text: result.detail };
    case "forbidden":
      return { kind: "message", text: OUTCOME_FORBIDDEN };
    case "not-found":
      return { kind: "message", text: NO_ACCESS_TO_OPPORTUNITY };
    default:
      return { kind: "message", text: OUTCOME_FAILED };
  }
}

type FormProps = {
  opportunity: Opportunity;
  command: OutcomeCommand;
  onOpenChange: (open: boolean) => void;
  onDone: (opportunity: Opportunity) => void;
};

/** One outcome command's confirm dialog, in the mockup's Challenge dialog shell (520px, the
 * title, a "Reason (required)" textarea and/or the contract end date, then right-aligned
 * Cancel and the primary action, disabled until the form is valid). A 412 shows the inline
 * alert with Reload; nothing is overwritten. The form is mounted only while open, so each
 * opening starts afresh from the Opportunity as shown. */
export function OutcomeDialog({ open, ...props }: FormProps & { open: boolean }) {
  return (
    <Dialog open={open} onOpenChange={props.onOpenChange}>
      <DialogContent showCloseButton={false} data-outcome-dialog={props.command}>
        {open ? <OutcomeForm {...props} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function OutcomeForm({ opportunity, command, onOpenChange, onDone }: FormProps) {
  const copy = OUTCOME_DIALOGS[command];
  const announce = useAnnounce();
  const reasonId = useId();
  const countId = useId();
  const dateId = useId();
  const helperId = useId();
  const [reason, setReason] = useState("");
  const [date, setDate] = useState(
    command === "contract_end" ? (opportunity.contract_end_date ?? "") : "",
  );
  const [busy, setBusy] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [current, setCurrent] = useState(opportunity);
  const [problem, setProblem] = useState<Problem | null>(null);

  const reasonLength = codePointLength(reason.trim());
  const reasonOk = !copy.reason || (reasonLength >= 1 && reasonLength <= OUTCOME_REASON_MAX);
  const dateOk = !copy.date || /^\d{4}-\d{2}-\d{2}$/.test(date);
  const ready = reasonOk && dateOk && problem?.kind !== "stale";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready) return;
    setBusy(true);
    setProblem(null);
    let result: OutcomeResult;
    try {
      result = await changeOutcome({
        opportunityId: current.id,
        rowVersion: current.row_version,
        command,
        ...(copy.reason ? { reason } : {}),
        ...(copy.date ? { contractEndDate: date } : {}),
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      announce(copy.announce);
      onDone(result.opportunity);
      onOpenChange(false);
      return;
    }
    const next = problemOf(result);
    setProblem(next);
    announce(next.kind === "stale" ? staleMessage(next.changedBy) : next.text);
  }

  async function reload() {
    setReloading(true);
    try {
      const result = await loadOpportunity(current.id);
      if (result.kind === "ok") {
        setCurrent(result.opportunity);
        setProblem(null);
        onDone(result.opportunity);
        // The command may no longer apply to the reloaded Opportunity.
        onOpenChange(false);
      }
    } catch {
      // Keep the alert and its Reload button; nothing was overwritten.
    } finally {
      setReloading(false);
    }
  }

  return (
    <form
      noValidate
      aria-busy={busy || undefined}
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-3.5"
    >
      <DialogHeader>
        <DialogTitle>{copy.title}</DialogTitle>
      </DialogHeader>
      {copy.date ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={dateId} className="text-label">
            {CONTRACT_END_LABEL}
          </label>
          <Input
            id={dateId}
            type="date"
            required
            value={date}
            disabled={busy}
            aria-describedby={helperId}
            onChange={(event) => setDate(event.target.value)}
            className="text-numeric"
          />
        </div>
      ) : null}
      {copy.reason ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={reasonId} className="text-label">
            {REASON_LABEL}
          </label>
          <Textarea
            id={reasonId}
            rows={3}
            required
            value={reason}
            disabled={busy}
            placeholder={copy.placeholder}
            aria-invalid={reasonLength > OUTCOME_REASON_MAX ? true : undefined}
            aria-describedby={`${countId} ${helperId}`}
            onChange={(event) => setReason(event.target.value)}
          />
          <span
            id={countId}
            className={cn(
              "text-meta [font-variant-numeric:tabular-nums]",
              reasonLength > OUTCOME_REASON_MAX ? "text-destructive" : "text-muted-foreground",
            )}
          >
            {`${reasonLength}/${OUTCOME_REASON_MAX}`}
          </span>
        </div>
      ) : null}
      <p id={helperId} className="text-meta text-text-secondary">
        {copy.helper}
      </p>
      {problem?.kind === "stale" ? (
        <InlineAlert
          lead={staleMessage(problem.changedBy)}
          onReload={() => void reload()}
          reloading={reloading}
        />
      ) : problem ? (
        <p
          role="alert"
          data-outcome-problem=""
          className="rounded-md border border-blocker/30 bg-blocker-tint px-3 py-2 text-meta text-blocker"
        >
          {problem.text}
        </p>
      ) : null}
      <DialogFooter>
        <DialogClose render={<Button type="button" variant="outline" />}>{CANCEL}</DialogClose>
        <Button type="submit" disabled={!ready || busy}>
          {copy.submit}
        </Button>
      </DialogFooter>
    </form>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-text-secondary">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  );
}

/** The Overview's Outcome card (Story 10.5): label/value rows in the mockup's 90px/1fr style
 * (Outcome, Recorded, Contract end), the retention line the API computed ("Lost — data kept
 * until 14 Oct 2029"), then the actions the API's flags allow: **Close as lost** and **Mark
 * as won** (disabled until a Baseline), **Change contract end date** and **Reopen**, each
 * through its confirm dialog. Everyone else sees the card read-only, with no actions. */
export function OutcomeCard({ initial }: { initial: Opportunity }) {
  const router = useRouter();
  const headingId = useId();
  const baselineHintId = useId();
  const [opportunity, setOpportunity] = useState(initial);
  const [seen, setSeen] = useState(initial);
  if (seen !== initial) {
    // Follow a newer server copy (React's pattern for adjusting state to a prop).
    setSeen(initial);
    if (initial.row_version > opportunity.row_version) setOpportunity(initial);
  }
  const [dialog, setDialog] = useState<OutcomeCommand | null>(null);
  const [last, setLast] = useState<OutcomeCommand>("lost");

  function openDialog(command: OutcomeCommand) {
    setLast(command);
    setDialog(command);
  }

  function done(next: Opportunity) {
    setOpportunity(next);
    // The workspace header's status pill and the list read the new derived status.
    router.refresh();
  }

  const outcome = opportunity.outcome ?? null;
  const canWin = hasBaseline(opportunity.status);
  const actions: React.ReactNode[] = [];
  if (opportunity.can_record_outcome) {
    actions.push(
      <Button
        key="lost"
        type="button"
        variant="outline"
        size="sm"
        onClick={() => openDialog("lost")}
      >
        {OUTCOME_DIALOGS.lost.button}
      </Button>,
      <Button
        key="won"
        type="button"
        variant="outline"
        size="sm"
        disabled={!canWin}
        aria-describedby={canWin ? undefined : baselineHintId}
        onClick={() => openDialog("won")}
      >
        {OUTCOME_DIALOGS.won.button}
      </Button>,
    );
  }
  if (opportunity.can_change_contract_end) {
    actions.push(
      <Button
        key="contract_end"
        type="button"
        variant="outline"
        size="sm"
        onClick={() => openDialog("contract_end")}
      >
        {OUTCOME_DIALOGS.contract_end.button}
      </Button>,
    );
  }
  if (opportunity.can_reopen_outcome) {
    actions.push(
      <Button
        key="reopen"
        type="button"
        variant="outline"
        size="sm"
        onClick={() => openDialog("reopen")}
      >
        {OUTCOME_DIALOGS.reopen.button}
      </Button>,
    );
  }

  return (
    <Card role="region" aria-labelledby={headingId} data-outcome-card="">
      <div className="border-b border-border px-5 py-[18px]">
        <h3 id={headingId} className="text-section">
          {OUTCOME_HEADING}
        </h3>
      </div>
      <div className="flex flex-col gap-3.5 p-5">
        <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-1.5 text-[13px] leading-5">
          <Row label="Outcome">
            <span data-outcome={outcome ?? "open"}>{OUTCOME_LABELS[outcome ?? "open"]}</span>
          </Row>
          {opportunity.outcome_recorded_at ? (
            <Row label="Recorded">
              <span className="text-numeric">
                {formatDate(opportunity.outcome_recorded_at.slice(0, 10))}
              </span>
            </Row>
          ) : null}
          {opportunity.contract_end_date ? (
            <Row label="Contract end">
              <span className="text-numeric">{formatDate(opportunity.contract_end_date)}</span>
            </Row>
          ) : null}
        </dl>
        <p className="text-body" data-retention-line="">
          {retentionLine(opportunity)}
        </p>
        {actions.length > 0 ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap gap-2">{actions}</div>
            {opportunity.can_record_outcome && !canWin ? (
              <p id={baselineHintId} className="text-meta text-muted-foreground">
                {NEEDS_BASELINE}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
      <OutcomeDialog
        opportunity={opportunity}
        command={dialog ?? last}
        open={dialog !== null}
        onOpenChange={(open) => {
          if (!open) setDialog(null);
        }}
        onDone={done}
      />
    </Card>
  );
}
