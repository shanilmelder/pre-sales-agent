---
review: adversarial
target: ../ARCHITECTURE-SPINE.md
reference: ../../../prds/prd-pre-sales-agent-2026-10-01/prd.md
date: '2026-10-01'
method: 'Two-unit incompatibility construction: for each seam, build two units (epics/modules by different developers or AI agents) that each obey every AD literally, then show where they still fail to fit.'
verdict: 'NOT READY FOR EPIC BREAKDOWN — revise spine first'
---

# Adversarial Review: Architecture Spine (Agentic AI Presales Platform)

## Verdict

**Not ready for epic breakdown.** The spine is strong on *mechanism*: one mutation path, proposal-only agents, gateways, append-only trace, one queue. It is weak on *ownership and vocabulary at the seams*. AD-2 says "every entity has exactly one owning module", but the spine never says which module owns several of the entities the PRD depends on most: Unknown, Risk, Workflow Run, Task, Challenge, Override, and the Opportunity lifecycle status. In two places the spine breaks its own rules: `trace_events` is written by every module, and the Baseline pointer sits in an `opportunities` table that `estimates` changes. Contracts that cross module boundaries are named but not given a shape: idempotency keys, job types, SSE payloads, the vocabularies of non-run statuses, and Evidence versioning. Any two agents building in parallel will diverge at each of these points, and every such unit will still pass a literal AD-compliance check.

## Holes by severity

| Severity | Count | IDs |
| --- | --- | --- |
| Critical | 4 | H1, H2, H3, H4 |
| High | 4 | H5, H6, H7, H8 |
| Medium | 6 | M1–M6 |
| **Total** | **14** | |

Critical means two literally compliant units cannot be integrated without rewriting one of them, or the compliant build violates a PRD invariant (FR-14, FR-62, FR-41, FR-16). High means integration is possible but needs a negotiated rework, or the gap creates silent data or behaviour divergence. Medium means local inconsistency, fixable at story level if a convention is added.

---

## Critical

### H1. Unknowns, Risks and Assumptions have no single owner, and nobody owns Gap→Assumption conversion

**ADs involved:** AD-2, AD-4, AD-11, AD-13; Capability map rows 4.4, 4.6, 4.9. **PRD:** FR-14, FR-25, FR-34.

**What the spine says.** An `AgentResult` (AD-4) carries Findings, Evidence, Assumptions, Unknowns and Risks (FR-25), and it is accepted by "the owning module's `accept_*` command". The ERD makes `ESTIMATE_VERSION ||--o{ ASSUMPTION`, which puts Assumption in `estimates`. Unknown and Risk appear in neither the ERD nor the module list. FR-14 demands that every open Gap and Unknown is converted to an Assumption or Risk before submission.

**Unit A: Assessments epic (developer 1).** `assessments.accept_assessment(agent_result)` stores everything in the result under its own prefix: `assessments_findings`, `assessments_assumptions`, `assessments_unknowns`, `assessments_risks`. That's AD-2 compliant, because the module owns the Assessment and its contents.

**Unit B: Estimates epic (developer 2).** `estimates_assumptions(estimate_version_id, kind, gap_id?, finding_id?, accepted_by, ...)` follows the ERD, and is also AD-2 compliant.

**Unit C: Gaps epic (developer 3).** `gaps.resolve_gap(gap_id, resolution: answered | assumption | risk, payload)` stores the resolution and the Assumption text in `gaps_resolutions`, because Gap resolution is a Gap state change (AD-3). That's compliant too.

**Clash.**
- There are now three Assumption shapes in three tables.
- FR-14's submission check in `estimates` must ask `gaps.public` about open Gaps. It must also ask somebody about open Unknowns, and nobody owns Unknown as an entity with a lifecycle.
- A Gap converted in `gaps` never shows up in `estimates_assumptions`, so FR-34 ("accepted by" before submission) can't see it.
- Assumptions are per Estimate Version (ERD) but Gaps are per Opportunity. When v2 is created, does a Gap resolved as an Assumption on v1 count as resolved for v2? Each developer will answer differently.
- Risk has no table anywhere, so `kind: risk` resolutions vanish. FR-14's whole purpose is that unknowns cannot vanish.

