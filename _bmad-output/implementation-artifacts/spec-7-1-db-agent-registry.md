---
title: 'Story 7.1: DB-owned Agent Registry with immutable config versions'
type: 'feature'
created: '2026-10-13'
status: 'done'
baseline_commit: 'f287da8a99d55f06b771660bcb30e0da28b63b64'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-7-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Agent configuration lives in code (`AgentConfig` plus a `config(profile)` function in each agent package, with every agent on semver 0.1.0 and prompt v1). Nothing records which configuration produced an Assessment, and an Agent's behaviour can change with no record.

**Approach:** Add a `registry` module that owns `registry_agents` and insert-only `registry_agent_config_versions`. A migration seeds them from today's code configs. Every agent call site resolves its config through `registry/application/public.py`. A committed manifest of prompt and schema versions guards new config versions. Disabled Agents are kept out of runs, and Assessments reference the config version row that produced them.

## Boundaries & Constraints

**Always:**
- Mutations follow AD-3 (authorize → validate → `If-Match` on `registry_agents` → write → `trace.append`, all in one UoW). Trace events `registry.agent.registered`, `registry.agent_config.version_created`, `registry.agent.enabled` and `registry.agent.disabled` carry `opportunity_id = null`, the actor, and the before and after config version IDs.
- `psa_app` has SELECT and INSERT only on config versions, and no DELETE on agents.
- Admin-only actions are `registry.agent.register`, `registry.agent_config.create` and `registry.agent.set_status`; everyone else gets 403.
- Agent IDs match `^[a-z][a-z0-9_]*_agent$` and are unique.
- A config version records: agent ID, version number (1, 2, …), semver, model profile name, model digest (`unpinned` until 7.2), prompt version, input and output schema versions, `contract_version`, tool permissions (list of action names, seeded `[]`), budgets (JSON, seeded `{}`), created by and created at.
- The `CallerMetadata.config_version` sent to the ModelGateway becomes the config version's ID.

**Decisions:**
1. Config versions pin a profile (seeded `demo-chat`). If `PSA_MODEL_PROFILE_CHAT` is explicitly present in the environment, it overrides that profile at runtime as a local-dev override, and `platform_model_calls.profile` records the profile actually used.
2. A disabled Agent's skipped Assessment task shows "Agent disabled — assess manually" in the run panel and appends `assessments.task.skipped` (ids and reason). No notification is sent.
3. Single-agent steps (extraction, Gap detection, Red Team, Estimate draft and assumptions, Opportunity import) reject with 409 `registry_agent_disabled` ("<Agent> is disabled") when triggered, and an already-queued job fails with that code.
4. `eval_only` behaves as `disabled` in all of these cases.

**Never:**
- No admin web UI (that is 7.3).
- No digest locking or VRAM checks (7.2).
- No ToolGateway or permission enforcement (7.4).
- No evals (7.6).
- No Docker or prod-infra changes beyond the Dockerfile copying the manifest.
- Seed data in the migration is a literal; the migration never imports `app.agents`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Seed | Migration on an existing DB | 8 agents `active`, each with config v1 (0.1.0, prompt 1, schemas 1, contract "1"), with IDs derived deterministically by `uuid5(agent_id)`. Existing Assessments are backfilled to their agent's v1. | N/A |
| New version | Admin posts a config that references deployed items | Row v(n+1) is inserted and becomes current, and a trace event is written. Runs already in progress keep their version. | N/A |
| Not deployed | Prompt, schema or profile is not in the manifest | Nothing stored | 422 `registry_config_not_deployed` |
| Bad contract | The output schema's contract version ≠ `CONTRACT_VERSION` | Nothing stored | 422 `registry_config_incompatible_contract` |
| Bad or duplicate ID | `Foo`, `engineering`, or an existing ID | Nothing stored | 422 / 409 `registry_agent_duplicate` |
| Disable | Admin disables `security_agent` with `If-Match` | Status `disabled`, and a trace event is written | 428 / 412 for a missing or stale header |
| Run with disabled agent | Assessment run queued | Task inserted as `skipped`, reason `agent_disabled`, notice shown | N/A |
| Disabled mid-run | Task still `queued` when its job starts | Task `skipped` with reason `agent_disabled`; running tasks finish | N/A |
| Edit attempt | `psa_app` UPDATE or DELETE on config versions | Permission denied | DB error |

</frozen-after-approval>

## Code Map

