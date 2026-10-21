# Epic 7 Context: Agent quality, cost and administration

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give platform administrators control over and visibility into the Agents. The Agent Registry moves from a code seed into the database, with immutable, versioned configurations. Admins manage model profiles, prompts, budgets, status and read-only tool permissions, and can see traces, tokens and cost per run, Agent and Opportunity. An annotated evaluation set, which includes a single-agent baseline comparison, acts as the release gate for any model, prompt or Agent change. This lets every run be reproduced, keeps behaviour from changing without a record, keeps cost within the sponsor's budget, and keeps the multi-agent design only where it is worth its cost. Note: the project has set aside the prod-hardening track for now (reverse proxy, OTel collector export, GPU/prod model choice and runner hardening). Parts of Stories 7.2, 7.5 and 7.8 touch that track, so confirm their scope before building.

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

- **Registry:** Agents have an ID, name, capabilities, schema, model and prompt versions, permissions and a status (`active | disabled | eval_only`). Agent IDs are unique and `snake_case`, ending in `_agent`. Disabled Agents get no new tasks. Their unstarted tasks in active runs become `skipped` ("Agent disabled") and are escalated, while running tasks finish. Every Assessment records the config version that produced it.
- **Run pinning:** each run pins the config versions it uses. A new config version applies only to new runs, and the ToolGateway checks permissions against the pinned version.
- **Tool permissions:** permissions are explicit action names, checked on every call. Agents may hold only `read` actions scoped to the task's Opportunity. `write`, `delete`, `send` and `approve` permissions are rejected at config creation. A denied call returns a typed denial, is audited and is never retried automatically. Prompt injection must never grant an Agent extra actions.
- **Observability and cost:** traces, latency, failures, retries, tokens and cost are reported per run, per Agent (and config version) and per Opportunity, linked by the `workflow_run_id` correlation ID. Agent execution time is reported separately from API time. Each Opportunity's cost is shown against its budget, with an email alert once each at 80% and 100%.
- **Privacy:** views, logs and denial lists hold only IDs, counts and timings, never prompt text, Source text or customer content. Reference-set data is anonymised (for example `[CUSTOMER]`), and originals never enter the repository.
- **Eval bars (release gate):** extraction recall ≥90% and citation validity 100%; Gap recall ≥80%, irrelevant Gaps ≤20% and mandatory-item Gaps 100%; Evidence support ≥95% plus the schema-valid rate. A candidate fails if it misses any bar or regresses any bar by more than 5 points against the last accepted result. Evidence pairs with no annotation are reported as pending, never counted as passes. The reference set holds at least 10 annotated Opportunities.
- **Single-agent decision rule:** "met" when the baseline is within 5 points on Gap detection and on integration-risk Findings, at a cost at least the configured margin lower (default 30%, an assumption). The platform never changes the design automatically, and the admin records the decision with a reason.
- **Access:** registry, admin and eval endpoints are restricted to platform administrators, and other users get 403. The Head of Delivery has read-only access to Cost and usage, which lives under Reports (not Admin).

## Technical Decisions

