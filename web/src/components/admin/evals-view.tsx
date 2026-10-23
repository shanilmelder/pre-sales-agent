"use client";

import { CircleAlertIcon, CircleCheckIcon, CircleDashedIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { BODY_ROW, CardTable } from "@/components/admin/card-table";
import { Card } from "@/components/ui/card";
import { Pill } from "@/components/ui/pill";
import { pillToneFor } from "@/lib/pill-tone";
import {
  agentName,
  agentRows,
  diffRows,
  EMPTY_STATE,
  formatCost,
  formatWhen,
  NO_PREVIOUS,
  percent,
  runSummary,
  signedPoints,
  statusLabel,
  thresholdLabel,
  type BarStatus,
  type EvalResult,
} from "@/lib/evals";

const ICONS = {
  pass: { Icon: CircleCheckIcon, tone: "text-resolved" },
  fail: { Icon: CircleAlertIcon, tone: "text-blocker" },
  not_measured: { Icon: CircleDashedIcon, tone: "text-muted-foreground" },
} as const;

const BARS_GRID = "grid-cols-[minmax(0,1fr)_110px_110px_120px]";
const AGENTS_GRID = "grid-cols-[minmax(0,1fr)_minmax(0,1fr)_110px_110px_120px]";
const DIFF_GRID = "grid-cols-[minmax(0,1fr)_110px_110px_110px]";

/** A bar's or a result's status: always an icon and a label, never colour alone. */
export function EvalStatusPill({
  status,
  label,
  className = "shrink-0",
}: {
  status: BarStatus;
  label?: string;
  className?: string;
}) {
  const { Icon, tone } = ICONS[status];
  return (
    <Pill data-eval-status={status} tone={pillToneFor(tone)} icon={<Icon />} className={className}>
      {label ?? statusLabel(status)}
    </Pill>
  );
}

function ResultPill({ result, large = false }: { result: EvalResult; large?: boolean }) {
  return (
    <EvalStatusPill
      status={result.passed ? "pass" : "fail"}
      label={result.passed ? (result.accepted ? "Passed · accepted" : "Passed") : "Failed"}
      className={large ? "shrink-0 py-1 pr-3 pl-2.5 [&_svg]:size-3.5" : undefined}
    />
  );
}

/** A card with a 16/600 header; `sub` is a line of secondary text under the title. */
function SectionCard({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <Card className="overflow-hidden">
      <section aria-labelledby={id}>
        <div className="px-5 py-[18px]">
          <h2 id={id} className="text-section">
            {title}
          </h2>
          {sub ? <p className="text-meta text-text-secondary">{sub}</p> : null}
        </div>
        {children}
      </section>
    </Card>
  );
}

const STRONG = "font-semibold text-foreground";

function Summary({ result, latest }: { result: EvalResult; latest: boolean }) {
  return (
    <Card className="flex-row flex-wrap items-center gap-x-5 gap-y-2 px-5 py-[18px]">
      <h2 className="sr-only">{latest ? "Latest result" : "Selected result"}</h2>
      <ResultPill result={result} large />
      <p className="min-w-0 flex-1 text-text-secondary">{runSummary(result)}</p>
      <p className="text-text-secondary">
        <strong className={STRONG}>{result.tokens.toLocaleString("en-GB")}</strong> tokens ·{" "}
        <strong className={STRONG}>{result.gpu_seconds.toFixed(1)}</strong> GPU s ·{" "}
        <strong className={STRONG}>{formatCost(result.cost)}</strong>
      </p>
    </Card>
  );
}

function Failures({ result }: { result: EvalResult }) {
  if (result.failures.length === 0) return null;
  return (
    <SectionCard title="Failures">
      <ul className="flex flex-col">
        {result.failures.map((f) => (
          <li key={`${f.slug}-${f.stage}`} className="border-t border-border px-5 py-3">
            {f.slug}: {f.stage.replace("_", " ")} failed ({f.code}); its later metrics scored 0
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

function Bars({ result }: { result: EvalResult }) {
  return (
    <SectionCard title="Release bars">
      <CardTable
        scrollable
        label="Release bars"
        grid={BARS_GRID}
        columns={["Bar", "Value", "Threshold", "Status"]}
      >
        {result.bars.map((bar) => (
          <div key={bar.metric} role="row" className={`py-4 ${BODY_ROW} ${BARS_GRID}`}>
            <div role="rowheader" className="min-w-0 text-body-strong">
              {bar.label}{" "}
              <span className="text-meta text-text-secondary">{bar.requirement}</span>
              {bar.regressed ? (
                <span className="block text-meta text-text-secondary">
                  {signedPoints(bar.delta)} vs accepted (regressed)
                </span>
              ) : null}
            </div>
            <div role="cell" className="text-numeric">
              <span className="font-semibold">{percent(bar.value)}</span>
            </div>
            <div role="cell" className="text-numeric text-text-secondary">
              {thresholdLabel(bar)}
            </div>
            <div role="cell">
              <EvalStatusPill status={bar.status} />
            </div>
          </div>
        ))}
      </CardTable>
    </SectionCard>
  );
}

function PerAgent({ result }: { result: EvalResult }) {
  return (
    <SectionCard title="Per Agent">
      <CardTable
        scrollable
        label="Results per Agent"
        grid={AGENTS_GRID}
        columns={["Agent", "Bar", "Value", "Threshold", "Status"]}
      >
        {agentRows(result).map((row) => (
          <div
            key={`${row.agentId}-${row.bar.metric}`}
            role="row"
            className={`py-3 ${BODY_ROW} ${AGENTS_GRID}`}
          >
            <div role="rowheader" className="min-w-0 text-body-strong">
              {agentName(row.agentId)}
            </div>
            <div role="cell" className="min-w-0">
              {row.bar.label}
            </div>
            <div role="cell" className="text-numeric">
              <span className="font-semibold">{percent(row.value)}</span>
            </div>
            <div role="cell" className="text-numeric text-text-secondary">
              {thresholdLabel(row.bar)}
            </div>
            <div role="cell">
              <EvalStatusPill status={row.status} />
            </div>
          </div>
        ))}
      </CardTable>
    </SectionCard>
  );
}

function Diff({ current, previous }: { current: EvalResult; previous: EvalResult | null }) {
  if (previous === null) {
    return (
      <SectionCard title="Change from the previous result">
        <p className="border-t border-border px-5 py-4 text-text-secondary">{NO_PREVIOUS}</p>
      </SectionCard>
    );
  }
  return (
    <SectionCard
      title="Change from the previous result"
      sub={`Against the result of ${formatWhen(previous.created_at)}. Changed rows are tinted.`}
    >
      <CardTable
        scrollable
        label="Change from the previous result"
        grid={DIFF_GRID}
        columns={["Bar", "Previous", "This result", "Change"]}
      >
        {diffRows(current, previous).map((row) => (
          <div
            key={row.metric}
            role="row"
            data-changed={row.changed || undefined}
            className={`py-3 ${BODY_ROW} ${DIFF_GRID} ${row.changed ? "bg-diff-tint" : ""}`}
          >
            <div role="rowheader" className="min-w-0 text-body-strong">
              {row.label}
            </div>
            <div role="cell" className="text-numeric">
              {percent(row.previous)}
            </div>
            <div role="cell" className="text-numeric">
              {percent(row.current)}
            </div>
            <div role="cell" className="text-numeric">
              {signedPoints(row.delta)}
            </div>
          </div>
        ))}
      </CardTable>
    </SectionCard>
  );
}

function History({
  results,
  selectedId,
  onSelect,
}: {
  results: readonly EvalResult[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <SectionCard title="History">
      <ul aria-label="Evaluation history" className="flex flex-col">
        {results.map((result) => (
          <li key={result.id} className="border-t border-border">
            <button
              type="button"
              aria-pressed={result.id === selectedId}
              onClick={() => onSelect(result.id)}
              className={`flex w-full items-center gap-3 px-5 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset ${
                result.id === selectedId ? "bg-primary-tint" : "hover:bg-muted/60"
              }`}
            >
              <span className="text-numeric">{formatWhen(result.created_at)}</span>
              <ResultPill result={result} />
              <span className="text-meta text-text-secondary">
                {result.reference_set_version}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

/** Admin → Evals (Story 7.6): the selected result (the latest by default) as a summary card
 * and its release bars, then any failures, the bars per Agent, the change from the result
 * before it and the history. Picking a result in History switches every card. Read-only:
 * results are written only by `make eval`. */
export function EvalsView({ results }: { results: readonly EvalResult[] }) {
  const [selectedId, setSelectedId] = useState(results[0]?.id ?? "");
  if (results.length === 0) {
    return (
      <Card className="px-5 py-4">
        <p className="text-text-secondary">{EMPTY_STATE}</p>
      </Card>
    );
  }
  const index = Math.max(
    0,
    results.findIndex((r) => r.id === selectedId),
  );
  const current = results[index];
  const previous = results[index + 1] ?? null;
  return (
    <div className="flex flex-col gap-6">
      <Summary result={current} latest={index === 0} />
      <Bars result={current} />
      <Failures result={current} />
      <PerAgent result={current} />
      <Diff current={current} previous={previous} />
      <History results={results} selectedId={current.id} onSelect={setSelectedId} />
    </div>
  );
}
