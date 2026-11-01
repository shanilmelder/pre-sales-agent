---
title: 'Admin-managed chat model profiles'
type: 'feature'
created: '2026-11-02'
status: 'in-review'
baseline_commit: '5540a0422da83b0eac6cbb61371b9b3943948cca'
route: 'dispatch'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Adding a chat model today needs a code change to `profiles.py` and a release, so platform admins can't try or adopt a model without one.

**Approach:** Platform admins create chat model profiles in Admin → Model profiles. Each is stored in the database, immutable, retirable, and must pass a live test call before an Agent's config version can pin it.

## Boundaries & Constraints

**Always:**
- Only platform administrators can read or change custom profiles (`registry.model_profile.manage`); every create, test result and retirement is traced.
- The form takes name, provider (fixed list: `ollama`, `openai`), model ID, context size, temperature and reasoning effort. Reasoning effort and temperature are mutually exclusive in the request, as the adapter already does; reasoning effort needs provider `openai`.
- The model ID must be on the approved-model allowlist, which is a database table managed by platform administrators on its own Admin screen (decision: database over env var, accepting that the same admins approve and create). It is seeded with the two built-in models. Adding or removing an entry is traced; removing one does not affect existing profiles.
- The UI warns that the profile sends prompt text off the host, on the form and on each profile.
- Profiles are immutable: no edit, no delete. A change is a new profile plus retiring the old one.
- Test calls send a fixed non-customer prompt, run in the worker, and store only status, error code and latency. The reply text is never stored or traced.
- A retired profile keeps resolving for versions and runs already pinned to it, but can't be newly pinned.

