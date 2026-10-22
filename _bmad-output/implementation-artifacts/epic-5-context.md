# Epic 5 Context: Multi-agent assessment with live progress

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Let a presales engineer press **Run assessment** on an Opportunity and have the Research, Engineering, PM and Security Agents assess it, in parallel where possible, while the engineer watches each task live. Runs execute in the background worker. They survive restarts without losing or duplicating work, stay within budgets and timeouts, can be cancelled, and pause for human decisions as long as needed. Every Agent result is validated against one Assessment contract, so no Finding enters the Opportunity without Evidence or an explicit Unknown or Assumption. This epic turns the structured Requirements, Knowledge Base and Gaps from Epics 2–4 into evidence-backed Assessments that later Estimates are built from.

## Stories

- Story 5.1: Start a Workflow Run with pinned inputs and a versioned plan
- Story 5.2: Durable LangGraph execution in the worker
- Story 5.3: Assessments and the standard Assessment contract
- Story 5.4: ToolGateway with task-scoped read-only tools and research snapshots
- Story 5.5: Pause for human input, resume and cancel
- Story 5.6: Budgets, timeouts and failure handling
- Story 5.7: Agent run panel and Activity tab
- Story 5.8: Engineering and PM Agents
- Story 5.9: Security and Research Agents and a full assessment run
- Story 5.10: Single-GPU load test and NFR baseline

## Requirements & Constraints

- **Planning:** plans are built from the Opportunity's Requirements, products and Integration Types, selecting the enabled Agent for each capability. Dependencies are explicit, independent tasks run concurrently, and plans are versioned and visible. A disabled or missing Agent is excluded and its tasks are escalated to the presales engineer.
- **Durability:** run state persists at each step and resumes after a restart without losing completed work. A duplicate start returns the existing run.
- **Human pause:** a run can wait indefinitely for human input and resume where it stopped.
- **Bounded execution:** every task has a timeout. Every run has limits on model calls, tokens, tool calls and wall-clock time. When a limit is hit the run stops safely, keeps partial results, and notifies the engineer and the administrator.
- **Failures:** transient failures are retried within policy. Invalid output is rejected, retried within limits, then escalated. Failures are visible on the task and never shown as success; a run with skipped tasks says so ("Completed — 1 task skipped"). If the DB is unavailable, the run stops changing state and resumes from the last checkpoint. Stale concurrent writes are rejected (412), never applied silently.
- **Cancel and pin:** cancelling keeps completed results and records who cancelled. Every run records the Source, Requirement and Agent config versions it started from.
- **Assessment contract:** every Assessment has Findings, Evidence, Assumptions, Unknowns, Risks, a recommendation, a confidence level with basis, a needs-human-review flag, and the Agent, model and prompt versions. Effort is broken down per Integration Type and Work Package. At least 95% of cited Evidence must support its Finding on the reference set.
- **Tool safety:** Agents have explicit read-only tool permissions, checked on every call. Unauthorized calls are blocked and audited. No Agent can write, delete, send or approve. Source, Knowledge and research content is data, never instructions.
- **Roles:** sales representatives and reviewers can read but never start, resolve, retry, skip or cancel runs.
- **Performance:** start acknowledged in under 2 s and status read in under 500 ms (P95). Agent time is measured separately from API time. Concurrency is limited by configuration; excess runs queue. The original "50 concurrent runs" target is revised by the Story 5.10 load test.
- **Observability:** each run has a correlation ID, and every Agent execution, tool call, retry and failure is traceable. Logs and failure records contain IDs and typed reason codes only, never prompts or customer text.

## Technical Decisions

