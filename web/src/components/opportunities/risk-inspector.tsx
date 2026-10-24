"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { SAVE_CHANGE } from "@/components/opportunities/assumption-inspector";
import {
  FormNotice,
  formFieldClass,
  OriginCard,
  PaneLabel,
  ReasonField,
  reasonValid,
} from "@/components/opportunities/estimate-item-parts";
import type { EditOutcome } from "@/components/opportunities/estimate-line-edit";
import { RiskLevelPill } from "@/components/opportunities/risks-card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  carriedLabel,
  DESCRIPTION_MAX,
  DESCRIPTION_RULE,
  EDIT_SAVE_FAILED,
  RISK_EDIT_HINT,
  RISK_LEVELS,
  riskId,
  type Risk,
  type RiskLevel,
} from "@/lib/estimates";
import { codePointLength } from "@/lib/opportunities";
import { cn } from "@/lib/utils";

export type RiskFields = { description: string; likelihood: RiskLevel; impact: RiskLevel };

export type SaveRisk = (
  risk: Risk,
  fields: RiskFields,
  reason: string,
  rowVersion: number,
) => Promise<EditOutcome>;

export type RiskEditing = { onSave: SaveRisk; onReload?: () => void };

function LevelSelect({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: RiskLevel;
  onChange: (value: RiskLevel) => void;
  disabled: boolean;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-label">
        {label}
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as RiskLevel)}
        className={cn(formFieldClass, "w-32")}
      >
        {RISK_LEVELS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** The "Edit Risk" form (Story 8.5): the description, likelihood and impact selects and a
 * required reason; **Save change** is disabled until something changed, the description is
 * valid and a reason is typed. A stale save (412) shows the inline alert with Reload. */
export function EditRiskForm({ risk, editing }: { risk: Risk; editing: RiskEditing }) {
  const formId = useId();
  const descriptionId = useId();
  const ruleId = useId();
  const hintId = useId();
  const [rowVersion, setRowVersion] = useState(risk.row_version);
  const [base, setBase] = useState<RiskFields>({
    description: risk.description,
    likelihood: risk.likelihood,
    impact: risk.impact,
  });
  const [description, setDescription] = useState(risk.description);
  const [likelihood, setLikelihood] = useState<RiskLevel>(risk.likelihood);
  const [impact, setImpact] = useState<RiskLevel>(risk.impact);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ message: string; reload: boolean } | null>(null);
  const [resync, setResync] = useState(false);
  /** After a Reload: the row version the form was on; its values are taken again once the
   * reloaded item (a newer row version) arrives, even with a reason typed. */
  const [reloadFrom, setReloadFrom] = useState<number | null>(null);

  const trimmed = description.trim();
  const length = codePointLength(trimmed);
  const descriptionOk = length > 0 && length <= DESCRIPTION_MAX;
  const changed =
    trimmed !== base.description || likelihood !== base.likelihood || impact !== base.impact;
  const dirty = changed || reason.trim() !== "";
  const canSave = !saving && changed && descriptionOk && reasonValid(reason);

  const reloaded = reloadFrom !== null && risk.row_version !== reloadFrom;
  if (resync || reloaded || (!dirty && !saving && risk.row_version !== rowVersion)) {
    setResync(false);
    setReloadFrom(null);
    setRowVersion(risk.row_version);
    setBase({ description: risk.description, likelihood: risk.likelihood, impact: risk.impact });
    setDescription(risk.description);
    setLikelihood(risk.likelihood);
    setImpact(risk.impact);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setNotice(null);
    let outcome: EditOutcome;
    try {
      outcome = await editing.onSave(
        risk,
        { description: trimmed, likelihood, impact },
        reason.trim(),
        rowVersion,
      );
    } catch {
      outcome = { ok: false, message: EDIT_SAVE_FAILED };
    }
    setSaving(false);
    if (outcome.ok) {
      setReason("");
      setResync(true);
    } else {
      setNotice({ message: outcome.message, reload: outcome.reload ?? false });
    }
  }

  return (
    <section
      aria-labelledby={formId}
      data-edit-risk=""
      className="flex flex-col gap-3 border-t border-border pt-4"
    >
      <h4 id={formId} className="text-eyebrow text-muted-foreground uppercase">
        Edit Risk
      </h4>
      {notice ? (
        <FormNotice
          notice={notice}
          onReload={
            editing.onReload
              ? () => {
                  setNotice(null);
                  setReloadFrom(rowVersion);
                  editing.onReload?.();
                }
              : undefined
          }
        />
      ) : null}
      <form
        aria-label="Edit Risk"
        aria-busy={saving || undefined}
        onSubmit={(event) => void submit(event)}
        className="flex flex-col gap-3"
      >
        <div className="flex flex-col gap-1">
          <label htmlFor={descriptionId} className="text-label">
            Description
          </label>
          <Textarea
            id={descriptionId}
            value={description}
            rows={3}
            maxLength={DESCRIPTION_MAX * 2}
            disabled={saving}
            aria-invalid={descriptionOk ? undefined : true}
            aria-describedby={descriptionOk ? undefined : ruleId}
            onChange={(event) => setDescription(event.target.value)}
          />
          {descriptionOk ? null : (
            <p id={ruleId} className="text-meta text-destructive">
              {DESCRIPTION_RULE}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-3">
          <LevelSelect
            label="Likelihood"
            value={likelihood}
            onChange={setLikelihood}
            disabled={saving}
          />
          <LevelSelect label="Impact" value={impact} onChange={setImpact} disabled={saving} />
        </div>
        <ReasonField value={reason} onChange={setReason} disabled={saving} />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!canSave} aria-describedby={hintId}>
            {SAVE_CHANGE}
          </Button>
          <p id={hintId} className="text-meta text-muted-foreground">
            {RISK_EDIT_HINT}
          </p>
        </div>
      </form>
    </section>
  );
}

/** The selected Risk in the right pane (Story 8.5): "Risk · R{n}" over its description, its
 * likelihood and impact, its origin card, and (with `editing`) the "Edit Risk" form. */
export function RiskInspector({
  risk,
  focusRequest = 0,
  editing,
  onOpenGap,
}: {
  risk: Risk;
  focusRequest?: number;
  editing?: RiskEditing;
  onOpenGap?: () => void;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const carried = carriedLabel(risk);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section aria-labelledby={headingId} data-risk-inspector="" className="flex flex-col gap-5 p-gutter">
      <div className="flex flex-col gap-1">
        <p className="text-meta text-muted-foreground">{`Risk · ${riskId(risk)}`}</p>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-section break-words outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {risk.description}
        </h3>
        {carried ? <p className="text-meta text-muted-foreground">{carried}</p> : null}
      </div>

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-2 text-body">
        <dt className="text-muted-foreground">Likelihood</dt>
        <dd>
          <RiskLevelPill level={risk.likelihood} kind="likelihood" />
        </dd>
        <dt className="text-muted-foreground">Impact</dt>
        <dd>
          <RiskLevelPill level={risk.impact} kind="impact" />
        </dd>
      </dl>

      <div className="flex flex-col gap-1.5">
        <PaneLabel>Origin</PaneLabel>
        <OriginCard item={risk} onOpenGap={onOpenGap} />
      </div>

      {editing ? <EditRiskForm key={risk.id} risk={risk} editing={editing} /> : null}
    </section>
  );
}
