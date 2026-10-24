# Epic 5 Context: Multi-agent assessment with live progress

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Let a presales engineer press **Run assessment** on an Opportunity and have the Research, Engineering, PM and Security Agents assess it, in parallel where possible, while the engineer watches each task live. Runs execute only in the background worker. They survive restarts without losing or duplicating work, stay within budgets and timeouts, can be cancelled, and can pause for a human decision for as long as needed (days, across worker restarts) and then continue exactly where they stopped. Every Agent result is validated against one Assessment contract, so no Finding enters the Opportunity without Evidence or an explicit Unknown or Assumption. This epic turns the Requirements, Knowledge Base and Gaps from Epics 2–4 into evidence-backed Assessments that later Estimates are built from.

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

- **Planning:** plans are built by Agent capability from the Opportunity's Requirements, products and Integration Types. Dependencies are explicit, independent tasks run concurrently, and plans are versioned with every version kept visible. A disabled or missing Agent's tasks are escalated to the presales engineer (the first human decision kind).
- **Durability:** run state persists at each step and resumes after a restart without losing completed work or re-executing completed tasks. A duplicate start returns the existing run.
- **Human pause and resume:** a run can wait indefinitely for a human decision and resume from the interrupted node. Resuming must work after days of waiting and after a worker restart, proven by an integration test that restarts the worker.
- **Concurrent resolution:** if two users resolve the same decision, only the first choice is applied; the second gets 412 with "Already resolved by [user]". Stale run-control writes are always rejected, never applied silently.
- **Cancel:** queued, running or waiting runs can be cancelled; the worker stops between nodes, in-flight task results are not accepted and those tasks become `skipped` ("Run cancelled"), accepted Assessments are kept, and who cancelled is recorded. Cancelling a terminal run returns 409; a cancelled run can never be resumed. Every run records the Source, Requirement and Agent config versions it started from.
- **Bounded execution and failures:** per-task timeouts; per-run limits on model calls, tokens, tool calls and wall-clock time; bounded retries; invalid output rejected then escalated. A failed or timed-out task with nothing else runnable becomes a `task_failed` human decision (Retry / Skip), reusing the same pause/resume path. A run with skipped tasks never shows plain success. A DB outage stops state changes and resumes from the last checkpoint.
- **Assessment contract:** Findings, Evidence, Assumptions, Unknowns, Risks, recommendation, confidence with basis, needs-human-review flag, and Agent/model/prompt versions; effort per Integration Type and Work Package.
- **Tool safety:** Agents have explicit read-only tool permissions checked on every call; no Agent can write, delete, send or approve. Source, Knowledge and research content is data, never instructions.
- **Roles:** only users holding the relevant action may start, resolve/resume, retry, skip or cancel; sales representatives and reviewers are read-only. Missing permission is 403 and the controls are hidden.
- **Performance and observability:** start acknowledged < 2 s, status read < 500 ms (P95); concurrency limited by configuration with excess runs queued. Every run has a correlation ID; logs and failure records carry IDs and typed reason codes only, never prompts or customer text.

## Technical Decisions

