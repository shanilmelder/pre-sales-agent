"use client";

import { ArrowDownIcon, CircleAlertIcon, TriangleAlertIcon } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent } from "react";

import { OriginText } from "@/components/opportunities/estimate-item-parts";
import { useShell } from "@/components/shell/shell-context";
import { Card } from "@/components/ui/card";
import { Pill, type PillTone } from "@/components/ui/pill";
import {
  NO_RISKS,
  riskId,
  riskLevelLabel,
  risksHeading,
  type Risk,
  type RiskLevel,
} from "@/lib/estimates";
import { cn } from "@/lib/utils";

const LEVEL: Record<RiskLevel, { tone: PillTone; Icon: typeof CircleAlertIcon }> = {
  high: { tone: "blocker", Icon: TriangleAlertIcon },
  medium: { tone: "gap", Icon: CircleAlertIcon },
  low: { tone: "neutral", Icon: ArrowDownIcon },
};

/** A likelihood or impact: always an icon and a label, never colour alone (High red). */
export function RiskLevelPill({
  level,
  kind,
}: {
  level: RiskLevel;
  kind: "likelihood" | "impact";
}) {
  const { tone, Icon } = LEVEL[level];
  return (
    <Pill tone={tone} icon={<Icon />} data-level={level} data-level-kind={kind} className="w-[5.5rem]">
      {riskLevelLabel(level)}
    </Pill>
  );
}

/** The columns of the Risks table, shared by its header and its rows (from `md`). */
const RISK_COLUMNS = "md:grid-cols-[3rem_6.5rem_6.5rem_minmax(0,1fr)]";

/** The Risks card below the Assumptions Register (Story 8.5), styled like the Findings table:
 * "Risks · {n}", then ID `R{n}`, Likelihood, Impact and the Risk (its description and its
 * "from Gap: {title}" origin), in the order the API gives (impact, then likelihood). One Tab
 * stop (roving tabindex); the arrows (or j/k with single-key shortcuts on) move between rows;
 * Enter, Space or a click opens the Risk in the inspector. Risks are never blockers. */
export function RisksCard({
  risks,
  selectedId = null,
  onOpen,
}: {
  risks: readonly Risk[];
  selectedId?: string | null;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (risk: Risk, viaKeyboard: boolean) => void;
}) {
  const headingId = useId();
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const ids = risks.map((r) => r.id);
  const tabStopId = [focusedId, selectedId].find((k) => k !== null && ids.includes(k)) ?? ids[0];

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      container.current?.querySelectorAll<HTMLButtonElement>("button[data-risk-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === event.target);
    const next =
      index === -1 ? 0 : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <Card
      role="region"
      aria-labelledby={headingId}
      data-testid="risks-card"
      className="gap-0 overflow-hidden p-0"
    >
      <div className="flex items-center gap-3 border-b border-border px-5 py-4">
        <h3 id={headingId} className="text-section">
          {risksHeading(risks.length)}
        </h3>
      </div>
      {risks.length === 0 ? (
        <p className="px-5 py-4 text-muted-foreground">{NO_RISKS}</p>
      ) : (
        <>
          <div
            aria-hidden="true"
            className={cn(
              "hidden gap-4 bg-surface-alt px-5 py-2.5 text-label text-muted-foreground md:grid",
              RISK_COLUMNS,
            )}
          >
            <span>ID</span>
            <span>Likelihood</span>
            <span>Impact</span>
            <span>Risk</span>
          </div>
          <div
            ref={container}
            role="grid"
            aria-label="Risks"
            onKeyDown={onKeyDown}
            className="flex flex-col"
          >
            {risks.map((risk) => {
              const selected = risk.id === selectedId;
              return (
                <div
                  key={risk.id}
                  role="row"
                  aria-selected={selected}
                  data-risk-id={risk.id}
                  className={cn(
                    "border-t border-border first:border-t-0 md:first:border-t",
                    selected ? "bg-muted" : "hover:brightness-[.97]",
                  )}
                >
                  <div role="gridcell">
                    <button
                      type="button"
                      data-risk-row=""
                      tabIndex={risk.id === tabStopId ? 0 : -1}
                      onFocus={() => setFocusedId(risk.id)}
                      // A keyboard-activated click has no pointer clicks (detail 0).
                      onClick={(event) => onOpen?.(risk, event.detail === 0)}
                      className={cn(
                        "grid min-h-row w-full grid-cols-[3rem_minmax(0,1fr)] items-center gap-x-4 gap-y-1 px-5 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset",
                        RISK_COLUMNS,
                      )}
                    >
                      <span className="text-label text-muted-foreground [font-variant-numeric:tabular-nums]">
                        {riskId(risk)}
                      </span>
                      <span className="flex flex-wrap gap-1 md:contents">
                        <span className="sr-only">Likelihood:</span>
                        <RiskLevelPill level={risk.likelihood} kind="likelihood" />
                        <span className="sr-only">Impact:</span>
                        <RiskLevelPill level={risk.impact} kind="impact" />
                      </span>
                      <span className="col-span-2 flex min-w-0 flex-col gap-0.5 md:col-span-1">
                        <span className="break-words text-body-strong">{risk.description}</span>
                        <span className="text-muted-foreground" data-gap-chip="">
                          <OriginText item={risk} />
                        </span>
                      </span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}