**Proposed rule: AD-23, Uncertainty ownership and conversion.**
- `gaps` owns **Gap** and **Unknown**. An Unknown is a Gap with `origin: agent_unknown | checklist | detection`. Both share one lifecycle: `open → answered | converted_to_assumption | converted_to_risk | dismissed`.
- `estimates` owns **Assumption** (`kind: condition | contingency`) and **Risk**, both scoped to an Estimate Version. Each carries exactly one `origin_ref: {kind: gap | finding, id}`.
- Conversion is one command, `estimates.register_assumption_from_gap` (or `register_risk_from_gap`), which calls `gaps.mark_converted(gap_id, target_ref)` through `gaps.application.public`. The rule for transactions spanning two modules is in H3.
- `assessments.accept_assessment` stores **only** Assessment and Finding. It forwards Unknowns to `gaps.raise_from_agent_unknown`, and forwards agent-proposed Assumptions and Risks as `estimates.propose_assumption` (status `proposed`, `accepted_by` null).
- When a new Estimate Version is created, unresolved and accepted Assumptions and Risks are carried forward explicitly (copied with a `carried_from_id`). FR-14 checks the version being submitted.

### H2. Nobody owns Workflow Run and Task, and task status has three competing sources of truth

**ADs involved:** AD-2, AD-3, AD-5, AD-6, AD-7; Consistency "Statuses". **PRD:** FR-3, FR-15–FR-19, FR-63.

**What the spine says.**
- The ERD has `WORKFLOW_RUN` and `TASK`, and the Statuses row defines their vocabularies.
- The source tree has no `workflows` module. `orchestration/` sits outside the modules and "drives the modules only through `application/public.py`".
- AD-6 puts "task statuses" in the checkpoint.
- AD-7 puts the run status `waiting_for_human` / `cancelled` on "Workflow Run status", and `platform_jobs` has its own claim and finish state.

**Unit A: Orchestration epic.** Run and task status live in LangGraph state, as AD-6 says. Run status is mirrored to a new table, `orchestration_runs`, written by orchestration code, because orchestration "owns" it. Orchestration isn't a module, so AD-3's "application-service command" doesn't obviously apply.

**Unit B: Opportunity Workspace / live progress epic.** FR-3 needs task-by-task progress. The developer adds `opportunities_workflow_runs` and `opportunities_tasks`, written through `opportunities.record_task_status` commands that emit trace events, because SSE comes from `trace_events` (AD-12).

**Unit C: Platform jobs.** `platform_jobs.status` uses `pending | claimed | done | error`.

**Clash.**
- There are two run tables, plus the checkpoint and the job row, which makes four status sources.
- Cancel (AD-7) is "an API command that sets status `cancelled`". Unit B's API updates `opportunities_workflow_runs`, while Unit A's worker checks `orchestration_runs` or the checkpoint between nodes. Cancellation never takes effect.
- AD-7 says a duplicate start "returns the existing run". The two units dedupe against different tables.
- The `timed_out` Task status (FR-19) can only be set by a timer, but AD-3 allows no non-command writer.
- FR-63's "pinned input versions" has no home.

**Proposed rule: AD-24, the `workflows` module owns runs and tasks; the checkpoint is a cache.**
- Add a business module `workflows`. It owns `workflows_runs` (with status, plan version, pinned input versions under FR-63, budgets used, and idempotency key) and `workflows_tasks` (with status, attempt, agent_id@version, failure reason, and deadline).
- Its commands are the **only** writers of run and task status: `start_run`, `mark_task_started`, `mark_task_completed`, `mark_task_failed`, `mark_task_timed_out`, `request_human`, `resume_run`, `cancel_run`. Each one is an AD-3 command and emits trace events.
- Orchestration nodes call these commands and never write tables. LangGraph state may *copy* statuses for routing, but on resume it re-reads them from `workflows`, and on disagreement `workflows` wins.
- `platform_jobs.status` is infrastructure only, with its own enum (`available, claimed, succeeded, failed, dead`). It is never shown to users and never used as run status.
- Cancellation is checked against `workflows_runs.status`.
- Task timeouts are enforced by the worker. The worker calls `mark_task_timed_out` as the system actor.