- `backend/app/agents/contract.py:107` -- `AgentConfig` (agent_id, semver, prompt_version, profile) and `CONTRACT_VERSION` at :21. Add `config_version_id: UUID` and keep `actor_id`. Delete the per-agent `config(profile)` functions and the `AGENT_ID`/`SEMVER`/`PROMPT_VERSION` constants as runtime sources; agents receive an `AgentConfig`.
- `backend/app/agents/*/agent.py` -- the 8 agents, all on 0.1.0 and v1. `estimating_agent` also loads `v1-assumptions.md` (`ASSUMPTIONS_PROMPT`, :43): prompt version N covers `v<N>.md` and `v<N>-*.md`. Callers pass `config_version=self._config.semver` (for example `specialist/agent.py:130`); switch this to the config version ID.
- Agent construction sites that must resolve through `registry.public.current_config(uow, agent_id)`:
  - `modules/assessments/application/assessment.py` (`_SPECS` :138, `agent_actor` :157, `_task` :782)
  - `review.py:486`
  - `estimates/application/draft.py:526`
  - `assumptions.py:430`
  - `gaps/application/detection.py:465`
  - `intake/application/extraction.py:455,471`
  - `opportunities/application/imports.py:388`
- `backend/app/platform/model_gateway/profiles.py` -- `MODEL_PROFILES` and `get_profile`. Profiles have no digest.
- `backend/app/modules/knowledge/` -- the layout to copy:
  - header plus version rows
  - `application/public.py`
  - `api/routes.py`
  - `If-Match` via `_expected` and `repo.bump`
- `backend/migrations/versions/20261012_0024_knowledge_catalogue.py` -- the grant pattern. The new migration is `20261013_0026_registry.py`, revision `0026_registry`, with down_revision `0025_knowledge_sources`. Add `registry` models to `migrations/env.py`.
- `backend/app/modules/assessments/adapters/models.py` -- changes:
  - Add `config_version_id` (FK, NOT NULL after backfill) to `assessments_assessments`.
  - Add a nullable `skip_reason` to `assessments_tasks`.
  - Write both in `accept_assessment` (`assessment.py:487`), `queue_run` (:173) and the task job start.