- **Process split:** only the `worker` runs graphs and agents. `api` only enqueues and reads. Only `orchestration/` imports `langgraph`.
- **Ownership:** `workflows` owns runs, plans (versioned), tasks, input pins and progress, and its commands are the only writers of run and task status. `assessments` owns Assessments, Findings, Evidence and effort lines. `gaps` owns Unknowns (`gaps.register_unknown`). `knowledge` owns Research Snapshots. Cross-module calls go only through `application/public.py`.
- **State machines (domain, tested without DB):** run `queued, running, waiting_for_human, completed, failed, cancelled`; task `queued, running, completed, failed, timed_out, skipped`; Finding `open, resolved, overridden`; Unknown shares the Gap lifecycle `open → answered | converted | dismissed_with_reason`.
- **One start path:** `workflows.start_run(opportunity_id, run_type, trigger_ref, idempotency_key)` for `assessment` and `reassessment` (scoped to capabilities). It enqueues the `workflows.execute` job in the same Unit of Work.
- **Checkpointer:** `langgraph-checkpoint-postgres` on its own pool (`search_path=orchestration_checkpoints`, `autocommit=True`, `row_factory=dict_row`, `LANGGRAPH_STRICT_MSGPACK=true`), with `thread_id = workflow_run_id`. Checkpoint state holds only IDs, counters and budgets, and nodes re-read run and task truth from `workflows` on every resume.
- **Node shape:** mark the task running, load inputs through queries, call `Agent.run(task)` outside any open Unit of Work, submit through the owner's `accept_*`, mark the task completed. Each command carries the key `node:<workflow_run_id>:<task_id>:<attempt>`, and a retry increments `attempt`. Side effects before `interrupt()` must be idempotent.
- **Idempotency keys:** `run:<opportunity_id>:<client_key>` for starts, `node:…` for node commands, stored in `platform_idempotency`.
- **Human waits:** `interrupt()` with a typed decision payload plus run status `waiting_for_human`. Resolving is a command that enqueues `workflows.resume`, which calls `Command(resume=…)`. Cancellation is checked between nodes.
- **Jobs:** Postgres `platform_jobs` claimed with `FOR UPDATE SKIP LOCKED`, with lease plus heartbeat, reclaim of expired leases, and priority classes `interactive > background`. Job status is never shown as run status.
- **Agents propose, never write:** each agent is a plain class implementing `Agent.run(TaskInput) -> AgentResult` (`agents/contract.py`, `contract_version`), with its own data under `extensions.<agent_id>`. Prompts are at `agents/<agent_id>/prompts/vN.md`, and Pydantic schemas are the source of truth. Each agent is registered in the DB Agent Registry with immutable config versions (model profile, prompt and schema versions, permissions, budgets, timeout). Agent IDs end in `_agent`, and agents act as `actor_id = "<agent_id>@<semver>"`.
- **Acceptance:** `accept_assessment` validates the base contract, the extension schema, the pinned agent and config version, catalogue references on effort lines, and Evidence. Evidence is `{kind, id, version?, span?}`, with `kind ∈ requirement | source_passage | knowledge_chunk | checklist_item | research_snapshot`, resolved through the owner's `public.py`. `version` is required for versioned targets, and spans are Unicode code-point offsets. A rejection stores nothing and returns typed reasons. New Assessments for the same capability become the next version, and Findings are always referenced with their Assessment version.
- **ModelGateway:** the only path to a model (Ollama `/api/chat` with `format` = JSON Schema). It applies the context size from the model profile, validates with Pydantic and retries, enforces budgets before each call, acquires a slot from the priority GPU semaphore, and writes `platform_model_calls`. Default chat model is `gpt-oss:20b`.
- **ToolGateway:** READ tools only, named by `identity` action names. It checks permissions on each call, scopes results to the task's Opportunity and pinned versions, and counts calls against the budget. Denials append `platform.tool_call.denied`. Untrusted text goes into delimited, escaped data blocks, and the injection heuristic flags `injection_suspected` on Findings. Research fetches are HTTPS GET only, against the allowlist in `ops/research-allowlist.yaml`, with redirects re-checked and size and time limits. Pages are stored through `platform.storage`, parsed in the sandbox, and recorded as immutable Research Snapshots.
- **Trace and stream:** state changes append trace events (`<module>.<entity>.<past_tense_verb>`) through `platform.trace.append` in the same Unit of Work. Progress rows go to non-audit `workflows_progress`, pruned after 30 days. SSE per Opportunity: NOTIFY carries only `{event_id, opportunity_id, source}`, frames are `id/event/data{event_type, subject_type, subject_id, subject_version, occurred_at, summary}`, and clients replay from `Last-Event-ID`.
- **Conventions:** UUIDv7 IDs, effort in person-hours `numeric(10,1)`, problem+json errors with a stable `code`, `row_version` with `If-Match` and 412 on mismatch, `PSA_` settings via `platform.config` (for example `PSA_MAX_ACTIVE_RUNS`), and the web app uses only the generated API client. Tests: agents use a fake ModelGateway, while graphs and commands get Postgres integration tests.

