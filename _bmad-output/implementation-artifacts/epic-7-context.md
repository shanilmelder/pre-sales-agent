# Epic 7 Context: Agent quality, cost and administration

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Make Agent behaviour controlled, measurable and gated. Platform administrators manage Agents as immutable, versioned configurations in the database (model profile pinned by digest, prompt and schema versions, read-only tool permissions, budgets), and they can see every blocked tool call. Admins and the Head of Delivery see cost, tokens, GPU time, failures and traces per run, per Agent and per Opportunity. An evaluation harness scores the Agents against an annotated reference set, compares them with a single-agent baseline, and acts as the CI release gate for any model, prompt, schema or Agent change. Nothing changes silently, every run can be reproduced, and model cost stays inside the sponsor's budget.

## Stories

- Story 7.1: DB-owned Agent Registry with immutable config versions
- Story 7.2: Model profiles pinned by digest and sized to the GPU
- Story 7.3: Admin Agents view with config history
- Story 7.4: Tool permissions administration and denial audit
- Story 7.5: Cost and observability per run, Agent and Opportunity
- Story 7.6: Evaluation harness and reference set
- Story 7.7: Single-agent baseline comparison and decision rule
- Story 7.8: CI eval gate on the self-hosted GPU runner

## Requirements & Constraints

- **Agent registration and versioning:** Agent IDs are unique and `snake_case` ending in `_agent`. A config change always inserts a new version, and existing versions are never edited. Runs pin a config version at start, so new versions affect new runs only. Agent status is `active | disabled | eval_only`. A disabled Agent gets no new tasks. Its unstarted tasks in active runs become `skipped` ("Agent disabled") and are escalated to the presales engineer, and its running tasks finish.
- **Tool permissions:** Agents may hold only `read` actions, scoped to the task's Opportunity. A `write`, `delete`, `send` or `approve` permission is rejected at config creation. Denied calls are blocked, return a typed denial to the Agent, are audited and are never retried automatically. A run with more than N denials (default 3) raises an email alert.
- **Observability and cost:** each run has one correlation ID (`workflow_run_id`), and every Agent execution, tool call, retry and failure can be traced from it. Agent execution time is reported separately from API time. Cost is reported per Opportunity against a configured per-Opportunity budget. An email alert fires once per threshold, at 80% and at 100%.
- **Privacy:** observability views, logs and the denial list contain IDs, counts and timings only. They never hold prompt text, Source text or customer content. Reference-set data is anonymised (for example `[CUSTOMER]`) before commit, and originals never enter the repository.
- **Eval quality bars:** extraction recall at least 90% and citation validity 100%; Gap recall at least 80%, irrelevant Gaps at most 20% and mandatory-item Gaps 100%; Evidence support at least 95%, plus the schema-valid rate. A candidate fails if it misses any bar or regresses any bar by more than 5 points against the last accepted result. Unannotated Evidence pairs count as pending, never as passes.
- **Single-agent decision rule:** the rule is met when the baseline comes within 5 points of the multi-agent design on Gap recall and on integration-risk Finding recall, at a cost at least the configured margin lower (default 30%, an assumption). Recording the decision (adopt or keep) is a human action with a required reason. The platform never changes the design or any config automatically.
- **Access:** registry writes and Admin are for the platform administrator only (others get 403 and the nav item stays hidden). Reports → Cost and usage is for the admin and, read-only, the Head of Delivery. Every other role gets 403.

## Technical Decisions

