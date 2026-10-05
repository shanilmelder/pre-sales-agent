# Epic 5 Context: Multi-agent assessment with live progress

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A presales engineer starts one assessment Workflow Run on an Opportunity. The run plans tasks by Agent capability and runs the Research, Engineering, PM and Security Agents in the background, in parallel where their dependencies allow. Progress shows live in the workspace. Runs survive restarts, stay within budgets and timeouts, can pause indefinitely for a human decision and resume where they stopped, and can be cancelled without losing completed work. Every Agent result goes through one Assessment contract, so no Finding reaches the Opportunity without Evidence or an explicit Unknown or Assumption. Later epics build on these Assessments: the Critic and Red Team, the Estimate draft and Challenge reassessment.

## Stories

- Story 5.1: Start a Workflow Run with pinned inputs and a versioned plan
- Story 5.2: Durable LangGraph execution in the worker
- Story 5.3: Assessments and the standard Assessment contract
- Story 5.4: ToolGateway with task-scoped read-only tools and research snapshots
- Story 5.5: Pause for human input, resume and cancel
- Story 5.6: Budgets, timeouts and failure handling
- Story 5.7: Agent run panel and activity rail
- Story 5.8: Engineering and PM Agents
- Story 5.9: Security and Research Agents and a full assessment run
- Story 5.10: Single-GPU load test and NFR baseline

## Requirements & Constraints

- **Planning:** Plans are versioned, dependency-aware and built by capability (`research`, `engineering_assessment`, `pm_assessment`, `security_assessment`). Dependencies are either `requires` (hard) or `after` (runs once the prerequisite is completed or skipped). A plan must be acyclic. An invalid plan returns 422 and persists nothing. A capability whose Agent is disabled or missing is escalated, never assigned.
- **Durability:** Execution resumes after a restart with no re-executed tasks and no duplicate rows. A duplicate start with the same idempotency key returns the existing run with 200. Duplicate detection never uses the Opportunity alone.
- **Pins:** Every run records the versions of its Sources, active Requirements and Agent config. Assessments cite the pinned Requirement version even if the Requirement is edited mid-run.
- **Human-in-the-loop:** A run can wait indefinitely, then resume. If two users resolve the same decision, the second gets 412. Cancelling keeps accepted Assessments and marks in-flight tasks `skipped`. Cancelling a finished run returns 409, and a cancelled run can't be resumed.
- **Bounds:** Each run has limits on model calls, tokens, tool calls and wall-clock time. A call that would exceed a limit is refused before it is made, and the run ends `failed` with `stop_reason = budget_exhausted:<limit>` while keeping partial results. Only an admin can raise a budget, and a reason is required. Tasks have timeouts with bounded retry (default once), then escalation. Transient failures retry with backoff (default 3), and retries count toward the budgets.
- **Failures:** When no other task can run, a failed or timed-out task interrupts the run with **Retry** or **Skip**. A run that finishes with skipped tasks is never shown as plain success. If the DB goes down, the worker stops changing state, reconnects with backoff and resumes cleanly. Failure records hold typed reason codes and safe messages only.
- **Assessment contract:** Every Finding has at least one Evidence reference that resolves, or is of kind `unknown` or `assumption`. Results that fail validation are rejected whole, and the typed reasons go back for bounded retry.
- **Agent outputs:** Engineering gives feasibility, architecture and one effort line per Integration Type in scope. PM gives approach, phases, a timeline in weeks, a role mix, Work Package effort lines and customer-side dependencies. Security gives requirements, mandatory controls and their effort. Research makes allowlisted fetches only, and every external claim cites a research snapshot.
- **Quality bars:** Every Integration Type in scope has an effort line or an Unknown (100%). At least 95% of cited Evidence supports its Finding. At least 95% of first-try outputs are schema-valid with the default model profile, or the blocker is recorded.
- **Performance:** Start acknowledgement under 2 s P95 and status reads under 500 ms P95, both tested in CI. Agent time is measured separately from API time. Runs beyond `PSA_MAX_ACTIVE_RUNS` queue by priority class, then start time, and report their queue position. These targets get revised after the single-GPU load test.
- **Access:** Only a presales engineer who owns or collaborates on the Opportunity can start, resume or cancel a run. Sales reps and reviewers get read-only views and 403 from the API.
- **Privacy:** Agents receive only task-scoped data. Logs and checkpoints hold IDs only, never customer text.

## Technical Decisions

