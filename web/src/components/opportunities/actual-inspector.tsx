"use client";

import { useEffect, useId, useState } from "react";

import { correctActual, saveActuals, type SaveActualsResult } from "@/app/opportunities/actions";
import type { CatalogueOptions } from "@/app/opportunities/data";
import { FailedAssumptionList } from "@/components/opportunities/failed-assumption-list";
import { ReasonInput } from "@/components/opportunities/reason-input";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  ACTUALS_REASON_MAX,
  DASH,
  HOURS_RULE,
  REASON_REQUIRED,
  SAVE_FAILED,
  STALE_LEAD,
  causeLabel,
  costText,
  currencyExponent,
  formatLocalDate,
  hours,
  kindLabel,
  parseHours,
  varianceTone,
  type ActualError,
  type ActualInput,
  type ActualKind,
  type ActualsLine,
  type ActualsView,
  type ActualView,
  type VarianceCause,
} from "@/lib/actuals";

/** What the Inspector shows: a Baseline line, a recorded Unplanned Actual, or new Unplanned
 * work. */
export type ActualTarget =
  | { kind: "line"; line: ActualsLine }
  | { kind: "unplanned"; actual: ActualView | null };

type Form = {
  kind: ActualKind;
  milestoneLabel: string;
  effort: string;
  duration: string;
  cost: string;
  currency: string;
  cause: VarianceCause | "";
  note: string;
  failed: string[];
  integrationTypeId: string;
  workPackageId: string;
  reason: string;
};

/** E.g. "Enter an amount such as 4800.00" (two decimals for EUR, none for JPY). */
function costHint(currency: string): string {
  const digits = currencyExponent(currency.trim() || null);
  return `Enter an amount such as ${(4800).toFixed(digits)}.`;
}

function formOf(actual: ActualView | null): Form {
  return {
    kind: actual?.kind ?? "final",
    milestoneLabel: actual?.milestone_label ?? "",
    effort: actual === null ? "" : hours(actual.effort_hours),
    duration: actual?.duration_days == null ? "" : hours(actual.duration_days),
    cost:
      actual?.cost_minor == null
        ? ""
        : (actual.cost_minor / 10 ** currencyExponent(actual.currency)).toFixed(
            currencyExponent(actual.currency),
          ),
    currency: actual?.currency ?? "",
    cause: actual?.variance_cause ?? "",
    note: actual?.note ?? "",
    failed: actual?.failed_assumptions.map((a) => a.assumption_id) ?? [],
    integrationTypeId:
      actual?.integration_types.length && actual.line_id === null
        ? actual.integration_types[0]!.id
        : "",
    workPackageId: actual?.work_package?.id ?? "",
    reason: "",
  };
}

/** A cost typed in the currency's units ("4800.50") as minor units, using the currency's
 * exponent; null when blank, "invalid" when it doesn't fit the exponent. */
function parseCost(text: string, currency: string): number | null | "invalid" {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const digits = currencyExponent(currency.trim() || null);
  const pattern =
    digits === 0 ? /^\d{1,15}$/ : new RegExp(`^\\d{1,15}(\\.\\d{1,${digits}})?$`);
  if (!pattern.test(trimmed)) return "invalid";
  return Math.round(Number(trimmed) * 10 ** digits);
}

/** The Inspector's full Actual form (kind, milestone label, hours, duration, cost, cause,
 * note, failed Assumptions and, for Unplanned work, the Integration Type or Work Package), the
 * correction reason, and the Actual's history. Read only unless `view.can_record`. Story 10.4:
 * the failed Assumptions are also listed read-only for every role, each with **Open in
 * Trace**. */