**Never:**
- No base URL, API key or other secret in the form, API or table; those stay in the environment.
- No chat call from the `api` process.
- No `app.platform` import of `app.modules`.
- No change to embedding profiles, and no per-Agent model field.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Create | Valid form | Row in state `untested`, test job enqueued in the same Unit of Work, traced | N/A |
| Model not approved | Model ID off the allowlist | Nothing stored | 422 `registry_model_not_approved` |
| Duplicate name | Same name as a custom or built-in profile | Nothing stored | 409 `registry_model_profile_duplicate` |
| Test passes | Worker call returns valid structured output | State `verified`, selectable in Agent config form | N/A |
| Test fails | Timeout, HTTP error or invalid output | State `failed` with error code; can be retested | Not selectable |
| Pin an unverified profile | Config version names `untested`, `failed` or `retired` | Nothing stored | 422 `registry_config_not_deployed` |
| Retire in use | An Agent's current config pins it | Nothing changes | 409 `registry_model_profile_in_use` |
| Non-admin | Any route | No data | 403 |
| Retired, old run | Older pinned version runs | Call uses the stored profile | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/platform/model_gateway/profiles.py` -- built-ins stay here; `MODEL_PROFILES`, `get_profile`.
- `backend/app/platform/model_gateway/gateway.py:121,160` -- fail-fast check and lookup; holds an engine but can't import registry (`pyproject.toml:80-84`).
- `backend/app/main_worker.py:47,202` -- `_JOB_MODULES`, gateway creation.
- `backend/app/agents/contract.py:129` -- sync `get_profile` check in `AgentConfig`.
- `backend/app/modules/registry/application/registry.py:158,245,266,359,438,489,644` -- `effective_model`, `check_deployed`, `read_config_options`, config creation, `agent_config`.
- `backend/app/modules/assessments/application/critic.py:276`, `conflicts/application/semantic.py:388` -- other `AgentConfig` builders.
- `backend/app/modules/intake/application/extraction.py:648`, `gaps/application/answer_matching.py:101` -- read `num_ctx` for budgets.
- `backend/app/modules/identity/actions.py:71,211`, `backend/scripts/seed_auth0.py:50`, `backend/tests/test_authorize.py:51`, `README.md:253,276` -- a new action goes in all of these.
- `backend/app/platform/trace/catalogue.py:1742` -- trace payloads; no prompts or replies (`tests/test_trace_catalogue.py`).
- `backend/app/platform/jobs/{queue,registry}.py` -- `enqueue`, `JobType`; the job module must also be imported by the api.
- `backend/migrations/versions/20261013_0026_registry.py:20,165` -- limited-update and grant precedents; next revision `0061`.
- `web/src/app/admin/catalogue/*`, `web/src/components/admin/catalogue-*.tsx`, `admin-nav.tsx:5` -- page and component pattern to copy.
- `web/src/components/admin/agent-config-form.tsx:241` -- profile options.
- `web/src/components/knowledge/sources-tab.tsx:106` -- polling pattern for test status.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/*_0061_registry_model_profiles.py`, `registry/adapters/models.py`, `adapters/repository.py` -- add `registry_model_profiles` with `psa_app` SELECT/INSERT and column-limited UPDATE on state, error code and tested-at fields -- immutable definition, mutable test state.
- [x] `platform/model_gateway/{gateway,profiles}.py`, `main_worker.py` -- inject an async profile resolver into the gateway, falling back to built-ins -- keeps the import boundary.
- [x] `agents/contract.py` and budget call sites -- drop the sync check and resolve through registry -- custom names aren't in code.
- [x] `registry/domain`, `application`, `api/routes.py`, `platform/errors.py` -- list, create, retest, retire; allowlist check; `check_deployed` and options include verified custom profiles.
- [x] `identity/actions.py`, `seed_auth0.py`, `README.md`, `trace/catalogue.py`, `web/src/lib/trace.ts` -- new action and `registry.model_profile.{created,tested,retired}` events.
- [x] `registry` job module, `main_worker.py`, api import -- `registry.test_model_profile` job (interactive priority) -- only the worker has provider keys.
- [x] `registry` domain, application, routes, migration `0061` -- `registry_approved_models` table (provider, model; unique), seeded with the built-ins; list, add, remove; `registry.approved_model.{added,removed}` trace events.
- [x] `web/src/app/admin/model-profiles/*`, `web/src/components/admin/model-profile-*.tsx`, `admin-nav.tsx`, regenerated `schema.d.ts` -- list, create form, off-host warning, status polling, retire; a second section managing approved models.
- [x] `backend/tests/test_registry_model_profiles.py`, web tests -- cover the I/O matrix; written but not run until the user says so.

**Acceptance Criteria:**
- Given a verified custom profile pinned on an Agent, when a run executes in the worker, then the call uses its stored model, context size and temperature and `platform_model_calls` records its name.
- Given a custom profile, when any budget reads its context size, then it gets the stored `num_ctx`.
- Given the worker is busy, when a test is queued, then the UI shows it as pending rather than failed.

## Implementation Notes

- The gateway checks built-ins first, then the injected resolver, so a built-in needs no database read and can't be shadowed. `PSA_MODEL_PROFILE_CHAT` still names a built-in only.
- Approved models are a sub-view, `/admin/model-profiles/approved`: its own screen (frozen Boundaries) and part of the same section (Tasks).
- Added beyond the matrix: 409 `registry_model_profile_not_retestable` (only `failed` or `untested` retests: a dead job leaves a profile `untested`, and the UI offers it once polling stops) and 409 `registry_approved_model_duplicate`.
- Added limits: `num_ctx` 16384-2097152 (below that intake's budget is 0), temperature 0-2, reasoning effort `low|medium|high`. A profile setting neither temperature nor effort gets 0.1; a reasoning profile stores a null temperature.
- `latency_ms` is a fourth updatable test column, since the frozen Boundaries say latency is stored.
- A retest is logged, not traced: the spec lists three profile events, and the job traces the result.
- `make eval` copies pinned custom profiles into the eval database, or they would not resolve there.
- The test payload is `ProbeModelProfile`, so pytest doesn't collect it as a test class.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Profile stuck `untested` after final-attempt timeout or lost lease | high | patch | `CancelledError` skips `except Exception`; retest accepts only `failed`. Same endpoint, one state widened. |
| Poll window not restarted by a new pending id; no restart after limit | medium | patch | Effect depends only on `pending`. |
| Stale poll response overwrites newer row | medium | patch | Poll result replaces list after a local upsert. |
| Focus lost after create, Retire, Confirm and Keep | medium | patch | Controls unmount with no focus move, unlike `agents-admin`. |
| Latency includes slot wait | low | patch | `StructuredResult.latency_ms` already excludes it; direct correction. |
| Misleading "deployed manifest" message for a retired profile | low | patch | Direct wording fix. |
| Test gaps: worker wiring, job-level budgets, eval copy, `.definition`, `test_error`, gateway unknown profile, custom model on list and register, double retire, web actions and pages, poll limit, allowlist grant | medium | patch | Verification-gap layer, pre-verified. Tests are written, not run, per the user. |
| Allowlist not enforced on pin or retest | false | reject | Frozen: removing an entry does not affect existing profiles. |
| Retest not traced | low | reject | Frozen list names create, test result and retirement; adding an event is a new surface. |
| Off-host warning absent from Agent config form | low | reject | Frozen: form and each profile; both done. |
| Retiring blocks restoring a version | false | reject | Frozen: a retired profile can't be newly pinned. |
| `verified` can't be refreshed | low | reject | Immutable-by-design; a fix adds a state transition. |
| `num_ctx` is declared, not proven by the probe | medium | defer | Needs a large probe or a UI label; not settled by the spec. |
| Critic and conflict evals and smoke can't resolve custom profiles | medium | defer | Fails loudly with `UnknownModelProfileError`. |
| Pin and retire lock race has no test | medium | defer | Needs a two-connection test. |
| Future built-in name collides with a stored custom name | maybe-false | defer | Would need a release adding that name; unverified medium. |

## Design Notes

Built-ins stay in code so a fresh deployment and `manifest.json` work unchanged; the database only adds to them. `AgentConfig` keeps the name, and resolution moves to the registry and the injected gateway resolver, so lookups stay async and outside Settings validation. `CallerMetadata` needs an agent id for test calls: use a fixed `model_profile_test` value, after checking `platform_model_calls` constraints.

## Working Rules

- Work only inside `D:\Projects\Office\pre-sales-agent-profiles`. Never touch `D:\Projects\Office\pre-sales-agent`.
- Do NOT run pytest, vitest or any other test suite: the user has forbidden it until they say so. Write the tests; run only the Verification commands below.
- Do not write to the dev `psa` database. Do not commit or push.
- `web/node_modules` may be missing: run `npm ci` there first. No Prettier in `web/`: hand-format at about 100 columns. Regenerate `schema.d.ts` with `npm run gen:api -- <file>` from a dumped `app.main_api.app.openapi()`.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app` -- expected: clean.
- `cd backend && uv run lint-imports` -- expected: contracts pass.
- `cd web && npx tsc --noEmit` -- expected: clean.

**Manual checks (if no CLI):**
- Tests run only when the user says so, on a freshly migrated test database.
