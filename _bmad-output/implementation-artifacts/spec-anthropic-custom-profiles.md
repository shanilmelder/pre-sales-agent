---
title: 'Anthropic as a custom model profile provider'
type: 'feature'
created: '2026-11-02'
status: 'done'
baseline_commit: '21f1b1d2e10d10883c69a179bb61e54f771dde0e'
route: 'dispatch'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Model profiles create form and Approved models list offer only `ollama` and `openai`, so an administrator can't create a Claude profile; Claude is reachable only through the built-in `anthropic-chat`.

**Approach:** Make `anthropic` a custom-profile provider end to end: database constraints, approved-model seed, API and form. A custom Claude profile behaves like `anthropic-chat`: it runs through the existing `AnthropicAdapter`, must pass its live test, and is then pinnable.

## Boundaries & Constraints

**Always:**
- `anthropic` is offered wherever the UI lists providers (create form and Approved models), both reading `PROVIDERS`.
- Claude requests never send `temperature`, so an `anthropic` profile stores `temperature` null and a `reasoning_effort` of `low`, `medium` or `high`. The form shows Reasoning effort (default `medium`, no "None" option) and hides Temperature; the API defaults an omitted effort to `medium`.
- A custom `anthropic` definition sets `refusal_fallback=True`, like `anthropic-chat`. `max_tokens` keeps the default 16000.
- The API key stays in `PSA_ANTHROPIC_API_KEY`, on the worker only.
- The migration seeds approved models `claude-opus-5-5` and `claude-sonnet-5-5` with the existing deterministic ids. Other Claude models go through Approved models and the live test.
- `app.platform.model_gateway` and migrations keep their import rules: the migration never imports the app.

**Never:**
- No model-specific logic: which models accept effort or fallback is settled by the live test, not by code.
- No new efforts (`xhigh`, `max`), no form fields for `max_tokens` or fallback, no adapter changes.
- No edits to migration `0061`. Nothing from the old checkout stash.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Create Claude profile | provider `anthropic`, approved model, effort `high` | 201; stored with null temperature; live test queued | N/A |
| Effort omitted | provider `anthropic`, neither field set | Stored with effort `medium` | N/A |
| Temperature on Claude | provider `anthropic`, temperature set, no effort | Nothing stored | 422 explaining Claude profiles use reasoning effort |
| Unapproved model | provider `anthropic`, unlisted model | Nothing stored | 422 not-approved, as other providers |
| Effort on ollama | provider `ollama`, effort set | Nothing stored | 422, message names `openai` and `anthropic` |
| No key on the worker | Live test runs without `PSA_ANTHROPIC_API_KEY` | Profile `failed` with the adapter's error code | Shown in the list; retest after setting the key |
| Switch provider in form | `openai` + effort `""` → `anthropic` | Effort shows `medium`, Temperature hidden | Back to `ollama` clears effort |

</frozen-after-approval>

## Code Map