### H3. `trace_events` breaks AD-2 by construction, and "same transaction" across modules is undefined

**ADs involved:** AD-2, AD-3, AD-12; Capability map row 4.11 ("`trace` (read side), all commands (write side)").

**What the spine says.** AD-2 says only the owning module's adapters write its table, and the table is named `trace_events`, so the `trace` module owns it. AD-12 says every command in every module writes it in its own transaction. AD-3 says "each command, in one DB transaction".

**Unit A: Estimates developer.** Reads AD-2 strictly and calls `trace.application.public.append_event(...)`. The `trace` module's command opens its own session and transaction (AD-3: "each command, in one DB transaction"). The trace row commits separately, so a rollback in `estimates` leaves an orphan trace event, and a trace failure after the estimates commit leaves state with no trace. That breaks AD-12's "Prevents" line.

**Unit B: Gaps developer.** Reads AD-12 literally ("in the same transaction") and has the `gaps` adapter INSERT into `trace_events` directly. That breaks AD-2, and the developer gives `payload` a different key style.

**Same problem, more generally.** H1's conversion, FR-13's Gap answer → Requirement update, FR-38's Challenge → new Estimate Version, and FR-62's set-Baseline gating all have one module's command calling another module's command. AD-3 says each command is its own transaction, so a cross-module operation either runs as two transactions (and can be left half done) or as nested ones (and nobody has said how).

**Proposed rule: AD-25, Unit of Work and the trace writer.**
- `platform.db` provides a request-scoped **Unit of Work**. The outermost command opens it. Commands called through another module's `public.py` *join* the caller's Unit of Work and never open a transaction of their own. One business action means one transaction, whichever modules take part.
- `trace_events` is reclassified as a **platform-owned table** (`platform_trace_events`). Writes go only through `platform.trace.append(uow, TraceEvent)`, which is typed and can only be called with an active Unit of Work. The `trace` module owns only read models and queries.
- AD-2 gets an explicit exception list: platform tables written by every module only through a platform port, namely `platform_trace_events`, `platform_jobs` and `platform_idempotency`.
- `payload` is a Pydantic model per `event_type`, registered in a single `trace_event_catalog.py`. An unregistered `event_type` raises an error.

### H4. The Baseline pointer and Opportunity lifecycle status are written into another module's table, and set-Baseline gating can race

**ADs involved:** AD-2, AD-3, AD-11 ("`opportunities.baseline_estimate_version_id` ... changes only through `estimates.set_baseline`"). **PRD:** FR-2, FR-39, FR-46, FR-62.

**What the spine says.** AD-11 places the pointer as a column on the `opportunities` table but gives write authority to the `estimates` module. Under AD-2, `estimates` adapters may not write `opportunities_*`. The spine contradicts itself here.

**Unit A: Estimates developer.** Writes the column directly, as AD-11 permits.

**Unit B: Opportunities developer.** Under AD-2 that table is theirs, so they expose `opportunities.set_baseline_pointer` with their own `identity.authorize(..., "opportunity.update")`. A compliant `scenarios.promote` (FR-46) calls this command directly and skips the FR-62 gating that lives in `estimates.set_baseline`.

**Related clash: lifecycle status.** FR-2's Opportunity lifecycle status (`intake, gaps_open, assessing, in_review, approved, delivered, closed`) depends on state in `gaps`, `workflows`, `reviews` and `estimates`. Unit B stores a `status` column that other modules must update by calling `opportunities.set_status`, which couples every module to opportunities. Unit C (the workspace UI) derives status in a `reporting_` view. The two disagree, and SSE has no event for a derived status.

