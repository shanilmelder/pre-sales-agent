"use client";

import { ChevronsUpDownIcon, XIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useState, useTransition, type FormEvent, type ReactNode } from "react";

import {
  decideFinding,
  loadEvidenceOptions,
  type FindingDecisionInput,
  type FindingDecisionResult,
} from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Pill } from "@/components/ui/pill";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import {
  DONE,
  EVIDENCE_EMPTY,
  EVIDENCE_LABEL,
  EVIDENCE_LIMIT,
  EVIDENCE_MAX,
  EVIDENCE_NOT_LOADED,
  EVIDENCE_PLACEHOLDER,
  EVIDENCE_REQUIRED,
  EVIDENCE_SEARCH,
  FINDING_DECISION_FAILED,
  FINDING_GONE,
  FINDING_NOT_ALLOWED,
  findingStatusInfo,
  isEvidenceKind,
  MARK_RESOLVED,
  NOT_OVERRIDABLE,
  NOTE_LABEL,
  OVERRIDE,
  OVERRIDE_CONFIRM,
  OVERRIDE_DESCRIPTION,
  OVERRIDE_KEEP,
  OVERRIDE_TITLE,
  overriddenBy,
  previousOverrideNote,
  REAPPLY_OVERRIDE,
  REASON_LABEL,
  REASON_MAX,
  REASON_REQUIRED,
  resolvedBy,
  SUPPLY_EVIDENCE,
  type EvidenceOption,
  type FindingState,
  type FindingStatus,
} from "@/lib/findings";
import { codePointLength } from "@/lib/opportunities";
import { formatDateTime } from "@/lib/sources";

/** A Critic or Red Team Finding's status (Story 6.6): an icon and a label, never colour alone.
 * Open is blocker-coloured when critical, neutral otherwise; Resolved has a check; Overridden
 * is neutral with a shield. */
export function FindingStatusPill({
  status,
  severity,
}: {
  status: FindingStatus;
  severity: string;
}) {
  const info = findingStatusInfo(status, severity);
  const Icon = info.icon;
  return (
    <Pill data-finding-status={status} tone={info.tone} icon={<Icon />} className="w-fit">
      {info.label}
    </Pill>
  );
}

type Mode = "evidence" | "resolve" | "override" | null;
type Outcome = { kind: "stale"; message: string } | { kind: "message"; text: string } | null;

/** What to show after a failed action (as `conflict-inspector`'s decisions). */
function failure(result: Exclude<FindingDecisionResult, { kind: "ok" }>): Outcome {
  switch (result.kind) {
    case "stale":
      return { kind: "stale", message: result.message };
    case "invalid":
      return { kind: "message", text: result.detail };
    case "conflict":
      return { kind: "message", text: `${result.detail} Reload to see the latest.` };
    case "forbidden":
      return { kind: "message", text: FINDING_NOT_ALLOWED };
    case "not-found":
      return { kind: "message", text: FINDING_GONE };
    default:
      return { kind: "message", text: FINDING_DECISION_FAILED };
  }
}