- **Ownership:** the `registry` module owns `registry_agents`, `registry_agent_config_versions` and `registry_eval_results`. Add any new entity to the Entity ownership table before writing code. Other modules read Agent config only through `registry/application/public.py`. Cross-module reporting uses read-only `reporting_*` views that nothing writes.
- **Immutability:** config version rows are insert-only, and the application DB role has no UPDATE or DELETE on them. Edits and "restore" both insert a new version. Mutable rows such as `registry_agents` carry `row_version`, writes require `If-Match`, and a mismatch returns 412.
- **Deploy manifest:** prompts live at `agents/<agent_id>/prompts/v<N>.md`. Pydantic models are the source of truth for Agent I/O, and JSON Schemas are generated from them. The image carries a manifest of prompt and schema versions with content hashes. A config that references anything outside the manifest is rejected with `registry.config.not_deployed`. An output schema that is incompatible with the `AgentResult` `contract_version` is rejected with `registry.config.incompatible_contract`.
- **Mutation path:** command → `identity.authorize` → validate → write + `platform.trace.append`, all inside one Unit of Work. Registry trace events (`registry.agent.registered`, `registry.agent_config.version_created`, `registry.agent.enabled` / `registry.agent.disabled`, `registry.eval.completed`, `registry.eval.decision_recorded`) use `opportunity_id = null`. Every event type has a payload model in the trace catalogue.
- **Action vocabulary:** names follow `<module>.<entity>.<verb>`, live in `identity/actions.py`, and match Auth0 permission names. Agents act as `actor_id = "<agent_id>@<semver>"`.
- **ModelGateway:** the only path to a model. It takes the model profile from the config version, validates output with Pydantic, enforces run budgets, and writes a `platform_model_calls` row (run, task, agent, config version, model digest, tokens, latency, outcome). Cost and tokens come only from that table. Context size comes only from the profile.
- **Model profiles:** each profile is a repo Modelfile (`ops/models/<profile>.Modelfile`) pinned by digest in `ops/models/digests.lock`. A runtime digest mismatch fails the call with outcome `model_digest_mismatch`. Weights plus KV cache must fit the VRAM budget, and gateway slots must not exceed `OLLAMA_NUM_PARALLEL`. Any new model needs a licence check and an eval pass. Changing the embedding model triggers a background re-embed, and vectors are tagged by model.
- **Cost:** cost is computed deterministically from GPU seconds and tokens, using rates in `platform.config`, and stored as integer minor units with an ISO-4217 currency.
- **Evals:** `make eval` runs the reference set in `evals/` through the ModelGateway at `background` priority, against an isolated evaluation database, with config versions chosen on the command line (default: current). Eval jobs have a timeout and fail with "Eval timed out — GPU busy". A result that passes the gate becomes the accepted comparison point.
- **Errors:** RFC 9457 problem+json with a stable `code`. The web app uses only the client generated from the OpenAPI spec.

## UX & Interaction Patterns

- **Admin layout:** the Admin sidebar entry is visible only to the admin role, with sub-tabs Users and roles, Agents, Catalogue and Evals. Cost is not in Admin.
- **Cost and usage:** a Reports sub-tab, visible to the Head of Delivery (read-only) and platform administrators only. It shows KPIs (runs, tokens, GPU seconds, cost) and a per-Agent table (runs, tokens, GPU seconds, failures), with per-run drill-down. GPU seconds are derived from configured rates.
- **Agents list:** padded list rows (density token) with `j`/`k` selection and Enter to open the right pane's Inspector (one 420px pane with Inspector and Activity tabs). Config history is shown newest first, with author, date and changed fields, and any two versions can be compared in the diff view (diff-tint with `+`/`−` markers).
- **Editing:** edits require a reason. A 412 shows the concurrent-edit message with reload or diff. Disable and enable use a confirm dialog that states the effect. Saving a config with no passing eval shows "Not evaluated" with the missing bars and requires explicit confirmation.
- **Data display:** Cost and usage uses tabular figures and sortable columns. Eval pass and fail pills use an icon plus a label, never colour alone.
- **Accessibility:** WCAG 2.1 AA, with axe in CI.

## Cross-Story Dependencies

- **Story 7.1 is the foundation:** it migrates the Story 2.4 code-seeded registry with the same IDs, so existing run and Assessment pins still resolve. Stories 7.2, 7.3, 7.4, 7.7 and 7.8 build on it.
- **Existing gateways:** Story 7.4 extends the Epic 5 ToolGateway. Story 7.5 relies on `platform_model_calls`, Workflow Run and Task records, and ToolGateway audit records. Alerts use the Story 1.3 email channel.
- **Evals:** Story 7.6 extends the Story 2.5 intake fixtures and exercises intake (Epic 2), Gap detection (Epic 4) and the Specialist, Critic and Red Team Agents (Epic 5). Story 7.7 extends 7.6. Story 7.8 gates on 7.6 and 7.7 and feeds "Not evaluated" into the 7.3 inspector.
- **Planner:** disabled-Agent escalation follows the existing planner rule for unavailable Agents (Epic 5).