**Race.** `set_baseline` reads `reviews.public` ("all approved"), `assessments.public` ("no blocking Finding") and `gaps.public` ("no open Gap"), then writes. A concurrent `reviews.reject` or `assessments.accept_*` (a Critic rerun adding a blocking Finding) commits between the reads and the write. That breaks FR-62, because `row_version` only protects the row being written.

**Proposed rule: AD-26, Baseline and lifecycle ownership.**
- The Baseline lives in `estimates_baselines(opportunity_id PK, estimate_version_id, set_by, set_at, row_version)`, owned by `estimates`. The `opportunities.baseline_*` column is removed.
- `estimates.set_baseline` is the **only** path to the Baseline. Scenario promotion and reassessment call it. They never call anything else.
- Gating runs inside the AD-25 Unit of Work and first takes `SELECT … FOR UPDATE` on the Opportunity's `opportunities_opportunities` row. **Every** command that can change a gating condition (review decisions, accepting Findings, Gap state, overrides) takes the same lock. This is the per-Opportunity serialization lock.
- Opportunity lifecycle status is **derived** by `opportunities.get_status` from the other modules' public queries. It is never stored or written by other modules. The SSE event `opportunities.status.changed` is emitted by `platform.trace` after any command whose event type is listed as status-affecting.

---

## High

### H5. Findings, Conflicts and blocking overrides: duplicate detectors and references that go stale

**ADs involved:** AD-2, AD-10, AD-13; Capability map rows 4.7 (Critic/Red Team in `assessments`) and 4.8 (`conflicts`). **PRD:** FR-27, FR-29, FR-30, FR-31, FR-38.