- **Ownership:** `workflows` owns runs, versioned plans, tasks, pins and `workflows_progress`, and only its commands write run or task status. `assessments` owns Assessments, Findings, Evidence and effort lines. `gaps` owns Unknowns, which are registered through `gaps.register_unknown` in the same Unit of Work. `knowledge` owns Research Snapshots. Cross-module access goes only through `application/public.py`.
- **Statuses:** Run: `queued, running, waiting_for_human, completed, failed, cancelled`. Task: `queued, running, completed, failed, timed_out, skipped`. Both are domain state machines tested without a DB. `platform_jobs.status` is never shown as run status.
- **One start path:** Every run starts through `workflows.start_run(opportunity_id, run_type, trigger_ref, idempotency_key)`, with run types `assessment` and `reassessment` (scoped by capability). The `workflows.execute` job is enqueued in the same Unit of Work.
- **LangGraph:** Graphs run only in the worker, and only `orchestration/` imports `langgraph`. The checkpointer is `langgraph-checkpoint-postgres` on its own pool (`search_path=orchestration_checkpoints`, `autocommit=True`, `row_factory=dict_row`, `LANGGRAPH_STRICT_MSGPACK=true`), with `thread_id = workflow_run_id`. Checkpoint state holds only IDs, counters and budgets, and nodes re-read `workflows` on resume.
- **Node pattern:** Mark the task running, load inputs through queries, call `Agent.run(task)` outside any open Unit of Work, submit through `accept_*`, then mark the task completed. Every command carries `node:<workflow_run_id>:<task_id>:<attempt>`, and a retry after a rejection increments `attempt`.
- **HITL:** `interrupt()` with a typed decision payload sets `waiting_for_human`. Resolving a decision enqueues a `workflows.resume` job that calls `Command(resume=…)`. Side effects before `interrupt()` must be idempotent. Cancellation is checked between nodes.
- **Agents:** Agents are plain classes implementing `Agent.run(TaskInput) -> AgentResult` with a `contract_version`. Agent-specific data lives under `extensions.<agent_id>`. Prompts are at `agents/<agent_id>/prompts/v1.md` with Pydantic extension schemas, and each Agent has one registry config version (model profile, prompt and schema versions, permissions, budgets, timeout). Agent actors are `<agent_id>@<semver>`.
- **Evidence:** References look like `{kind, id, version?, span?}`, and `version` is required for versioned targets. They resolve through their owner (`intake` for requirements and source passages, `knowledge` for chunks, checklist items and research snapshots). Spans are Unicode code-point offsets.
- **Assessments:** A new Assessment for an existing capability becomes the next version, and Findings are always referenced with their Assessment version. Effort is in person-hours `numeric(10,1)`, low/likely/high, and every effort line references a catalogue entry.
- **ModelGateway:** It is the only path to a model. It enforces budgets before calls, uses the priority-aware GPU semaphore (`interactive > background`) and writes a `platform_model_calls` row per call.
- **ToolGateway:** READ-only tools, named by `identity` actions. It checks permissions and restricts results to the task's Opportunity and pinned versions on every call, and counts calls toward the budget. Denials are audited with `platform.tool_call.denied`. Research fetches are HTTPS GET to the `ops/research-allowlist.yaml` hosts only, with redirects re-checked and size and time limits. Pages are stored unchanged and parsed in the sandbox. Untrusted text enters prompts only in delimited data blocks, and the injection heuristic sets `injection_suspected` on affected Findings.
- **Events and telemetry:** Progress rows are streamed over the per-Opportunity SSE stream in the standard frame shape, with `Last-Event-ID` replay. Trace events follow `<module>.<entity>.<past_tense_verb>`, for example `workflows.run.started` and `assessments.assessment.rejected`. OTel spans carry `workflow_run_id`.
- **Concurrency:** Run-control commands use `row_version` with If-Match and return 412 when stale. Errors are problem+json.

## UX & Interaction Patterns

- **Agent run panel (Overview):** One 28px row per task. Each row names the Agent by role, has a Task status pill, elapsed time in tabular figures and a running dot, and updates over SSE. The dot is static under reduced motion.
- **States:**
  - Queued: "Position 2 in queue — the model server is busy".
  - Failed: a red pill with the specific reason, plus inline **Retry** and **Skip**. Accepted results stay and are labelled "partial".
  - Waiting: an amber **Waiting for you** pill with **Resolve**, which opens the decision in the inspector.
  - Budget stopped: the banner "Run stopped: token budget reached. Results so far are kept." with **Rerun selected tasks**, plus **Increase budget** for admins.
  - Cancel: confirmed with "Cancel this run? Completed results are kept."
- **Activity rail (`]`):** The right pane when nothing is selected. It shows task progress and trace events, newest first and virtualised.
- **Run detail:** The plan version with dependencies and escalations, input pins ("Inputs: 3 Sources, 34 Requirements"), usage against budgets and earlier runs.
- **Assessments tab:** One section per Agent with version, recommendation and confidence. Findings are list rows with kind, severity, a status pill, Evidence chips and a "Low confidence" label with its basis. Each section has an effort table, a weak-coverage info banner and the tab badge counts up live.
- **Accessibility and tone:** A polite `aria-live` region throttled to one announcement every 5 s, axe-clean. Copy uses specific failure reasons, names Agents by role and uses no celebration copy.

## Cross-Story Dependencies

- **Order within the epic:** 5.1 → 5.2 (execution wraps the plan), then 5.3 (contract) and 5.4 (tools). 5.5 and 5.6 extend run control, and 5.7 is the UI over 5.5 and 5.6 commands. 5.8 and 5.9 need 5.3 and 5.4. 5.10 needs the full run from 5.9.
- **Earlier epics:**
  - Epic 2: job queue and worker, ModelGateway and structured-output spike, SSE stream, Agent Registry seed, injection heuristic, the Requirement change notice used for **Rerun selected**.
  - Epic 3: catalogue, pgvector retrieval, Knowledge Chunks and Checklists.
  - Epic 4: shared Gap/Unknown state machine, Gaps tab.
  - Epic 1: Unit of Work, authorize, trace, alert email channel.
- **Later epics:**
  - Epic 6: Critic and Red Team run after assessment.
  - Epic 7: registry admin, cost views, eval gate.
  - Epic 8: Estimate drafted from Assessments; Unknowns converted to Assumptions or Risks.
  - Epic 9: Challenge runs reuse `start_run`; Inbox lists waiting runs.
