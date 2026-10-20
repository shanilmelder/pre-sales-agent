# Epic 6 Context: Critic, Red Team and conflicts

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Independent checks try to break the multi-agent assessment before anyone estimates or reviews it. Conflicts between Assessments are detected, deterministically for structured fields and with LLM help for free text. A Critic and a Red Team Agent challenge coverage, unsupported claims and optimism. Critical Findings and open Conflicts become submission blockers. The presales engineer (Ravi) resolves each Conflict with a recorded reason, and the dissenting position is kept in the Decision Trace. This matters because the platform exists to stop estimates that are optimistic or internally inconsistent from reaching customers.

## Stories

- Story 6.1: Detect Conflicts with deterministic rules
- Story 6.2: LLM-assisted Conflict detection for free text
- Story 6.3: Resolve Conflicts with a reason
- Story 6.4: Critic Review
- Story 6.5: Red Team Review
- Story 6.6: Blocking Findings and overrides

## Requirements & Constraints

- **Conflict types:** timeline, effort, resource, architecture, security, scope, assumption, evidence. Each Conflict links its positions (Assessment plus Assessment version, optional Finding, agent, summary or value, Evidence) and has a severity (`low | medium | high | critical`).
- **Detection split:** structured fields are compared by deterministic rules. Free-text Findings are compared by an LLM (semantic comparison). Mandatory constraints (unanswered mandatory Checklist items, mandatory security controls) are decided **only** by deterministic rules, never by LLM judgement. Any LLM candidate that claims a mandatory-constraint violation is discarded.
- **Semantic detection (6.2):** candidates are limited to `architecture | assumption | evidence | scope`. Each must cite at least two Findings with their Assessment versions, plus a severity. Every Finding reference must resolve at its version. A candidate whose fingerprint matches an existing rule-based Conflict is dropped as a duplicate. Invalid output is rejected and goes back for bounded retry or escalation; it is never written partially.
- **Idempotency:** raising a Conflict is idempotent per run and fingerprint. On a re-run, a Conflict that no longer holds is auto-resolved with a specific reason ("No longer present in Engineering Assessment v3"). One that still holds is raised again and links to its predecessor.
- **Resolution:** choose a position, enter a different one, or escalate to a named reviewer who has access to the Opportunity. A reason is always required (missing reason gives 422 problem+json). Resolving preserves every original position in the trace. A stale `row_version` gives 412.
- **Blocking:** open `critical` Critic and Red Team Findings block submission until they are evidenced, resolved with a reason, or overridden with a reason by a permitted role. Findings tied to a mandatory security or authorization policy can never be overridden by any role, including admin. Overrides never carry over silently to a newer Finding with the same fingerprint.
- **Permissions:** sales representatives can't resolve, escalate or override (403, and the actions are hidden).
- **Quality baselines:** each LLM detector has an eval fixture set under `evals/<area>/` with a `make eval-<area>` target. For 6.2, record precision and recall per Conflict type as the baseline for the later evaluation harness. Red Team is measured against the target of surfacing ≥60% of known overrun causes.

## Technical Decisions

- **Ownership:** the `conflicts` module owns `conflicts_conflicts` (status `open | negotiating | resolved | escalated`; `detected_by` `rule | semantic | critic | red_team`; fingerprint; run; `row_version`) and `conflicts_positions`. Other modules reach it only through `conflicts/public.py`: `raise_conflict(uow, …)` is the single command every detector uses, and `list_open(opportunity_id)` feeds blocker checks. `assessments` owns Findings, Critic and Red Team Reviews, and FindingOverride.
- **Agents propose, never write:** an agent is a plain class, `Agent.run(TaskInput) -> AgentResult`. Agent-specific output goes only under `extensions.<agent_id>` with a registered schema. The owning module's `accept_*` command (for 6.2, `conflicts.accept_semantic_conflicts`) validates the base contract, the extension, the references and the permissions, then stores the result.
- **Agent Registry:** each new agent (`conflict_agent`, `critic_agent`, `red_team_agent`) is seeded with prompt v1 at `agents/<agent_id>/prompts/v1.md`, a Pydantic extension schema (JSON Schema is generated from it) and an immutable, read-only config version (model profile, prompt and schema version, permissions, budgets). Runs pin the config version. The agent's actor id is `<agent_id>@<semver>`.
- **Model access:** only through the ModelGateway, which uses the Ollama native `/api/chat` with `format` set to the output JSON Schema, low temperature, Pydantic validation with bounded retry, run budgets, a GPU slot, and a `platform_model_calls` row. The default chat model is `gpt-oss:20b`, and context size comes only from the model profile.
- **Tools:** read-only and task-scoped, through the ToolGateway. Untrusted text enters prompts only inside delimited data blocks, and the injection flag is recorded on affected Findings.
- **Orchestration:** LangGraph is used only in `orchestration/`, and nodes are thin wrappers (load through queries, call the agent, submit through `accept_*`, update the task through `workflows`). Detection tasks run `after` all specialist tasks, so they also run when a specialist was skipped. `semantic_conflict_detection` runs in parallel with the `system`-executor `conflict_detection`, and `critic_review` runs in parallel with `red_team_review`. Node commands carry idempotency keys (`run:` / `node:` / `out:`).
- **Transactions:** a Unit of Work per request or job step. Every command calls `identity.authorize`, checks `row_version` and appends a trace event in the same transaction. LLM calls never happen inside an open Unit of Work.
- **Trace events:** `conflicts.conflict.detected | resolved | escalated`, plus `assessments.finding.resolved | overridden`. Findings are always referenced together with their Assessment version.
- **Single blocker check:** `estimates.get_submission_blockers` is the only gate. It includes open Conflicts and unoverridden critical Findings. Overrides take `pg_advisory_xact_lock(opportunity_id)`.
- Contradictions found by the Critic or Red Team become Conflicts (`detected_by = critic | red_team`) and are not stored as Findings.

## UX & Interaction Patterns

- Conflicts are tab 6 of the workspace (key `6`). The badge counts open and escalated Conflicts and updates live over SSE. Rows are 32px and show type, severity, status pill and a positions summary. Semantic Conflicts are labelled "Detected from text".
- Conflict status pills: Open (blocker colour), Negotiating (agent), Resolved (resolved green), Escalated (arrow-up, gap colour). Colour is always paired with an icon and a label.
- Conflict view: equal-width position cards, with the agent named by role, the value in tabular figures, Evidence chips and the source Assessment version (struck through when superseded). Resolution requires a reason. Resolved Conflicts stay readable in a resolved section.
- Critic and Red Team Reviews have their own sections in the Assessments tab. Critical open Findings use the blocker colour. Copy is specific and names agents by role, with no emoji.

## Cross-Story Dependencies

- 6.1 creates the `conflicts` module, tables, `raise_conflict`, fingerprints and the Conflicts tab. 6.2 depends on all of these and on rule fingerprints for deduplication.
- 6.2, 6.4 and 6.5 depend on Epic 5: plan templates with `after` dependencies, the standard Assessment contract and Finding versions (5.3), the ToolGateway (5.4), failure handling and bounded retry (5.6), and the Engineering, PM, Security and Research Agents (5.8, 5.9).
- 6.3 builds on 6.1 and 6.2. The Inbox for escalated Conflicts arrives in Story 9.2.
- 6.6 depends on 6.4 and 6.5. Closing an Opportunity clears blockers only from Story 10.5 onwards. The blockers feed `estimates.get_submission_blockers` (Epic 8).
- Eval baselines from 6.2, 6.4 and 6.5 feed the Epic 7 evaluation harness and CI gate.