- `backend/app/platform/errors.py` -- central error codes, snake_case only.
- `backend/app/modules/identity/actions.py` and `scripts/seed_auth0.py` (`ROLE_PERMISSIONS`) -- admin actions.
- `backend/app/platform/trace/catalogue.py` -- registry payloads.
- `backend/pyproject.toml` -- import-linter contract for `app.modules.registry`.
- `backend/app/main_api.py:126` -- include the router.
- `Dockerfile`, `.github/workflows/ci.yml` -- CI regenerates the manifest and checks it with `git diff --exit-code`, like `gen:api`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/agents/manifest.py` and generated `backend/app/agents/manifest.json` -- A script lists every `prompts/v*.md` (with sha256), every registered (agent, input or output schema version), and every profile. Schema versions come from a registry of `SchemaVersion(agent, kind, version, model, contract_version)`. Hashes use `TypeAdapter(model).json_schema()`. The manifest is loaded at runtime; CI checks it for drift.
- [x] `backend/migrations/versions/20261013_0026_registry.py` -- tables, grants, the literal seed, the assessments columns and the backfill.
- [x] `backend/app/modules/registry/{domain,application,adapters,api}` -- commands `register_agent`, `create_config_version` and `set_status`, plus the queries `current_config`, `get_config_version` and `list_agents`. Admin routes live under `/registry/agents`.
- [x] identity actions, Auth0 seed, error classes, trace payloads, import-linter contract, router registration, `migrations/env.py`.
- [x] agents plus the 7 call sites -- resolve config through registry public; handle disabled agents per decisions 2 and 3; apply the profile override per decision 1.
- [x] assessments -- skipped tasks with a reason, and Assessments referencing their config version.
- [x] `web` -- `npm run gen:api`; show "Agent disabled — assess manually" for skipped tasks in the run panel.
- [x] tests in `backend/tests/test_registry.py` -- the I/O matrix, the migration seed and backfill (with the `_alembic` helper), grants, trace events, manifest drift, and that no runtime path imports the agents' constants.

**Acceptance Criteria:**
- Given the migration has run, when any agent runs, then its config comes from the DB, and its `platform_model_calls.config_version` equals the config version ID.
- Given an Assessment stored after this story, then its Agent ID, semver, model digest and prompt version are resolvable from `config_version_id`.
- Given a non-admin, when they call any registry write, then the response is 403.

## Implementation Notes

- `registry_agents` has a UUID `id` (`uuid5(SEED_NAMESPACE, agent_id)`) because trace `subject_id` is a UUID; `agent_id` is unique text and the FK target of config versions. Seeded v1 ids are `uuid5(SEED_NAMESPACE, "<agent_id>/config/1")`; versions created later use `new_id()`. Current version = highest version number.
- Run pinning: `assessments_tasks` also gets `config_version_id` (FK, NOT NULL, backfilled to v1). `psa_app` may UPDATE `skip_reason` but not the pinned version. A retried task keeps its pinned version; retrying a task of a disabled agent is 409 `registry_agent_disabled`.
- Single-agent jobs resolve the current version when the job starts and fail with `registry_agent_disabled` (no retry) if the agent is not active. `registry_agent_disabled` was added to the `error_code` enums/checks of red team runs, gap detections, estimate drafts, intake extractions and opportunity imports. Assumption proposals have no error code column: they are marked `failed`. API triggers (`start_*`, retry, import upload) return 409; automatic enqueues still queue, and the job fails.
- Profile override: `"model_profile_chat" in settings.model_fields_set` (true when `PSA_MODEL_PROFILE_CHAT` is set in the environment, or a test passes it explicitly).
- Manifest: `python -m app.agents.manifest` (`--check` for drift). Prompt hashes normalise CRLF. Estimating has one input schema (`EstimatingTask | AssumptionsTask`) and one output schema (`EstimatingOutput | AssumptionsOutput`) at v1.
- Registry reads (`GET /registry/agents…`) require the `platform_administrator` role; the three write actions are Auth0 permissions.
- Disabled skips count as non-succeeded in `run_status` (a run with one disabled agent ends `partially_failed`).

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence / route |
|---|---|---|
| Retry test hits the "not failed" guard, never `require_enabled` | medium | Test retries a `skipped` task; 409 comes from `AssessmentTaskNotFailedError`. Patch: test a genuinely failed task, assert `registry_agent_disabled`. |
| Disabled-at-job-start untested for draft, Red Team, extraction, import, proposals | medium | Only Gap detection drains a queued job. Patch: add job-start tests. |
| `has_prompt` accepts estimating prompt N without `v<N>-assumptions.md` | medium | `has_prompt` checks the version key only; `named_prompt` would raise FileNotFoundError. Patch: require each agent's named prompt files. |
| Proposals already stored marked `failed` when agent disabled before a retried job | low | `runs_tasks` check runs before `has_proposed_assumptions`. Patch: reorder. |
| `.env.example` sets `PSA_MODEL_PROFILE_CHAT`, so every copied env overrides the pinned profile | medium | Decision 1 makes the override intentional, but the example turns it on by default. Patch: comment it out in `.env.example`. |
| Override applies from `.env` | false | Decision 1: an explicitly set variable is the local-dev override; the user's `.env` relies on it. |
| Redundant Dockerfile `COPY` of manifest.json | low | `COPY app ./app` already includes it. Patch: delete the line. |
| manifest.py docstring says CI uses `--check` | low | CI runs the generator + `git diff --exit-code`. Patch: fix the docstring. |
| Prompt edited in place keeps its version; hashes never compared | medium | Manifest hashes are recorded but not enforced against pinned versions. Fix needs stored hashes or a base-branch CI comparison. Deferred. |
| Assumption proposals fail with no `registry_agent_disabled` code | medium | No error-code column on proposals (decision 3 says the code is recorded). Needs a migration column. Deferred. |
| Web shows a generic conflict, not "<Agent> is disabled", on the 409 | low | Disabling is only reachable through the admin API until 7.3; fix touches several web actions. Rejected here, noted for 7.3. |
| Disabled skips make runs `partially_failed`/`failed`, and a fresh run reads `running` | low | `run_status` unchanged; each row explains "Agent disabled — assess manually". Fix adds branches to run status. Rejected; raised to the user. |
| Run-started trace `agent_count` counts skipped tasks | low | Cosmetic; counts tasks in the run. Rejected. |
| Single-agent jobs resolve the version at job start and store no config_version_id | low | Spec pins Assessments only; model calls record the version id. Rejected. |
| Disabled single-agent failures are logged, not traced | low | No trace event required by the spec. Rejected. |
| `UnknownAgentError` → 500 / dead job when an agent id is missing | low | Seed and tests cover every id in code. Rejected. |
| Redeploy dropping a pinned prompt crashes jobs | low | Deploy-time concern; would need runtime guards. Rejected. |
| `budgets` values unbounded | low | Admin-only, key count capped, unused until 7.4/7.5. Rejected. |
| Registry reads use a role check, not `authorize` | low | Matches the knowledge module's `_require_role` read pattern. Rejected. |
| All-disabled run still queues | low | Rare; each task shows the notice. Rejected. |
| Downgrade maps `registry_agent_disabled` to `model_unavailable` | low | Commented in the migration; downgrade is lossy by necessity. Rejected. |

## Design Notes

- Error codes follow the repo convention (snake_case, no dots), so they read `registry_config_not_deployed` rather than the epic's dotted form.
- The "same IDs" requirement: the code seed has no IDs and nothing pins a version yet. Deterministic `uuid5` IDs for the seed rows, plus backfilling existing Assessments to v1, give the same guarantee, because every existing Assessment was produced by 0.1.0 with prompt v1.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest` -- all pass. Use a separate test database (`psa_test`) at `127.0.0.1`, never the dev `psa` DB: migration tests drop later tables. `alembic check` needs `PSA_MIGRATIONS_DATABASE_URL` (owner role).
- `cd backend && uv run alembic upgrade head && uv run alembic downgrade 0025_knowledge_sources && uv run alembic upgrade head && uv run alembic check` (against `psa_test`) -- clean
- `cd web && npm run gen:api` against a freshly started local uvicorn (not the Docker `api`), then `npm run lint && npm run typecheck && npm test` -- all pass, no schema drift