**What happens.**
- The Critic Agent's FR-27 brief includes "contradictions across Assessments". Unit A (Assessments) stores those as Critic Findings with `severity: critical`, which blocks submission under FR-29.
- Unit B (Conflicts) runs FR-30 detection (structured deterministic comparison plus an LLM text comparison) and stores `conflicts_conflicts` with `positions: [finding_id, ...]`.
- The same contradiction now exists twice. One copy is blocking, the other isn't. Resolving the Conflict (FR-31) doesn't clear the Critic Finding.
- Conflict positions reference `finding_id`. A Challenge rerun (FR-38) creates a new Assessment with new Finding IDs, so the old Conflict points at superseded Findings and stays open forever, or is silently orphaned.
- Nobody owns the FR-29 **override** entity. `assessments` could own it (it owns the Finding), or `reviews` could (it's a human approval act), or `conflicts` could (if Conflicts can be blocking). AD-13's Evidence kinds don't include `finding` or `assessment`, so a Conflict position can't even be a typed Evidence reference.

**Proposed rule: AD-27, the Finding / Conflict / Block contract.**
- `assessments` owns Assessment, Finding and **FindingOverride**. Assessments are versioned, and every Finding is addressed as `(finding_id, assessment_version)`.
- `conflicts` owns Conflict and ConflictResolution. Positions are `{assessment_id, assessment_version, finding_id}`.
- The Critic and Red Team may **not** emit "contradiction" Findings. Contradictions between Assessments are only ever Conflicts. Critic output with `category: contradiction` is routed to `conflicts.propose_conflict`.
- Blocking is computed in one place: `estimates.get_submission_blockers(version)`. It unions blocking Findings, unresolved Conflicts with blocking severity, open Gaps and Unknowns (H1), and unaccepted Assumptions, and returns typed reasons. Both submit and set-Baseline use it.
- When an Assessment is superseded, `conflicts` re-evaluates the Conflicts that reference it. Each one is marked `superseded` (and re-detected) in the same Unit of Work.
- Add `finding` and `assessment` (each with a version) to the AD-13 Evidence kinds.

### H6. Review vs Challenge: split ownership of one workflow, a polymorphic review target, and approvals that never expire

**ADs involved:** AD-2, AD-3, AD-7, AD-11; Capability map row 4.10. **PRD:** FR-37, FR-38, FR-62.

**What happens.**
- The ERD has `ESTIMATE_VERSION ||--o{ REVIEW_REQUEST`, but FR-37 also allows Review Requests on "specific Assessments". Unit A (Reviews) models `reviews_requests(estimate_version_id NOT NULL)`. Unit B (an Assessments developer who needs security review of one Assessment) adds `assessments_review_requests`, which creates a second owner of Review Request.
- A Challenge is one of the reviewer actions (FR-37), so Unit A stores it as `reviews_decisions(action='challenge')`. FR-38 also lets a presales engineer Challenge a Finding *outside* any Review Request, so Unit B adds `assessments_challenges`.
- Under FR-38, a Challenge causes three things: a confirmed rerun (a Workflow Run), a new Estimate Version, and a forced Conflict, Critic and Red Team rerun. `reviews` could enqueue the run directly (AD-7 lets "an API command" enqueue a job), or it could call `workflows.start_run`. `estimates` could create the version when the run finishes, or `reviews` could. Nobody owns the Challenge lifecycle.
- Approvals aren't tied to content. Approvals on v3 don't apply to v4, but nothing in the spine says a new version voids pending Review Requests. A compliant `set_baseline` that counts "approved Review Requests for this Opportunity" would accept stale approvals. Review Request status vocabulary is also undefined.

**Proposed rule: AD-28, Review and Challenge ownership.**
- `reviews` owns **ReviewRequest**, **ReviewDecision** and **Challenge**. The review target is a typed reference `{kind: estimate_version | assessment, id, version}`, with no foreign key into another module's table.
- A Challenge can exist without a ReviewRequest (`review_request_id` nullable).
- Review Request statuses: `pending, approved, rejected, challenged, more_evidence_requested, alternative_requested, escalated, superseded`. Challenge statuses: `open, rerun_confirmed, rerun_running, resolved, withdrawn`.
- A Challenge never writes elsewhere. On confirmation, `reviews.confirm_challenge_rerun` calls `workflows.start_run(kind=challenge_rerun, challenge_id, task_scope)`. Only the workflow's final node creates the new Estimate Version, through `estimates.create_version_from_run`.
- Creating Estimate Version N+1 sets every pending or approved ReviewRequest targeting version N to `superseded`, in the same Unit of Work. Gating counts only approvals whose target `version` equals the version being baselined.

### H7. Idempotency keys, job types and the transactional enqueue have no defined format

**ADs involved:** AD-4, AD-6, AD-7, AD-17. **PRD:** FR-16, FR-19.

**What happens.**
- AD-6 defines the key as `(workflow_run_id, task_id, attempt_scope)` but never defines `attempt_scope`.
- Unit A (Orchestration) sets `attempt_scope = attempt_number`. AD-4 sends a rejected `AgentResult` back for retry. The retry gets `attempt=2`, and a crash between `accept_*` committing and the checkpoint write replays attempt 1 safely. So far so good.
- Unit B (Assessments) stores keys in `assessments_idempotency(key text)` formatted as `f"{run}:{task}"`. It ignores the scope, so every retry returns the cached first rejection, and the task can never succeed.
- Unit C (Integrations, AD-17) uses `hubspot:{deal_id}:{hash(payload)}`. Unit D (the run start in AD-7) uses `opportunity_id` alone, which makes a legitimate second run (a Challenge rerun, H6) impossible.
- Job types are free strings: `resume`, `run.resume` and `ResumeRun` all appear. The `resume` payload (which run, which interrupt, which human decision) is unspecified, so two producers can't share one consumer.
- When a command enqueues a job (an outbound CRM write, a reminder, a run start), Unit A inserts the job inside its Unit of Work. Unit C inserts it after commit, and loses it on a crash.

**Proposed rule: AD-29, idempotency and the job contract.**
- **One store.** `platform_idempotency(key PK, command, request_hash, result_ref, created_at)` is written by the Unit of Work. A duplicate key with the same hash returns the stored result. A different hash raises `409 idempotency_conflict`.
- **One key grammar.** `<scope>:<parts…>`, built only by the `platform.idempotency.key(...)` helpers:
  - node command: `node:{workflow_run_id}:{task_id}:{node_name}:{attempt}`, where `attempt` increments on every validation retry or timeout retry and replays reuse the same value;
  - run start: `run:{opportunity_id}:{run_kind}:{trigger_id}`, where `trigger_id` is a client-supplied UUID for user starts, or a challenge ID or change-set ID;
  - outbound: `out:{integration}:{entity}:{local_id}:{local_version}`;
  - API mutations: the `Idempotency-Key` header, with UUIDv7 required on POST.
- **Job registry.** `platform.jobs` registers a closed set of `job_type` values (`workflow.start`, `workflow.resume`, `workflow.cancel_check`, `integration.outbound`, `knowledge.ingest`, `knowledge.reembed`, `reviews.reminder`, …). Each has a Pydantic payload model, versioned with `payload_version`.
- **Transactional enqueue.** `platform.jobs.enqueue(uow, ...)` writes the `platform_jobs` row inside the caller's Unit of Work. Enqueueing outside one is forbidden.
- The `workflow.resume` payload is `{workflow_run_id, interrupt_id, decision_ref: {kind, id}}`. The resume value passed to `Command(resume=…)` contains IDs only (AD-6).

### H8. SSE payloads and event vocabulary are undefined, and non-command progress never reaches the stream

**ADs involved:** AD-12, AD-16; Consistency "Trace event types". **PRD:** FR-2, FR-3, FR-58, FR-64.

**What happens.**
- AD-12 says SSE is driven by `trace_events` inserts through `LISTEN/NOTIFY`. Postgres NOTIFY payloads are limited to about 8 KB.
- Unit A (the platform/trace developer) sends the whole row as the NOTIFY payload. It works in tests and fails in production on large Finding payloads.
- Unit B (the web developer) expects `{type, data}` frames with `event:` set to the trace `event_type`. Unit A emits a single unnamed `message` event carrying JSON.
- Event names drift even under the `<module>.<entity>.<past_tense_verb>` convention: `workflows.task.status_changed` versus `workflows.task.started` / `.completed`, and `gaps.gap.converted` versus `gaps.gap.converted_to_assumption`.
- FR-3's partial results and the "running" state come from orchestration progress. If H2 isn't fixed, that progress isn't a command, so it isn't a trace event, so it never reaches SSE. If it is fixed, every task heartbeat becomes an immutable audit row and bloats the trace that FR-41 wants to contain only decision-relevant events.
- Reconnect (`Last-Event-ID`) behaviour is unspecified. Per-event authorization is also unspecified: a sales rep (FR-64) can't see some Assessment and Estimate detail, but the stream is per Opportunity.

**Proposed rule: AD-30, the SSE envelope and event catalogue.**
- NOTIFY carries only `{"id": "<trace_event_id>", "opportunity_id": "..."}`. The API process re-reads the row and authorizes it per subscriber, by calling `identity.authorize(actor, "trace.read", subject)`, before sending.
- Every SSE frame is `id: <trace_event_id>`, `event: <event_type>`, `data: {event_type, subject: {type, id, version}, occurred_at, actor: {type, id}, summary: <event-specific DTO from the catalogue>}`. Clients re-fetch full entities through the REST API. The frame never carries entity bodies.
- `Last-Event-ID` replay reads `trace_events` with `id > last`, which works because UUIDv7 IDs are time-ordered.
- **Two tiers.** Decision events go to `trace_events`. Progress events (task started, heartbeat, token-budget usage) go to a non-audit `workflows_progress` table, which is pruned after N days and delivered on the same stream with `event: progress.*`. Status transitions to `completed`, `failed`, `timed_out` and `waiting_for_human` are decision events.
- The event catalogue (H3) is the single list of allowed `event_type` values. Status changes use one verb per target status (`workflows.task.completed`), never `status_changed`.

---

## Medium

| ID | Hole | Two compliant, incompatible units | Proposed rule |
| --- | --- | --- | --- |
| M1 | **Evidence references to versioned entities aren't versioned** (AD-11 vs AD-13). Requirements carry version numbers, but `{kind: requirement, id}` has no version. `source_passage` has no table owner. `span` offsets have no stated reference text. | Intake measures spans against the docling-extracted text. The Proposals module measures them against the raw file bytes. Highlighting (FR-5) breaks. A Requirement edited after it was cited silently changes what the Evidence supports. | Add `version` to every Evidence kind that points at a versioned entity. `source_passage` is owned by `intake` (`intake_source_passages`, immutable, holding `source_version_id` and the offsets into the stored extracted-text artifact, hashed per AD-18). Spans are always UTF-8 code-point offsets into that artifact. |
| M2 | **Scenario ownership is split** across `scenarios` and the `estimates` table (AD-11 says Scenarios "are Estimate Versions with `scenario_id`"). | `scenarios` writes `estimates_versions` rows for its Scenario. `estimates` rejects them because of `scenario_id` foreign-key checks on its own side. | `scenarios` owns Scenario metadata and the constraint deltas only. Scenario Estimate Versions are created through `estimates.create_version(scenario_id=…)`. Promotion goes through `estimates.set_baseline` (H4). |
| M3 | **Status vocabularies exist only for Run and Task.** Gap, Unknown, Clarification Question (FR-12 lists `drafted, approved, sent, answered, unanswered`), Conflict, Finding, Assumption, Review Request, Challenge, Estimate Version and Opportunity have none. | The UI filters on `open`, while the backend emits `OPEN` or `pending`, and so on. | Add a Statuses table for every lifecycle entity, each with its allowed transitions, as domain state machines. |
| M4 | **The `authorize` action and resource vocabulary is undefined** (AD-15). Agent service principals aren't tied to `actor_id`. | Estimates authorizes `"estimate:edit"`, Reviews authorizes `"approve_estimate"`, and the Registry permissions use tool names. | Action grammar is `<module>.<entity>.<verb>`, matching the command name, and lives in one catalogue. Agent `actor_id` = `"<agent_id>@<semver>"`. Agent Registry permissions use the same action names. |
| M5 | **The `AgentResult` contract version and agent `schemas.py` can drift** (AD-4 vs AD-21). | Each agent extends the base Assessment with ad hoc fields. `accept_*` validates against the base and drops the extra data, or validates against the agent schema and rejects the base. | `AgentResult` is the base model in `agents/contract.py`, with `contract_version`. Agent schemas may only add fields under `extensions: {agent_id: …}`. `accept_*` validates both the base and the registered extension. |
| M6 | **Answering a Gap updates a Requirement (FR-13) across modules, and that can conflict with FR-6** ("human edits are never overwritten"). | Gaps calls `intake.update_requirement`, which overwrites a human-edited field. Alternatively, intake ignores the call because the field is human-owned, and the Gap shows as answered while the Requirement stays stale. | `gaps.record_answer` creates a new Opportunity Source (`kind: gap_answer`) and calls `intake.propose_requirement_change`. Human-edited fields produce a pending change for confirmation and are never applied automatically. |

---

## Cross-cutting recommendation

Add a **"Shared Contracts" section** to the spine, next to the Consistency Conventions, holding the canonical owned-by table. Every entity in the ERD, plus Unknown, Risk, Challenge, Override, Workflow Run, Task, Baseline and Idempotency record, gets exactly one row naming its owning module, its table prefix and its creating command. Then add the six artefacts the holes above need, each as a single file that epics import rather than re-declare:

1. `platform/db/uow.py`, the Unit of Work (H3).
2. `platform/trace/catalog.py`, the event types and payload models (H3, H8).
3. `platform/jobs/registry.py`, the job types and payload models (H7).
4. `platform/idempotency/keys.py`, the key builders (H7).
5. `agents/contract.py`, `AgentResult` and the Evidence reference (H5, M1, M5).
6. `identity/actions.py`, the authorization action catalogue (M4).

Fold AD-23 to AD-30 into the spine, or tighten the existing ADs, and the 14 seams above become compile-time or migration-time failures rather than integration-time surprises.
