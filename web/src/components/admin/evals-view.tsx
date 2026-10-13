"use client";

import { CircleCheckIcon, CircleDashedIcon, CircleXIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import {
  agentName,
  agentRows,
  diffRows,
  EMPTY_STATE,
  formatCost,
  formatWhen,
  NO_PREVIOUS,
  percent,
  signedPoints,
  statusLabel,
  thresholdLabel,
  type BarStatus,
  type EvalResult,
} from "@/lib/evals";

const HEAD = "py-1 pr-3 font-normal";
const NUMERIC = "py-1 pr-3 text-right text-numeric whitespace-nowrap";

const ICONS = {
  pass: { Icon: CircleCheckIcon, tone: "text-resolved" },
  fail: { Icon: CircleXIcon, tone: "text-blocker" },
  not_measured: { Icon: CircleDashedIcon, tone: "text-muted-foreground" },
} as const;

/** A bar's or a result's status: always an icon and a label, never colour alone. */
export function EvalStatusPill({ status, label }: { status: BarStatus; label?: string }) {
  const { Icon, tone } = ICONS[status];
  return (
    <span
      data-eval-status={status}
      className="inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-border bg-background pr-2 pl-1.5 text-label text-foreground"
    >
      <Icon className={`size-3 shrink-0 ${tone}`} aria-hidden="true" />
      {label ?? statusLabel(status)}
    </span>
  );
}

function ResultPill({ result }: { result: EvalResult }) {
  return (
    <EvalStatusPill
      status={result.passed ? "pass" : "fail"}
      label={result.passed ? (result.accepted ? "Passed · accepted" : "Passed") : "Failed"}
    />
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <h2 id={id} className="text-section">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ScrollTable({ caption, children }: { caption: string; children: ReactNode }) {
  const captionId = `${caption.replace(/\W+/g, "-").toLowerCase()}-caption`;
  return (
    <div
      role="region"
      aria-labelledby={captionId}
      tabIndex={0}
      className="overflow-x-auto rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-primary"
    >
      <table className="w-full border-collapse text-left">
        <caption id={captionId} className="sr-only">
          {caption}
        </caption>
        {children}
      </table>
    </div>
  );
}

function Summary({ result }: { result: EvalResult }) {
  const facts: [string, string][] = [
    ["Run", formatWhen(result.created_at)],
    ["Reference set", result.reference_set_version],
    ["Opportunities", `${result.opportunity_count} (${result.draft_count} draft annotations)`],
    ["Evidence pairs pending review", String(result.pending_count)],
    ["Tokens", result.tokens.toLocaleString("en-GB")],
    ["GPU seconds", result.gpu_seconds.toFixed(1)],
    ["Cost", formatCost(result.cost)],
  ];
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <ResultPill result={result} />
        <span className="text-meta text-muted-foreground">Critic: not available</span>
      </div>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
        {facts.map(([term, value]) => (
          <div key={term} className="contents">
            <dt className="text-label text-muted-foreground">{term}</dt>
            <dd className="text-numeric">{value}</dd>
          </div>
        ))}
      </dl>
      {result.failures.length > 0 ? (
        <ul className="list-disc pl-5 text-body">
          {result.failures.map((f) => (
            <li key={`${f.slug}-${f.stage}`}>
              {f.slug}: {f.stage.replace("_", " ")} failed ({f.code}); its later metrics scored 0
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Bars({ result }: { result: EvalResult }) {
  return (
    <ScrollTable caption="Release bars">
      <thead>
        <tr className="border-b border-border text-label text-muted-foreground">
          <th scope="col" className={HEAD}>
            Bar
          </th>
          <th scope="col" className={`${HEAD} text-right`}>
            Value
          </th>
          <th scope="col" className={`${HEAD} text-right`}>
            Threshold
          </th>
          <th scope="col" className={`${HEAD} text-right`}>
            Change vs accepted
          </th>
          <th scope="col" className={HEAD}>
            Status
          </th>
        </tr>
      </thead>
      <tbody>
        {result.bars.map((bar) => (
          <tr key={bar.metric} className="h-row border-b border-border align-baseline">
            <th scope="row" className="py-1 pr-3 text-left font-normal">
              {bar.label} <span className="text-meta text-muted-foreground">{bar.requirement}</span>
            </th>
            <td className={NUMERIC}>{percent(bar.value)}</td>
            <td className={NUMERIC}>{thresholdLabel(bar)}</td>
            <td className={NUMERIC}>
              {signedPoints(bar.delta)}
              {bar.regressed ? <span className="text-meta"> (regressed)</span> : null}
            </td>
            <td className="py-1 pr-3">
              <EvalStatusPill status={bar.status} />
            </td>
          </tr>
        ))}
      </tbody>
    </ScrollTable>
  );
}

function PerAgent({ result }: { result: EvalResult }) {
  return (
    <ScrollTable caption="Results per Agent">
      <thead>
        <tr className="border-b border-border text-label text-muted-foreground">
          <th scope="col" className={HEAD}>
            Agent
          </th>
          <th scope="col" className={HEAD}>
            Bar
          </th>
          <th scope="col" className={`${HEAD} text-right`}>
            Value
          </th>
          <th scope="col" className={`${HEAD} text-right`}>
            Threshold
          </th>
          <th scope="col" className={HEAD}>
            Status
          </th>
        </tr>
      </thead>
      <tbody>
        {agentRows(result).map((row) => (
          <tr
            key={`${row.agentId}-${row.bar.metric}`}
            className="h-row border-b border-border align-baseline"
          >
            <th scope="row" className="py-1 pr-3 text-left font-normal">
              {agentName(row.agentId)}
            </th>
            <td className="py-1 pr-3">{row.bar.label}</td>
            <td className={NUMERIC}>{percent(row.value)}</td>
            <td className={NUMERIC}>{thresholdLabel(row.bar)}</td>
            <td className="py-1 pr-3">
              <EvalStatusPill status={row.status} />
            </td>
          </tr>
        ))}
      </tbody>
    </ScrollTable>
  );
}

function Diff({ current, previous }: { current: EvalResult; previous: EvalResult | null }) {
  if (previous === null) return <p className="text-muted-foreground">{NO_PREVIOUS}</p>;
  return (
    <>
      <p className="text-meta text-muted-foreground">
        Against the result of {formatWhen(previous.created_at)}. Changed rows are tinted.
      </p>
      <ScrollTable caption="Change from the previous result">
        <thead>
          <tr className="border-b border-border text-label text-muted-foreground">
            <th scope="col" className={HEAD}>
              Bar
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Previous
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              This result
            </th>
            <th scope="col" className={`${HEAD} text-right`}>
              Change
            </th>
          </tr>
        </thead>
        <tbody>
          {diffRows(current, previous).map((row) => (
            <tr
              key={row.metric}
              data-changed={row.changed || undefined}
              className={`h-row border-b border-border align-baseline ${row.changed ? "bg-diff-tint" : ""}`}
            >
              <th scope="row" className="py-1 pr-3 text-left font-normal">
                {row.label}
              </th>
              <td className={NUMERIC}>{percent(row.previous)}</td>
              <td className={NUMERIC}>{percent(row.current)}</td>
              <td className={NUMERIC}>{signedPoints(row.delta)}</td>
            </tr>
          ))}
        </tbody>
      </ScrollTable>
    </>
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
    <ul aria-label="Evaluation history" className="flex flex-col">
      {results.map((result) => (
        <li key={result.id} className="border-b border-border">
          <button
            type="button"
            aria-pressed={result.id === selectedId}
            onClick={() => onSelect(result.id)}
            className={`flex h-row w-full items-center gap-3 px-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-primary ${
              result.id === selectedId ? "bg-muted" : "hover:bg-muted"
            }`}
          >
            <span className="text-numeric">{formatWhen(result.created_at)}</span>
            <ResultPill result={result} />
            <span className="font-mono text-meta text-muted-foreground">
              {result.reference_set_version}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Admin → Evals (Story 7.6): the selected result (the latest by default) bar by bar and per
 * Agent against the thresholds, the history of results, and the change from the result
 * before it. Read-only: results are written only by `make eval`. */
export function EvalsView({ results }: { results: readonly EvalResult[] }) {
  const [selectedId, setSelectedId] = useState(results[0]?.id ?? "");
  if (results.length === 0) {
    return <p className="p-gutter text-muted-foreground">{EMPTY_STATE}</p>;
  }
  const index = Math.max(
    0,
    results.findIndex((r) => r.id === selectedId),
  );
  const current = results[index];
  const previous = results[index + 1] ?? null;
  return (
    <div className="flex flex-col gap-6 p-gutter">
      <Section id="evals-result" title={index === 0 ? "Latest result" : "Selected result"}>
        <Summary result={current} />
      </Section>
      <Section id="evals-bars" title="Bars">
        <Bars result={current} />
      </Section>
      <Section id="evals-agents" title="Per Agent">
        <PerAgent result={current} />
      </Section>
      <Section id="evals-diff" title="Change from the previous result">
        <Diff current={current} previous={previous} />
      </Section>
      <Section id="evals-history" title="History">
        <History results={results} selectedId={current.id} onSelect={setSelectedId} />
      </Section>
    </div>
  );
}