/** The required reason (or note) with a live character count and an inline error. */
function ReasonField({
  label,
  value,
  onChange,
  error,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error: string | null;
  disabled: boolean;
}) {
  const id = useId();
  const countId = useId();
  const errorId = useId();
  const length = codePointLength(value.trim());
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-label">
        {label}
      </label>
      <Textarea
        id={id}
        rows={3}
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${countId} ${errorId}` : countId}
        onChange={(event) => onChange(event.target.value)}
      />
      <span
        id={countId}
        className={`self-end text-meta [font-variant-numeric:tabular-nums] ${length > REASON_MAX ? "text-destructive" : "text-muted-foreground"}`}
      >
        {`${length}/${REASON_MAX}`}
      </span>
      {error ? (
        <p id={errorId} className="text-meta text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function validReason(value: string): boolean {
  const length = codePointLength(value.trim());
  return length >= 1 && length <= REASON_MAX;
}

function refKey(option: Pick<EvidenceOption, "kind" | "id" | "version">): string {
  return `${option.kind}:${option.id}:${option.version}`;
}

/** The Evidence combobox (Popover + Command): the Opportunity's active Requirements and its
 * Sources, loaded when first opened; up to 20 may be chosen (each item then shows a check and
 * `aria-checked`, and a removable chip), after which the others are disabled and "Up to 20"
 * shows. */
function EvidencePicker({
  opportunityId,
  chosen,
  onChange,
  error,
  disabled,
}: {
  opportunityId: string;
  chosen: EvidenceOption[];
  onChange: (chosen: EvidenceOption[]) => void;
  error: string | null;
  disabled: boolean;
}) {
  const labelId = useId();
  const errorId = useId();
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<EvidenceOption[] | null>(null);
  const [failed, setFailed] = useState(false);
  const chosenKeys = new Set(chosen.map(refKey));
  const atLimit = chosen.length >= EVIDENCE_MAX;

  function load() {
    if (options !== null) return;
    loadEvidenceOptions(opportunityId).then(
      (result) => {
        if (result.kind === "ok") {
          setOptions(result.items);
          setFailed(false);
        } else setFailed(true);
      },
      () => setFailed(true),
    );
  }

  function toggle(option: EvidenceOption) {
    const key = refKey(option);
    if (chosenKeys.has(key)) onChange(chosen.filter((c) => refKey(c) !== key));
    else if (chosen.length < EVIDENCE_MAX) onChange([...chosen, option]);
  }

  const groups: { heading: string; kind: string }[] = [
    { heading: "Requirements", kind: "requirement" },
    { heading: "Sources", kind: "source_document" },
  ];

  return (
    <div className="flex flex-col gap-1.5">
      <span id={labelId} className="text-label">
        {EVIDENCE_LABEL}
      </span>
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) load();
        }}
      >
        <PopoverTrigger
          disabled={disabled}
          aria-labelledby={labelId}
          aria-describedby={error ? errorId : undefined}
          render={<Button type="button" variant="outline" className="w-full justify-between" />}
        >
          <span className="truncate">
            {chosen.length > 0 ? `${chosen.length} chosen` : EVIDENCE_PLACEHOLDER}
          </span>
          <ChevronsUpDownIcon aria-hidden="true" className="size-4 shrink-0 opacity-60" />
        </PopoverTrigger>
        <PopoverContent className="w-80 p-0">
          <Command label={EVIDENCE_LABEL}>
            <CommandInput placeholder={EVIDENCE_SEARCH} aria-label={EVIDENCE_SEARCH} />
            <CommandList>
              {failed ? (
                <p className="p-3 text-meta text-destructive">{EVIDENCE_NOT_LOADED}</p>
              ) : options === null ? (
                <p className="p-3 text-meta text-muted-foreground">Loading…</p>
              ) : (
                <>
                  <CommandEmpty>{EVIDENCE_EMPTY}</CommandEmpty>
                  {groups.map((group) => {
                    const items = options.filter((o) => o.kind === group.kind);
                    if (items.length === 0) return null;
                    return (
                      <CommandGroup key={group.kind} heading={group.heading}>
                        {items.map((option) => (
                          <CommandItem
                            key={refKey(option)}
                            value={`${option.label} ${option.excerpt} ${refKey(option)}`}
                            // The item's check icon shows on `data-checked`; `aria-checked`
                            // gives the chosen state to assistive technology.
                            data-checked={chosenKeys.has(refKey(option))}
                            aria-checked={chosenKeys.has(refKey(option))}
                            disabled={atLimit && !chosenKeys.has(refKey(option))}
                            onSelect={() => toggle(option)}
                          >
                            <span className="shrink-0 text-label">{option.label}</span>
                            {option.excerpt ? (
                              <span className="truncate text-meta text-muted-foreground">
                                {option.excerpt}
                              </span>
                            ) : null}
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    );
                  })}
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {chosen.length > 0 ? (
        <ul aria-label="Chosen Evidence" className="flex flex-wrap gap-1.5">
          {chosen.map((option) => (
            <li key={refKey(option)}>
              <Chip>
                {option.label}
                <button
                  type="button"
                  disabled={disabled}
                  aria-label={`Remove ${option.label}`}
                  onClick={() => onChange(chosen.filter((c) => refKey(c) !== refKey(option)))}
                  className={
                    "inline-flex rounded-sm outline-none focus-visible:ring-2 " +
                    "focus-visible:ring-primary"
                  }
                >
                  <XIcon aria-hidden="true" className="size-3" />
                </button>
              </Chip>
            </li>
          ))}
        </ul>
      ) : null}
      {atLimit ? (
        <p role="status" className="text-meta text-muted-foreground">
          {EVIDENCE_LIMIT}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-meta text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** How the Finding was resolved or overridden, and (while open) an earlier Finding's override
 * with the same fingerprint, shown and never applied. */
function FindingRecord({ finding }: { finding: FindingState }) {
  const { resolution, override, previous_override: previous } = finding;
  return (
    <>
      {resolution ? (
        <div className="flex flex-col gap-1" data-testid="finding-resolution">
          <p className="text-meta text-muted-foreground">
            {resolvedBy(resolution)} ·{" "}
            <time dateTime={resolution.at}>{formatDateTime(resolution.at)}</time>
          </p>
          <p className="whitespace-pre-wrap break-words text-body">{resolution.reason}</p>
          {resolution.evidence.length > 0 ? (
            <ul aria-label="Supplied Evidence" className="flex flex-wrap gap-1.5">
              {resolution.evidence.map((e) => (
                <li key={`${e.kind}:${e.id}:${e.version}`}>
                  <Chip>{e.label}</Chip>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {override ? (
        <div className="flex flex-col gap-1" data-testid="finding-override">
          <p className="text-meta text-muted-foreground">
            {overriddenBy(override)} ·{" "}
            <time dateTime={override.at}>{formatDateTime(override.at)}</time>
          </p>
          <p className="whitespace-pre-wrap break-words text-body">{override.reason}</p>
        </div>
      ) : null}
      {finding.status === "open" && previous ? (
        <p className="text-meta text-muted-foreground" data-testid="previous-override">
          {previousOverrideNote(previous)}
        </p>
      ) : null}
    </>
  );
}

/** The status block of a Critic or Red Team Finding's inspector, with its actions (Story 6.6):
 * **Supply Evidence** (the Evidence combobox and a note), **Mark resolved** (a reason) and
 * **Override** (a reason, then a confirm dialog), or **Re-apply override** with the earlier
 * Finding's reason filled in. Each action shows only when the API says the caller may
 * (`can_resolve`, `can_override`, `overridable`). Errors show inline (a 412 offers Reload) and
 * are announced, as a saved action is; then the page re-reads. */
export function FindingDecisions({
  opportunityId,
  finding,
}: {
  opportunityId: string;
  finding: FindingState & { severity: string };
}) {
  const router = useRouter();
  const announce = useAnnounce();
  const [pending, startTransition] = useTransition();
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [mode, setMode] = useState<Mode>(null);
  const [reason, setReason] = useState("");
  const [chosen, setChosen] = useState<EvidenceOption[]>([]);
  const [errors, setErrors] = useState<{ reason?: string; evidence?: string }>({});
  const [confirming, setConfirming] = useState(false);
  const headingId = useId();
  const open = finding.status === "open";
  const previous = finding.previous_override;

  function choose(next: Mode, prefill = "") {
    setMode(next);
    setReason(prefill);
    setChosen([]);
    setErrors({});
    setOutcome(null);
  }

  function send(action: FindingDecisionInput["action"]) {
    setOutcome(null);
    const input: FindingDecisionInput = {
      opportunityId,
      findingId: finding.id,
      rowVersion: finding.row_version,
      action,
      reason,
      ...(action === "evidence"
        ? {
            refs: chosen.flatMap((c) =>
              isEvidenceKind(c.kind) ? [{ kind: c.kind, id: c.id, version: c.version }] : [],
            ),
          }
        : {}),
    };
    startTransition(async () => {
      let result: FindingDecisionResult;
      try {
        result = await decideFinding(input);
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok") {
        const done =
          action === "evidence" ? "evidence" : action === "resolve" ? "resolved" : "overridden";
        announce(DONE[done]);
        setMode(null);
        // The pill, the inspector and the Assessments badge update.
        router.refresh();
        return;
      }
      const next = failure(result);
      setOutcome(next);
      announce(next?.kind === "stale" ? next.message : (next?.text ?? FINDING_DECISION_FAILED));
    });
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next: { reason?: string; evidence?: string } = {};
    if (!validReason(reason)) next.reason = REASON_REQUIRED;
    if (mode === "evidence" && chosen.length === 0) next.evidence = EVIDENCE_REQUIRED;
    setErrors(next);
    if (next.reason || next.evidence) return;
    if (mode === "override") setConfirming(true);
    else if (mode === "evidence") send("evidence");
    else if (mode === "resolve") send("resolve");
  }

  const notice: ReactNode =
    outcome?.kind === "stale" ? (
      <InlineAlert
        lead={outcome.message}
        onReload={() => {
          setOutcome(null);
          router.refresh();
        }}
      />
    ) : outcome?.kind === "message" ? (
      <p className="text-meta text-destructive">{outcome.text}</p>
    ) : null;

  const canOverride = open && finding.overridable && finding.can_override;
  const canResolve = open && finding.can_resolve;
  const submitLabel =
    mode === "evidence" ? SUPPLY_EVIDENCE : mode === "resolve" ? MARK_RESOLVED : OVERRIDE;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h4 id={headingId} className="text-label text-muted-foreground">
        Status
      </h4>
      <FindingStatusPill status={finding.status} severity={finding.severity} />
      <FindingRecord finding={finding} />
      {open && !finding.overridable ? (
        <p className="text-meta text-muted-foreground">{NOT_OVERRIDABLE}</p>
      ) : null}
      {canResolve || canOverride ? (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Finding actions">
          {canResolve ? (
            <>
              <Button
                type="button"
                variant="outline"
                aria-pressed={mode === "evidence"}
                disabled={pending}
                onClick={() => choose("evidence")}
              >
                {SUPPLY_EVIDENCE}
              </Button>
              <Button
                type="button"
                variant="outline"
                aria-pressed={mode === "resolve"}
                disabled={pending}
                onClick={() => choose("resolve")}
              >
                {MARK_RESOLVED}
              </Button>
            </>
          ) : null}
          {canOverride ? (
            <Button
              type="button"
              variant="outline"
              aria-pressed={mode === "override"}
              disabled={pending}
              onClick={() => choose("override", previous ? previous.reason : "")}
            >
              {previous ? REAPPLY_OVERRIDE : OVERRIDE}
            </Button>
          ) : null}
        </div>
      ) : null}
      {mode !== null ? (
        <form noValidate onSubmit={onSubmit} className="flex flex-col gap-3">
          {mode === "evidence" ? (
            <EvidencePicker
              opportunityId={opportunityId}
              chosen={chosen}
              onChange={setChosen}
              error={errors.evidence ?? null}
              disabled={pending}
            />
          ) : null}
          <ReasonField
            label={mode === "evidence" ? NOTE_LABEL : REASON_LABEL}
            value={reason}
            onChange={setReason}
            error={errors.reason ?? null}
            disabled={pending}
          />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={pending}>
              {submitLabel}
            </Button>
            <Button type="button" variant="ghost" disabled={pending} onClick={() => choose(null)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
      {notice}
      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{OVERRIDE_TITLE}</DialogTitle>
            <DialogDescription>{OVERRIDE_DESCRIPTION}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>{OVERRIDE_KEEP}</DialogClose>
            <Button
              variant="destructive"
              disabled={pending}
              onClick={() => {
                setConfirming(false);
                send("override");
              }}
            >
              {OVERRIDE_CONFIRM}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