export function ActualInspector({
  opportunityId,
  view,
  target,
  catalogue,
  onSaved,
  onReload,
  onDirtyChange,
}: {
  opportunityId: string;
  view: ActualsView;
  target: ActualTarget;
  catalogue: CatalogueOptions;
  onSaved: (next: ActualsView) => void;
  onReload: () => void;
  /** Whether the form differs from the saved Actual (the tab skips live re-reads then). */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const announce = useAnnounce();
  const ids = useId();
  const actual = target.kind === "line" ? target.line.actual : target.actual;
  const unplanned = target.kind === "unplanned";
  const [form, setForm] = useState<Form>(() => formOf(actual));
  const [errors, setErrors] = useState<ActualError[]>([]);
  const [stale, setStale] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(form) !== JSON.stringify(formOf(actual));
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);
  const editable = view.can_record;
  const correcting = actual !== null;
  const causes = view.causes.filter((c) => !unplanned || c.unplanned);
  const heading =
    target.kind === "line" ? `${target.line.label} ${target.line.title}` : "Unplanned work";

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function errorFor(field: string): string | null {
    return errors.find((e) => e.field === field)?.message ?? null;
  }

  function fieldProps(field: string) {
    const message = errorFor(field);
    return {
      "aria-invalid": message ? true : undefined,
      "aria-describedby": message ? `${ids}-${field}-error` : undefined,
    } as const;
  }

  function fieldError(field: string) {
    const message = errorFor(field);
    return message ? (
      <p id={`${ids}-${field}-error`} className="text-meta text-destructive">
        {message}
      </p>
    ) : null;
  }

  function outcome(result: SaveActualsResult) {
    if (result.kind === "ok") {
      setErrors([]);
      setStale(false);
      setFailure(null);
      announce(correcting ? "Actual corrected" : "Actual recorded");
      onSaved(result.saved.view);
      return;
    }
    if (result.kind === "invalid") setErrors(result.errors);
    else if (result.kind === "stale") setStale(true);
    else if (result.kind === "conflict") setFailure(result.detail ?? SAVE_FAILED);
    else if (result.kind === "forbidden") setFailure("You can't record Actuals here.");
    else setFailure(SAVE_FAILED);
  }

  async function save() {
    if (busy) return;
    const effort = parseHours(form.effort);
    const duration = parseHours(form.duration);
    const local: ActualError[] = [];
    if (effort === null || effort === "invalid") {
      local.push({ item: null, field: "effort_hours", message: HOURS_RULE });
    }
    if (duration === "invalid") {
      local.push({ item: null, field: "duration_days", message: HOURS_RULE });
    }
    const cost = parseCost(form.cost, form.currency);
    if (cost === "invalid") {
      local.push({ item: null, field: "cost_minor", message: costHint(form.currency) });
    }
    if (correcting && form.reason.trim() === "") {
      local.push({ item: null, field: "reason", message: REASON_REQUIRED });
    }
    if (
      local.length > 0 ||
      effort === null ||
      effort === "invalid" ||
      duration === "invalid" ||
      cost === "invalid"
    ) {
      setErrors(local);
      return;
    }
    const fields: Omit<ActualInput, "line_id" | "actual_id"> = {
      kind: form.kind,
      milestone_label: form.kind === "milestone" && form.milestoneLabel.trim() ? form.milestoneLabel : null,
      effort_hours: effort,
      duration_days: duration,
      cost_minor: cost,
      currency: form.currency.trim() === "" ? null : form.currency.trim().toUpperCase(),
      variance_cause: form.cause === "" ? null : form.cause,
      note: form.note.trim() === "" ? null : form.note,
      failed_assumption_ids: form.failed,
      integration_type_id: unplanned && form.integrationTypeId ? form.integrationTypeId : null,
      work_package_id: unplanned && form.workPackageId ? form.workPackageId : null,
    };
    setBusy(true);
    try {
      if (actual !== null) {
        outcome(
          await correctActual({
            opportunityId,
            actualId: actual.id,
            version: actual.version,
            fields: { ...fields, reason: form.reason },
          }),
        );
      } else {
        const item: ActualInput = {
          ...fields,
          ...(target.kind === "line" ? { line_id: target.line.line_id } : {}),
        };
        outcome(await saveActuals({ opportunityId, rowVersion: view.row_version, items: [item] }));
      }
    } finally {
      setBusy(false);
    }
  }

  const variance = target.kind === "line" ? target.line.variance : (actual?.variance ?? null);

  return (
    <section aria-labelledby={`${ids}-heading`} className="flex flex-col gap-4 p-gutter">
      <header className="flex flex-col gap-1">
        <h3 id={`${ids}-heading`} className="text-section">
          {heading}
        </h3>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-meta tabular-nums">
          {target.kind === "line" ? (
            <>
              <dt className="text-text-secondary">Estimate</dt>
              <dd>{`${hours(target.line.estimate_hours)} h`}</dd>
              <dt className="text-text-secondary">Integration Types</dt>
              <dd>
                {target.line.integration_types.map((t) => t.name).join(", ") || DASH}
              </dd>
            </>
          ) : null}
          <dt className="text-text-secondary">Variance</dt>
          <dd className={`font-semibold ${varianceTone(variance)}`}>
            {variance === null ? (
              DASH
            ) : (
              <>
                {variance.label}
                <span className="ml-1 font-normal text-text-secondary">
                  {variance.direction_label}
                </span>
              </>
            )}
          </dd>
          {actual !== null ? (
            <>
              <dt className="text-text-secondary">Recorded against</dt>
              <dd>{`Estimate v${actual.estimate_version}`}</dd>
            </>
          ) : null}
        </dl>
      </header>

      {stale ? (
        <InlineAlert lead={STALE_LEAD} onReload={onReload}>
          <p className="text-meta">Reload to see the latest Actuals, then make your change again.</p>
        </InlineAlert>
      ) : null}
      {failure ? (
        <p role="alert" className="text-meta text-destructive">
          {failure}
        </p>
      ) : null}

      {editable ? (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="flex flex-col gap-1">
            <label htmlFor={`${ids}-kind`} className="text-meta text-text-secondary">
              Kind
            </label>
            <Select
              id={`${ids}-kind`}
              value={form.kind}
              onChange={(event) => set("kind", event.target.value as ActualKind)}
            >
              <option value="final">Final</option>
              <option value="milestone">Milestone</option>
            </Select>
          </div>
          {form.kind === "milestone" ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={`${ids}-label`} className="text-meta text-text-secondary">
                Milestone label
              </label>
              <Input
                id={`${ids}-label`}
                value={form.milestoneLabel}
                onChange={(event) => set("milestoneLabel", event.target.value)}
                {...fieldProps("milestone_label")}
              />
              {fieldError("milestone_label")}
            </div>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor={`${ids}-effort`} className="text-meta text-text-secondary">
                Actual hours
              </label>
              <Input
                id={`${ids}-effort`}
                inputMode="decimal"
                className="text-right tabular-nums"
                value={form.effort}
                onChange={(event) => set("effort", event.target.value)}
                {...fieldProps("effort_hours")}
              />
              {fieldError("effort_hours")}
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`${ids}-duration`} className="text-meta text-text-secondary">
                Duration (working days)
              </label>
              <Input
                id={`${ids}-duration`}
                inputMode="decimal"
                className="text-right tabular-nums"
                value={form.duration}
                onChange={(event) => set("duration", event.target.value)}
                {...fieldProps("duration_days")}
              />
              {fieldError("duration_days")}
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`${ids}-cost`} className="text-meta text-text-secondary">
                Cost
              </label>
              <Input
                id={`${ids}-cost`}
                inputMode="decimal"
                placeholder={(0).toFixed(currencyExponent(form.currency.trim() || null))}
                className="text-right tabular-nums"
                value={form.cost}
                onChange={(event) => set("cost", event.target.value)}
                {...fieldProps("cost_minor")}
              />
              {fieldError("cost_minor")}
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`${ids}-currency`} className="text-meta text-text-secondary">
                Currency
              </label>
              <Input
                id={`${ids}-currency`}
                maxLength={3}
                placeholder="EUR"
                value={form.currency}
                onChange={(event) => set("currency", event.target.value)}
                {...fieldProps("currency")}
              />
              {fieldError("currency")}
            </div>
          </div>
          {unplanned ? (
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <label htmlFor={`${ids}-type`} className="text-meta text-text-secondary">
                  Integration Type
                </label>
                <Select
                  id={`${ids}-type`}
                  value={form.integrationTypeId}
                  onChange={(event) => set("integrationTypeId", event.target.value)}
                  {...fieldProps("integration_type_id")}
                >
                  <option value="">None</option>
                  {catalogue.integrationTypes.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name}
                    </option>
                  ))}
                </Select>
                {fieldError("integration_type_id")}
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor={`${ids}-package`} className="text-meta text-text-secondary">
                  Work Package
                </label>
                <Select
                  id={`${ids}-package`}
                  value={form.workPackageId}
                  onChange={(event) => set("workPackageId", event.target.value)}
                  {...fieldProps("work_package_id")}
                >
                  <option value="">None</option>
                  {catalogue.workPackages.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name}
                    </option>
                  ))}
                </Select>
                {fieldError("work_package_id")}
              </div>
            </div>
          ) : null}
          <div className="flex flex-col gap-1">
            <label htmlFor={`${ids}-cause`} className="text-meta text-text-secondary">
              Variance cause
            </label>
            <Select
              id={`${ids}-cause`}
              value={form.cause}
              onChange={(event) => set("cause", event.target.value as VarianceCause | "")}
              {...fieldProps("variance_cause")}
            >
              <option value="">No cause</option>
              {causes.map((cause) => (
                <option key={cause.value} value={cause.value}>
                  {cause.label}
                </option>
              ))}
            </Select>
            {fieldError("variance_cause")}
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={`${ids}-note`} className="text-meta text-text-secondary">
              Note
            </label>
            <Textarea
              id={`${ids}-note`}
              rows={2}
              value={form.note}
              onChange={(event) => set("note", event.target.value)}
              {...fieldProps("note")}
            />
            {fieldError("note")}
          </div>
          {view.assumptions.length > 0 ? (
            <fieldset className="flex flex-col gap-1" {...fieldProps("failed_assumption_ids")}>
              <legend className="text-meta text-text-secondary">Failed Assumptions</legend>
              {view.assumptions.map((assumption) => (
                <label key={assumption.id} className="flex items-start gap-2 text-meta">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={form.failed.includes(assumption.id)}
                    onChange={(event) =>
                      set(
                        "failed",
                        event.target.checked
                          ? [...form.failed, assumption.id]
                          : form.failed.filter((id) => id !== assumption.id),
                      )
                    }
                  />
                  <span>
                    <span className="text-text-secondary">
                      {assumption.kind === "contingency" ? "Contingency" : "Condition"}
                    </span>{" "}
                    {assumption.wording}
                  </span>
                </label>
              ))}
              {fieldError("failed_assumption_ids")}
            </fieldset>
          ) : null}
          {correcting ? (
            <ReasonInput
              label="Reason for the correction"
              value={form.reason}
              onChange={(value) => set("reason", value)}
              error={errorFor("reason")}
              disabled={busy}
              max={ACTUALS_REASON_MAX}
            />
          ) : null}
          <Button type="submit" aria-disabled={busy || undefined}>
            {correcting ? "Save correction" : "Record Actual"}
          </Button>
        </form>
      ) : actual !== null ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-meta tabular-nums">
          <dt className="text-text-secondary">Kind</dt>
          <dd>
            {kindLabel(actual.kind)}
            {actual.milestone_label ? ` · ${actual.milestone_label}` : ""}
          </dd>
          <dt className="text-text-secondary">Actual</dt>
          <dd>{`${hours(actual.effort_hours)} h`}</dd>
          <dt className="text-text-secondary">Duration</dt>
          <dd>{actual.duration_days === null ? DASH : `${hours(actual.duration_days)} days`}</dd>
          <dt className="text-text-secondary">Cost</dt>
          <dd>{costText(actual.cost_minor, actual.currency)}</dd>
          <dt className="text-text-secondary">Variance cause</dt>
          <dd>{causeLabel(actual.variance_cause, view.causes)}</dd>
          <dt className="text-text-secondary">Note</dt>
          <dd>{actual.note ?? DASH}</dd>
          <dt className="text-text-secondary">Failed Assumptions</dt>
          <dd>{actual.failed_assumptions.length === 0 ? DASH : actual.failed_assumptions.length}</dd>
        </dl>
      ) : (
        <p className="text-meta text-text-secondary">Not recorded</p>
      )}

      {actual !== null ? (
        <FailedAssumptionList opportunityId={opportunityId} assumptions={actual.failed_assumptions} />
      ) : null}

      {actual !== null ? (
        <section aria-labelledby={`${ids}-history`} className="flex flex-col gap-2">
          <h4 id={`${ids}-history`} className="text-label text-text-secondary">
            History
          </h4>
          <ol className="flex flex-col gap-2 text-meta tabular-nums">
            {[actual, ...actual.history].map((version) => (
              <li key={version.id} className="flex flex-col">
                <span>
                  {`v${version.version} · ${hours(version.effort_hours)} h · ${kindLabel(version.kind)}`}
                </span>
                <span className="text-text-secondary">
                  {`${version.recorded_by_name} · ${formatLocalDate(version.recorded_at)}`}
                  {version.correction_reason ? ` · ${version.correction_reason}` : ""}
                </span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </section>
  );
}