- `backend/app/modules/registry/domain/model_profiles.py` -- `CustomProvider` (line 22), `sampling()`, `CustomProfile.definition`.
- `backend/app/modules/registry/application/models.py` -- API schemas; `NewModelProfile` docstring states the provider rule.
- `backend/app/modules/registry/adapters/models.py:102,110,140` -- ORM mirrors of the three constraints; must match the migration.
- `backend/migrations/versions/20261102_0061_registry_model_profiles.py` -- constraint names (`ck_registry_model_profiles_provider`, `ck_registry_model_profiles_reasoning_effort`, `ck_registry_approved_models_provider`) and the seed pattern to copy, including `SEED_NAMESPACE`.
- `backend/app/platform/model_gateway/profiles.py` -- reuse `Provider`; update the module docstring's custom-profile sentence if it reads wrong. `gateway.py` already dispatches on `provider` and the worker's resolver returns `definition`: no change.
- `web/src/lib/model-profiles.ts:10` -- `PROVIDERS`; `samplingLabel` already handles effort.
- `web/src/components/admin/model-profile-create-form.tsx` -- `usesEffort`, `chooseProvider`, submit payload, the effort select at line 226.
- `web/src/lib/api/schema.d.ts` -- generated; regenerate, don't hand-edit.
- `backend/tests/test_registry_model_profiles.py:158,278,283,732` -- `_custom_capable()` and cases asserting the old limit.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/registry/domain/model_profiles.py` -- set `CustomProvider = Provider`, make `sampling()` apply the anthropic rules and update the effort message, set `refusal_fallback` in `definition` -- provider rules live here.
- [x] `backend/app/modules/registry/application/models.py` -- update the `NewModelProfile` docstring -- keeps the OpenAPI text true.
- [x] `backend/migrations/versions/20261102_0062_anthropic_custom_profiles.py` -- widen the three constraints and insert the two seed rows; downgrade deletes `anthropic` rows, then restores the constraints -- custom Claude profiles need storage. Check the two named constraints are dropped by their real names.
- [x] `backend/app/modules/registry/adapters/models.py` -- mirror the widened constraints -- keeps metadata and migrations equal.
- [x] `web/src/lib/model-profiles.ts` -- add `anthropic` to `PROVIDERS` -- offers it in both lists.
- [x] `web/src/components/admin/model-profile-create-form.tsx` -- anthropic shows effort without "None", default `medium`, no Temperature; update the doc comment.
- [x] `web/src/lib/api/schema.d.ts` -- regenerate from a fresh backend.
- [x] `README.md` -- update any statement that custom profiles are `ollama` or `openai` only; note that `anthropic` needs `PSA_ANTHROPIC_API_KEY` on the worker.
- [x] `backend/tests/test_registry_model_profiles.py` and `web/src/components/admin/model-profiles-admin.test.tsx`, `web/src/lib/model-profiles.test.ts` -- replace old-limit cases; cover every I/O row, a migration upgrade/downgrade round trip, and that a custom Claude definition reaches `AnthropicAdapter` with its effort.

**Acceptance Criteria:**
- Given migration `0062` is applied, when an administrator opens the create form, then `anthropic` is listed and its model list holds both seeded Claude models.
- Given a verified custom `anthropic` profile, when an Agent config version pins it, then the worker's run calls the Anthropic adapter with that model and effort.
- Given anthropic profiles exist, when `0062` is downgraded, then they and the anthropic approved models are removed and the old constraints hold.

## Design Notes

Requiring effort avoids a stored `temperature` that is never sent, which `samplingLabel` would show as "Temperature 0.1". The downgrade deletes rows because the old constraints can't hold them; `0061`'s downgrade already accepts that pins then fail as unknown profiles.

## Implementation Notes

- The three constraints' real names differ from the code map: `env.py`'s naming convention doubled the prefix `0061` passed and hashed two (`..._r_1695`, `..._f32e`). `0062` passes `0061`'s literal names, which the convention rewrites to the same real names on drop and create; the round-trip test compares the real names and definitions.
- A temperature with an effort on `anthropic` also returns the Claude message (the matrix covers temperature with no effort only).
- Moving from `openai` with a chosen effort to `anthropic` keeps that effort; only an empty effort becomes `medium`. Leaving `anthropic` clears the effort, so `openai` never keeps one the administrator didn't choose.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Blind + Edge: `chooseProvider` keeps auto-set effort on `anthropic` → `openai` | medium | patch | Only `ollama` cleared it, so Temperature hid and `gpt-4.1-mini` could save with an effort. Fixed and tested. |
| Blind + Edge: `_test_with_real_gateway` depends on leftover queued jobs | medium | patch | It claimed all `TEST_PROFILE` jobs and one test leaves a job queued. Fixed by draining first. |
| DB accepts `anthropic` with temperature and no effort | low | rejected | Only raw SQL reaches it; `sampling()` is the sole write path. An extra constraint is more than a direct fix. |
| `CustomProvider = Provider` drops the DB coupling | low | rejected | Harm needs a future fourth provider; that change would meet the check constraint at once. |
| Fallback-served probe can verify a declined model | low | rejected | Needs a refusal of the trivial probe prompt; fallback fires on refusal only, and comparing models adds a branch. |
| `high` effort may truncate at `max_tokens` 16000 | maybe-false | defer | Real extraction may stop at the limit. Unverified medium; settle with a live large-chunk run on a `high` profile. |
| "Context size" isn't sent for Claude | low | rejected | Same existing meaning for `openai`; no new behaviour. |
| README timeout advice skips the live test; short line | low | patch | `TEST_TIMEOUT_S` is fixed at 90 s. Fixed. |
| Stale `.env.example` and `profiles.py` text | low | patch | Both named `anthropic-chat` as the only Anthropic route. Fixed. |
| AC2 has no single end-to-end test | low | rejected | Pinning and gateway dispatch are each tested; a run test adds setup, and dispatch is on `provider` only. Reported to the user. |
| Test copies `SEED_NAMESPACE` | low | patch | Test now imports the app constant. |
| ORM and migration drift unchecked | false | rejected | CI runs `alembic check` (`.github/workflows/ci.yml:78`). |
| Default effort duplicated in three places | low | rejected | No named caller diverges; the web and API defaults are each tested. |
| No live Claude check before seeding Sonnet | false | rejected | The spec routes this to the live test, which must pass before pinning. |

## Verification

**Commands:**
- `cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app` -- expected: clean.
- `cd backend && uv run pytest tests/test_registry_model_profiles.py tests/test_model_gateway_anthropic.py` against 127.0.0.1 test DB `psa_test_claude_profiles` -- expected: pass. Never `psa`.
- `cd web && npm run lint && npx tsc --noEmit && npx vitest run src/components/admin src/lib/model-profiles.test.ts` -- expected: pass.

**Manual checks (if no CLI):**
- With `PSA_ANTHROPIC_API_KEY` set, a real profile's live test is the first live Claude call; it can't run without the key.
