# Epic 6 Context: Critic, Red Team and conflicts

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Independent checks try to break the combined multi-agent assessment before a reviewer or an estimate sees it. Conflicts between Assessments are detected (deterministically for structured fields, LLM-assisted for free text) and resolved by the presales engineer (Ravi) with a recorded reason, keeping the dissenting position. A Critic checks coverage, unsupported claims and consistency; a Red Team argues the solution is harder than claimed. Critical Findings block submission until resolved, evidenced or overridden where policy permits. This matters because the platform exists to stop optimistic or internally inconsistent estimates reaching customers. Status at compile time: 6.1, 6.2, 6.3 and 6.5 are done; 6.4 and 6.6 remain.

## Stories

- Story 6.1: Detect Conflicts with deterministic rules
- Story 6.2: LLM-assisted Conflict detection for free text
- Story 6.3: Resolve Conflicts with a reason
- Story 6.4: Critic Review
- Story 6.5: Red Team Review
- Story 6.6: Blocking Findings and overrides

## Requirements & Constraints

- **Critic scope:** Requirement coverage, unsupported claims, contradictions, timeline consistency and dependency completeness across the run's Assessments. Coverage is computed deterministically first (Requirements no Finding or effort line cites) and handed to the agent, which reports each as a coverage Finding; the uncovered Requirement must be found in every eval fixture.
- **Red Team scope:** integrations harder than claimed, incomplete Requirements, overstated capabilities (including claims with no Knowledge Source). Suspected but unevidenced hidden dependencies become Unknowns via `gaps.register_unknown`.
- **Findings:** severity `low | medium | high | critical`; status `open | resolved | overridden`. Every Finding cites its target Finding with its Assessment version, or the Requirement concerned, plus Evidence. Copy is specific and names agents by role.
- **Contradictions are Conflicts, not Findings:** contradictions found by Critic or Red Team go through `conflicts.raise_conflict` with `detected_by = critic | red_team`.
- **Mandatory constraints** (mandatory Checklist items, security controls, authorization policies) are decided only by deterministic rules, never LLM judgement, and Findings tied to them can never be overridden by any role.
- **Blocking:** open critical Critic/Red Team Findings block submission until Evidence is supplied, resolved with a reason, overridden with a reason by a permitted role, or (from Story 10.5) the Opportunity is closed. Overrides never carry over silently to a newer Finding with the same fingerprint.
- **Conflicts:** idempotent per run and fingerprint; a re-run auto-resolves Conflicts that no longer hold. Resolution and escalation always need a reason (422 without), stale `row_version` gives 412, sales reps get 403 with actions hidden.
- **Eval baselines:** each LLM detector has fixtures in `evals/<area>/` and a `make eval-<area>` target (critic: share of seeded defects found; red team: SM-7 target of 60% of known overrun causes surfaced).

## Technical Decisions

- **Ownership:** `assessments` owns Findings, Critic and Red Team Review Assessments and FindingOverride; `conflicts` owns Conflicts and positions. Cross-module access only through public commands/queries.
- **Agents propose, modules accept:** agents return `AgentResult`; agent-specific output lives under `extensions.<agent_id>` with a registered Pydantic schema. Reviews are accepted through `assessments.accept_review` under the same contract and Evidence validation as standard Assessments, with Finding references resolved at their Assessment version. Invalid output is rejected for bounded retry, never written partially.
- **Agent Registry:** each agent is seeded with prompt v1, an extension schema and an immutable read-only config version; runs pin the config version; actor id is `<agent_id>@<semver>`.
- **Model and tools:** model calls only through the ModelGateway (Ollama structured output, low temperature, budgets, recorded calls); tools only through the read-only, task-scoped ToolGateway. Untrusted text enters prompts only inside delimited data blocks; injection-suspected content is flagged on Findings.
- **Orchestration:** plan template tasks `conflict_detection`, `semantic_conflict_detection`, `critic_review` and `red_team_review` run `after` all specialist tasks (so they run even if a specialist was skipped); Critic and Red Team run in parallel. Nodes are thin wrappers: load via queries, call the agent outside any open Unit of Work, submit via `accept_*`, update the task via `workflows`.
- **Transactions and trace:** Unit of Work per request/job step; every command authorizes, checks `row_version` and appends a trace event in the same transaction. Overrides take `pg_advisory_xact_lock(opportunity_id)`.
- **Single blocker check:** `estimates.get_submission_blockers` is the only gate before submit or Baseline; it includes open Conflicts and unoverridden critical Findings (fed by `assessments.get_blocking_findings` and `conflicts.list_open`).

## UX & Interaction Patterns

- Assessments tab: Critic and Red Team each get their own section with version and Findings; the Findings table card shows a severity summary ("1 Critical · 3 High · 2 Medium · 0 Low") and columns Severity (icon + label), Type, Finding, Raised by (agent role), Evidence count. Critical rows sit on the blocker tint. Challenge, Override and Rerun live in the row inspector, not a row-action column.
- Finding pills: Open (blocker colour if critical, otherwise neutral), Resolved, Overridden (shield, neutral). Colour is always paired with icon and label. The tab badge shows the blocking count in blocker colour and updates live.
- Conflicts tab: padded list rows with type, severity, status pill and positions summary; semantic Conflicts are labelled "Detected from text". The Conflict view shows equal-width position cards; resolved Conflicts stay readable, and those resolved against an earlier version carry the tag "Superseded by Assessment v2".

## Cross-Story Dependencies

- 6.4 and 6.5 depend on Epic 5: plan templates with `after` dependencies, the standard Assessment contract and Finding versions (5.3), the ToolGateway (5.4) and bounded retry/failure handling (5.6), plus the specialist agents.
- 6.4 uses `conflicts.raise_conflict` from 6.1; 6.5 (done) is the closest pattern to mirror for agent seeding, review acceptance and the Assessments tab section.
- 6.6 depends on 6.4 and 6.5 and feeds `estimates.get_submission_blockers` (Epic 8); Opportunity close clearing blockers arrives in Story 10.5; the escalation Inbox arrives in Story 9.2.
- Eval baselines from 6.2, 6.4 and 6.5 feed the Epic 7 evaluation harness.
