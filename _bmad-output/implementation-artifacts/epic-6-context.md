# Epic 6 Context: Critic, Red Team and conflicts

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Independent agents try to break the specialist Assessments before a reviewer sees them. Deterministic rules and an LLM-assisted detector surface Conflicts between Assessments. A Critic checks coverage and consistency, and a Red Team argues that integrations are harder, Requirements incomplete, or capabilities overstated. Critical Findings block submission until they are resolved, given Evidence, or overridden with a reason where policy permits. The presales engineer resolves each Conflict with a recorded reason, and the dissenting position is kept. This is the platform's main guard against confident but wrong agents, and it feeds the single submission-blocker check used before submit and Baseline.

## Stories

- Story 6.1: Detect Conflicts with deterministic rules
- Story 6.2: LLM-assisted Conflict detection for free text
- Story 6.3: Resolve Conflicts with a reason
- Story 6.4: Critic Review
- Story 6.5: Red Team Review
- Story 6.6: Blocking Findings and overrides

## Requirements & Constraints

- **Conflict types:** timeline, effort, resource, architecture, security, scope, assumption, evidence. Each Conflict links its positions, their Evidence and a severity (`low | medium | high | critical`).
- **Detection split:** structured fields (effort ranges, timelines, resourcing, scope coverage) use deterministic rules. Free-text contradictions use LLM help. **Mandatory constraints** (unanswered mandatory Checklist items, mandatory security controls) are decided only by rules, never by LLM judgement. Semantic candidates that claim a mandatory violation are discarded.
- **Effort rule threshold:** likely values differing by more than a configured 30% (test the boundary values).
- **Resolution:** the presales engineer chooses a position, enters a different one, or escalates to a named reviewer who has access to the Opportunity. A reason is always required (422 without it). The resolution and every original position are kept in the Decision Trace.
- **Critic** checks Requirement coverage, unsupported claims, contradictions, timeline consistency, dependency completeness and risk coverage.
- **Red Team** argues that integrations are harder, Requirements incomplete, or capabilities overstated (including capability claims with no Knowledge Source behind them). It proposes the hidden dependencies it suspects. Findings must be specific, for example "Red Team: ERP custom fields — no evidence the connector supports them", never "Potential issue detected".
- **Blocking:** open `critical` Critic or Red Team Findings block submission. They clear only by supplying Evidence, being marked resolved (addressed) with a reason, or an authorized override with a reason. Closing the Opportunity clears them only once Story 10.5 exists.
- **Never overridable:** Findings tied to mandatory security Checklist items or authorization policies. No role, including platform administrator, can override them.
- **Override does not carry over silently:** a newer review re-raising the same fingerprint creates an `open` Finding that shows the previous override and offers "Re-apply override".
- **Sales representatives** cannot resolve, escalate or override (403).
- **Quality targets:** Red Team replay must surface at least 60% of known overrun causes as a Gap, Unknown or Red Team Finding. The Critic must find the uncovered Requirement in every fixture. Semantic conflict precision and recall are recorded as the baseline for the Epic 7 eval harness.

## Technical Decisions