- **Process split:** only the `worker` runs graphs and agents; `api` only enqueues and reads. Only `orchestration/` imports `langgraph`.
- **`workflows` owns run truth; graph state is a cache:** `workflows` owns runs, versioned plans, tasks, input pins and open decisions, and its commands are the only writers of run and task status. Checkpoint state holds only IDs, counters and budgets; nodes re-read run/task truth from `workflows` on every resume. `platform_jobs.status` is never shown as run status.
- **Checkpointer:** `langgraph-checkpoint-postgres` (3.1.x) on its own pool with `search_path=orchestration_checkpoints`, `autocommit=True`, `row_factory=dict_row`, `LANGGRAPH_STRICT_MSGPACK=true`; `thread_id = workflow_run_id`. This is what makes resume-after-restart work.
- **Interrupt/resume model:** a node needing a human calls `interrupt()` with a typed decision payload (decision kind, task, allowed choices) and `workflows` sets the run to `waiting_for_human`, records the open decision and appends `workflows.run.waiting_for_human`. A node reruns from its start on resume, so every side effect before `interrupt()` must be idempotent (tested: resume finds no duplicate rows). Resolving is a command (`workflows.resolve_decision`) that records the choice and enqueues a `workflows.resume` job in the same Unit of Work; the worker's resume handler calls `Command(resume=…)` on the same thread. Plan-escalation choices are **Continue without** and **Re-plan** (Re-plan creates plan v2 if the agent was re-enabled).
- **Cancellation:** `workflows.cancel_run` sets `cancelled`; the worker checks between nodes and stops; trace event `workflows.run.cancelled` records the actor.
- **Optimistic concurrency:** mutable rows carry `row_version`; the API requires `If-Match` and returns 412 on mismatch. Run-control commands (resolve, cancel) use it.
- **Jobs and idempotency:** Postgres `platform_jobs`, each type registered with typed payload, priority class (`interactive > background`), timeout and retry policy; claimed `FOR UPDATE SKIP LOCKED` with lease + heartbeat and reclaim of expired leases; exhausted jobs become `dead` and alert. Idempotency keys in `platform_idempotency`: `run:<opportunity_id>:<client_key>` for starts, `node:<workflow_run_id>:<task_id>:<attempt>` for node commands (retry increments `attempt`).
- **State machines (domain, tested without DB):** run `queued, running, waiting_for_human, completed, failed, cancelled`; task `queued, running, completed, failed, timed_out, skipped`; Finding `open, resolved, overridden`.
- **Authorization:** Auth0 RBAC is the single source of roles and permissions; each permission name equals an action name (`<module>.<entity>.<verb>`, catalogued in `identity/actions.py`), read from the token's `permissions` claim. Every command calls `identity.authorize(actor, action, resource)`; Opportunity membership (owner, collaborators) stays in the platform. Relevant actions include `workflows.run.resume` and `workflows.run.cancel`. The UI is never the enforcement point. Agents act as `actor_id = "<agent_id>@<semver>"`.
- **Node shape:** mark task running, load inputs through queries, call `Agent.run(task)` outside any open Unit of Work, submit via the owner's `accept_*`, mark task completed, each command carrying its `node:` key.
- **Agents, gateways, acceptance:** agents implement `Agent.run(TaskInput) -> AgentResult`, registered with immutable config versions. ModelGateway is the only path to a model (Ollama, JSON-Schema `format`, budgets enforced before each call). ToolGateway exposes READ tools only, checks permissions per call and audits denials. `accept_assessment` validates the contract and resolves Evidence through owners' `public.py`; rejections store nothing.
- **Trace and stream:** state changes append `<module>.<entity>.<past_tense_verb>` trace events via `platform.trace.append` in the same Unit of Work; progress rows go to `workflows_progress`; SSE per Opportunity with `Last-Event-ID` replay.
- **Conventions:** UUIDv7 IDs, problem+json errors with a stable `code`, `PSA_` settings via `platform.config`, web uses only the generated API client. Graphs and commands get Postgres integration tests; agents use a fake ModelGateway.

## UX & Interaction Patterns

- **Waiting for you:** a waiting run shows an amber (gap colour, clock icon) **Waiting for you** pill naming the decision, e.g. "Security assessment not planned: Security Agent is disabled", with a **Resolve** link that opens the decision in the Inspector. The same decision appears in the Activity tab for the engineer who started the run and the Opportunity owner, and in the Overview **Needs you** card. Inbox listing of waiting runs comes later (Story 9.2), derived from run state.
- **Concurrent resolve:** the second resolver sees the 412 message ("Already resolved by [user]") with reload; nothing is overwritten.
- **Cancel:** **Cancel run** confirms with "Cancel this run? Completed results are kept." Cancelled pill is neutral with a ban icon.
- **Agent run panel:** one row per task with agent avatar, role, status pill, elapsed time, static loader icon while Running; updates over SSE. Failed tasks show reason plus **Retry** and **Skip**, partial results labelled "partial". A queued run shows its queue position. Budget stop shows a banner with **Rerun selected tasks** (and **Increase budget** for admins only).
- **Activity tab:** right-pane Inspector/Activity tabs (`]` cycles), virtualised newest-first events plus run metrics tiles and correlation ID.
- **Accessibility:** a polite `aria-live` region announces status changes, throttled to one per 5 s; no axe violations.
- **Read-only roles:** no Run, Retry, Skip, Resolve or Cancel controls.

## Cross-Story Dependencies

- 5.1 (start path, versioned plans, plan escalation for disabled agents) and 5.2 (worker execution, checkpointer, `workflows.execute`) are prerequisites for 5.5. 5.5 supplies the interrupt/resolve/resume and cancel commands that 5.6 reuses for the `task_failed` decision and that 5.7's UI calls. 5.3 provides `accept_assessment` for 5.8/5.9; 5.4's gateway is needed by 5.8/5.9; 5.10 needs the full run from 5.9.
- Depends on Opportunities, membership and Auth0 RBAC (Epic 1), Requirements and the changed-Requirements notice (Epic 2), Knowledge and catalogue (Epic 3), the Gap/Unknown state machine (Epic 4), and the Agent Registry (Epic 7).
- Feeds Critic and Red Team (Epic 6), Estimates (Epic 8), the Inbox listing waiting runs (Story 9.2), and Challenge runs via the same `start_run` path (Epic 9).