- **Ownership:** `registry` owns `registry_agents`, `registry_agent_config_versions` and the insert-only `registry_eval_results`. Only `registry` commands write them. Every other module, including the planner, ModelGateway and ToolGateway, reads Agent configuration only through `registry/application/public.py`. The application DB role has no UPDATE or DELETE on config versions.
- **Migration from the code seed (Story 2.4):** copy the seeded Agents and config versions with the same IDs, so pinned versions on existing runs and Assessments still resolve. After the migration, nothing reads the seed at runtime. Each Assessment references the config version row that produced it.
- **Deploy manifest:** the image carries a generated manifest of `agents/<agent_id>/prompts/v<N>.md` files and output schema versions, with content hashes. A config that references something not in the manifest is rejected with `registry.config.not_deployed`. A schema that is incompatible with the `AgentResult` `contract_version` is rejected with `registry.config.incompatible_contract`.
- **Model profiles:** profiles live in `ops/models/<profile>.Modelfile`, which sets `num_ctx`. Each is built at deploy into a named Ollama model, and its digest is pinned in `ops/models/digests.lock`. The context size always comes from the profile. CI requires `num_ctx`, an allowlisted licence and a VRAM estimate. Loaded weights plus KV cache (`num_ctx` × `OLLAMA_NUM_PARALLEL`) must fit the VRAM budget (default 48 GB), and gateway slots never exceed `OLLAMA_NUM_PARALLEL`. The defaults are `gpt-oss:20b` (chat) and `bge-m3` (embeddings), both kept loaded. A digest mismatch at runtime fails the call with outcome `model_digest_mismatch`, records it and sends an alert. A changed embedding profile enqueues a re-embed at `background` priority, and retrieval keeps using the old vectors until the re-embed completes.
- **Gateways:** the ModelGateway is the only path to a model. It writes a `platform_model_calls` row (run, task, agent, config version, digest, tokens, latency, outcome). The ToolGateway checks permissions from the run's pinned config version, not the Agent's current one, and writes `platform.tool_call.denied` trace events.
- **Trace events:** registry changes append `registry.agent.registered`, `registry.agent_config.version_created`, `registry.agent.enabled` and `registry.agent.disabled`, plus `registry.eval.completed` and `registry.eval.decision_recorded`. They go through the single platform trace writer with `opportunity_id = null`, the actor, and the before and after version IDs.
- **Concurrency:** every mutable row has `row_version`. Writes require `If-Match`, and a stale version returns 412. Restoring an old version creates a new copy and leaves the old row unchanged. Errors use problem+json codes.
- **Cost read model:** `reporting_*` views over `platform_model_calls`, workflow and task tables, and ToolGateway audit records. They are read-only, and nothing writes to them. `platform_model_calls` has no GPU-seconds column, so GPU time and cost are derived deterministically from configured rates (for example `PSA_COST_GPU_HOUR_MINOR`, with an ISO-4217 currency) and stored as integer minor units. The cost figures come from deterministic code, never from an LLM.
- **Telemetry:** OpenTelemetry carries `workflow_run_id` from the API request span through the job, graph nodes and gateway calls to the local `otel-collector` (file output, 30-day retention). Logs are structured JSON with IDs only. Nothing is sent to a SaaS tracer.
- **Evals:** the reference set in `evals/reference/` holds 10 or more anonymised Opportunities, extending the Story 2.5 fixtures. `make eval` runs intake, Gap detection, the Specialists, the Critic and the Red Team through the ModelGateway at `background` priority, in an isolated evaluation database, with config versions chosen on the command line (default: current). The `single_agent_baseline_agent` has status `eval_only` and is never planned into real runs.
- **CI gate:** the `eval-gate` job runs on a self-hosted runner labelled `gpu`. It runs as non-root, uses only the eval database and eval-scoped secrets, never touches production secrets or data, and never runs fork PRs. It triggers on `agents/**`, `ops/models/**` (including `digests.lock`) and `evals/**`. It has a timeout that fails with "Eval timed out — GPU busy". A passing result becomes the accepted comparison point when the change is deployed.

## UX & Interaction Patterns

- **Admin sub-tabs:** Users and roles, Agents, Catalogue, Evals. Cost is not in Admin.
- **Admin → Agents:** list rows with agent ID, name, capabilities, a status pill, the current config version, model profile and prompt version. `j`/`k` select a row, and Enter opens the inspector. The inspector holds the config history (newest first, with author, date and changed fields) and a two-version diff with the diff tint and `+`/`−` markers. An edit or a restore requires a reason. The model profile picker offers only locked profiles. The permissions picker shows `read` actions only, and the diff shows permissions granted and removed. Enable and disable use a confirm dialog that states the effect. A config with no passing eval shows "Not evaluated" with the missing bars, and saving it needs explicit confirmation.
- **Admin → Agents → Denied tool calls:** shows time, Agent and version, tool action, and Opportunity and run links. It filters by Agent and date and shows no customer content.
- **Admin → Evals:** shows the latest result per Agent against the bars, with pass or fail pills that pair an icon with a label (never colour alone). It also shows history, a diff to the previous result, and the single-agent decision rule ("Decision rule met / not met" with the figures).
- **Reports → Cost and usage:** shows KPIs (runs, tokens, GPU seconds, cost) and a per-Agent table (runs, tokens, GPU seconds, failures). It also shows cost and tokens per Opportunity for a date range, with each Opportunity's budget, sortable and in tabular figures, and flags Opportunities at 80% or 100% of budget. The run drill-down shows a copyable `workflow_run_id`, the tasks (Agent, version, status, latency, retries, failure reason), model calls and tool calls including denials. Charts are bars with their values as text.
- New UI follows the Epic 17 redesign tokens and primitives (list rows, not fixed 32px rows). axe must report no WCAG 2.1 AA violations.

## Cross-Story Dependencies

- 7.1 is the foundation for 7.2, 7.3, 7.4, 7.7 and 7.8. It replaces the code-seeded registry from Story 2.4, and Assessments from Epic 5 must reference its config versions.
- 7.2 feeds the profile picker in 7.3 and the digest checks in 7.8. Digest-mismatch alerts use the Story 1.3 email channel.
- 7.4 builds on the ToolGateway from Epic 5, and it reuses the action catalogue and authorization from Epic 1 (`identity/actions.py`).
- 7.5 needs `platform_model_calls` and the workflow and task tables (Epics 2 and 5). It needs the Epic 5 per-run budgets and the 7.4 denial records for its tool-call figures.
- 7.6 extends the Story 2.5 intake fixtures. It needs Gap detection (Epic 4), the Specialists (Epic 5) and the Critic and Red Team (Epic 6). The Epic 6 Conflict precision and recall baseline feeds into it. 7.7 extends 7.6, and 7.8 wraps 7.6 and 7.7 in CI.
- 7.3 and 7.8 meet at the "Not evaluated" warning when a config is saved. Every new UI story comes after Story 17.1.