## UX & Interaction Patterns

- **Overview agent run panel:** one list row per task, showing an agent avatar and role, a Task status pill, elapsed time in tabular figures, and a static loader icon while Running (no pulse). It updates over SSE without a refresh.
- **Status pills:** run Queued (neutral), Running (agent colour), Waiting for you (amber), Completed, Failed (red), Cancelled. Task statuses are Done, Failed, Timed out and Skipped.
- **States:** a queued run shows "Position 2 in queue — the model server is busy". A failed task shows a red pill with its specific reason and inline **Retry** and **Skip**, and partial results stay visible, labelled "partial". A waiting run shows an amber **Waiting for you** pill naming the decision, with **Resolve** opening it in the inspector. A budget stop shows the banner "Run stopped: token budget reached. Results so far are kept." with **Rerun selected tasks**, plus **Increase budget** for admins only. **Cancel run** confirms with "Cancel this run? Completed results are kept."
- **Activity tab:** the single 420px right pane has Inspector and Activity tabs (`]` cycles closed, open, closed). Activity is a virtualised list of progress and trace events, newest first, plus run metrics as KPI tiles (tokens, model calls, tool calls, elapsed) with the correlation ID; the token bar turns gap-coloured at its limit.
- **Assessments tab:** one section per Specialist Agent (version, recommendation, confidence), a Findings table card with a severity summary (for example "1 Critical · 3 High · 2 Medium · 0 Low") and columns Severity (icon and label, Critical rows on the blocker tint), Type, Finding (a partial Finding adds "Partial result · blocks submission until resolved"), Raised by (agent role) and Evidence count. Severity values are `low | medium | high | critical`; Finding statuses are Open, Resolved and Overridden, and Challenge, Override and Rerun actions live in the row inspector. A "Low confidence" basis stays visible. An effort table per Integration Type and Work Package. The tab badge counts up live.
- **Accessibility:** a polite `aria-live` region announces status changes, throttled to one announcement per 5 s. Axe must report no violations.
- **Read-only roles:** no Run, Retry, Skip, Resolve or Cancel controls. The UI hides controls, but the API is the enforcement point.

## Cross-Story Dependencies

- 5.1 underpins everything. 5.2 executes 5.1's plans using a test fixture agent. 5.3 provides the real `accept_assessment`, which 5.8 and 5.9 depend on. 5.4's gateway is required by 5.8 and 5.9 (research fetch in 5.9). 5.5 and 5.6 supply the decision, cancel and budget commands that 5.7's UI calls. 5.10 needs the full run from 5.9.
- Depends on earlier epics: Opportunities and membership (Epic 1), parsed Sources, Source Passages, Requirements, the Story 2.7 changed-Requirements notice and the Story 2.8 injection heuristic (Epic 2), Knowledge Chunk retrieval, the catalogue, Checklists and Research Snapshots (Epic 3), the Gap/Unknown state machine from Story 4.2 and the Gaps tab (Epic 4), the Agent Registry and evals harness (Epic 7), and the Story 1.3 alert channel for budget emails.
- Feeds later epics: Critic and Red Team (Epic 6), Estimate and Assumption conversion of Unknowns and Findings (Epic 8), the Inbox listing waiting runs (Story 9.2), and Challenge runs via the same `start_run` path (Epic 9).