- **Ownership:** `conflicts` owns Conflict (and later Negotiation): tables `conflicts_conflicts` and `conflicts_positions`. `assessments` owns Critic and Red Team Reviews (as Assessments), Findings and FindingOverride (`assessments_finding_overrides`). `gaps` owns Unknowns. Cross-module access goes only through `application/public.py`.
- **One owner per blocker:** contradictions found by the Critic or Red Team become Conflicts through `conflicts.raise_conflict` (with `detected_by = critic | red_team`). They are never stored as Findings. Red Team suspicions it can't evidence become Unknowns through `gaps.register_unknown`.
- **Idempotent detectors:** `raise_conflict(uow, …)` is the single command every detector uses, idempotent per run and fingerprint. On rerun, a Conflict that no longer holds is resolved by the system with a reason that names the Assessment version. One that still holds is raised again, linking the previous Conflict.
- **Findings are always referenced with their Assessment version.** Evidence follows the typed, versioned reference rules and is validated on acceptance. Every Finding cites Evidence or is typed as an Unknown or Assumption.
- **Agents propose, never write:** `conflict_agent`, `critic_agent` and `red_team_agent` return `AgentResult` with agent data under `extensions.<agent_id>`. They are accepted through `accept_*` commands (`conflicts.accept_semantic_conflicts`, `assessments.accept_review`). Invalid results are rejected for bounded retry. Each agent has a registry seed with prompt `v1`, an extension schema and a read-only config version. Prompts live at `agents/<agent_id>/prompts/v1.md`. Agent actor IDs are `<agent_id>@<semver>`.
- **Plan tasks:** `conflict_detection` (executor kind `system`), `semantic_conflict_detection`, `critic_review` and `red_team_review` all run `after` every specialist task, so they still run when a specialist was skipped. The Critic and Red Team run in parallel.
- **Deterministic code:** Conflict rules live in `conflicts/domain/rules/` and are unit-tested without DB or LLM. The Critic's coverage pre-check (Requirements cited by no Finding or effort line) is deterministic and is passed to the agent. `policy_ref` (non-overridable) is set deterministically at acceptance.
- **ToolGateway:** a read-only tool returns the run's accepted Assessments and Findings with their versions. Untrusted text goes into delimited data blocks, and the `injection_suspected` flag shows on affected Findings.
- **Mutation path:** every command authorizes through `identity.authorize`, checks `row_version` (If-Match, 412 on mismatch), writes, and appends a trace event in the same Unit of Work. Overrides take `pg_advisory_xact_lock(opportunity_id)` because they affect Baseline checks.
- **Trace events:** `conflicts.conflict.detected | resolved | escalated`, `assessments.finding.resolved | overridden`. Each has a payload model in the trace catalogue.
- **Queries for blockers:** `conflicts.list_open(opportunity_id)` returns open and escalated Conflicts. `assessments.get_blocking_findings(opportunity_id)` returns open critical Findings with their Assessment version. Both feed `estimates.get_submission_blockers`, the only submission check.
- **Statuses:** Conflict `open, negotiating, resolved, escalated`. Finding `open, resolved, overridden`, with resolution kinds `evidence_supplied | addressed`.
- **Evals:** fixtures in `evals/conflicts/`, `evals/critic/` and `evals/red_team/`, run by `make eval-conflicts`, `make eval-critic` and `make eval-red-team`.

## UX & Interaction Patterns

- **Conflicts tab (tab 6):** 32px rows with type, severity, status pill and a positions summary. Open and resolved sections. The tab badge counts open and escalated Conflicts and updates live over SSE. Semantic Conflicts are marked "Detected from text".
- **Conflict view:** equal-width position cards, each with the agent named by role, the value in tabular figures, Evidence chips and the source Assessment version. Superseded versions are struck through. Resolving requires an inline reason. A stale save shows the 412 message with Reload.
- **Assessments tab (tab 5):** separate Critic and Red Team sections with version, Findings and severity. Critical open Findings use the blocker colour and icon. The badge shows the blocking count in the blocker colour and drops live.
- **Finding inspector actions:** Supply Evidence, Mark resolved (reason), and Override (reason plus confirm dialog). Override is hidden when the Finding can't be overridden or the user lacks the action.
- **Status pills** always pair an icon with a label. Conflict: Open (blocker), Negotiating (agent), Resolved (resolved), Escalated (arrow-up, gap). Finding: Open (blocker if critical), Resolved, Overridden (shield, neutral).
- **Escalation** shows on the Overview and in the activity rail, naming the reviewer.
- Blocker red is reserved for real blockers. No vague or celebratory copy.

## Cross-Story Dependencies

- **Within the epic:** 6.1 creates the `conflicts` module and `raise_conflict`, which 6.2, 6.4 and 6.5 use. 6.3 needs 6.1. 6.6 needs the reviews from 6.4 and 6.5.
- **Epic 5:** the assessment plan template, specialist Assessments, the Assessment contract and Evidence validation (Story 5.3), ToolGateway and bounded retry.
- **Epic 4:** `gaps.register_unknown`, and mandatory Checklist items for the rule-based mandatory checks.
- **Epic 8:** `estimates.get_submission_blockers` consumes open Conflicts and unoverridden critical Findings.
- **Epic 9:** Challenge reruns Conflict detection, Critic and Red Team. The Story 9.2 Inbox will list Conflicts escalated to a user. 6.3 creates no Inbox items.
- **Epic 10 (Story 10.5):** closing an Opportunity clears blocking Findings.
- **Epic 7:** the eval harness builds on the baselines recorded here.
- **Epic 14 (R3):** Negotiation extends the Conflict model (`negotiating` status). Consensus never overrides a mandatory constraint.
