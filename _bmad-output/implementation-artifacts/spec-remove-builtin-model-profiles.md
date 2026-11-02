---
title: 'Every chat model profile lives in the registry'
type: 'refactor'
created: '2026-11-02'
status: 'done'
baseline_commit: '8ecd66a73785ec0a31f7ef75dfac8c870b4f918c'
route: 'dispatch'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Three chat profiles (`ollama-cloud-chat`, `openai-chat`, `anthropic-chat`) are hard-coded in `MODEL_PROFILES`, so they never appear in Admin > Model profiles, and `PSA_MODEL_PROFILE_CHAT` picks a hidden default. The administrator wants one list: every chat profile in `registry_model_profiles`, none in code.

**Approach:** Migration `0063` seeds the three as `verified` rows (their models are already approved by `0061` and `0062`). Remove `MODEL_PROFILES`, `get_profile`, the manifest's `profiles` key and the `model_profile_chat` setting. Every model call names its profile; the gateway resolves chat profiles only through the registry.

## Boundaries & Constraints

**Always:**
- Seeded rows: `ollama-cloud-chat` (ollama, `gpt-oss:120b-cloud`, num_ctx 32768, temperature 0.1), `openai-chat` (openai, `gpt-4.1-mini`, 32768, temperature 0.1), `anthropic-chat` (anthropic, `claude-opus-5-5`, 32768, effort `medium`). State `verified`, `created_by` null, deterministic ids `uuid5(SEED_NAMESPACE, "model-profile/<name>")`, insert skips a name that already exists. They then behave like any custom profile: listed, retirable when unpinned, immutable.
- Existing pins (all 13 dev config versions pin `ollama-cloud-chat`) keep resolving after upgrade with no data change to config versions.
- `StructuredRequest.profile` becomes a required `str`. Smoke and evals take a required `--profile`.
- Every `ModelGateway` that makes chat calls gets the registry `profile_resolver` (worker, API, smoke, evals). An unknown name raises `UnknownModelProfileError`, as today.
- A config version may pin only a `verified` profile (`_profile_problem`), with no manifest shortcut. Pickers list only verified DB profiles.
- Embedding profiles (`EMBED_PROFILES`, `PSA_MODEL_PROFILE_EMBED`) are untouched.

**Never:**
- No edits to migrations `0060`–`0062`; no change to config-version rows.
- No new UI: the existing list shows the seeded rows.
- No reading `PSA_MODEL_PROFILE_CHAT` anywhere (settings ignore unknown `PSA_` vars, so a leftover value is harmless).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Upgrade dev DB | 13 versions pin `ollama-cloud-chat`, no profile rows | 3 `verified` rows; agents run unchanged | N/A |
| Name already taken | a row `openai-chat` exists before `0063` | that row kept; others inserted | N/A |
| Downgrade `0063` | seeded rows present | seeded ids deleted | pins then fail as unknown, like `0061`'s downgrade |
| Retire seeded profile | `openai-chat`, unpinned | `retired` | pinned one: 409 in-use, as today |
| Create with a seeded name | name `anthropic-chat` | nothing stored | 409 duplicate (DB lookup) |
| Smoke/evals without `--profile` | no argument | argparse usage error, exit 2 | N/A |
| Unknown pinned profile | version pins a name with no row | run fails | `UnknownModelProfileError` |

</frozen-after-approval>

## Code Map

Work only in the git worktree `D:/Projects/Office/pre-sales-agent-anthropic-profiles` (paths below are relative to it); never edit `D:/Projects/Office/pre-sales-agent` or test against its `psa` DB. Create `psa_test_profiles` first if missing. No Prettier in `web/` (hand-format ~100 cols).

- `backend/app/platform/model_gateway/profiles.py` -- delete the three constants, `MODEL_PROFILES`, `get_profile`; keep `ModelProfile`, `Provider`, `ProfileResolver`, `UnknownModelProfileError`, embed parts; rewrite docstring.
- `backend/app/platform/model_gateway/gateway.py:134-139,198,253-260` -- drop startup chat check and default; `_chat_profile` uses resolver only (none → unknown).
- `backend/app/platform/model_gateway/port.py:53-55` -- `profile: str` required (field order may need moving).
- `backend/app/platform/config.py:183-191,337-340` -- remove `model_profile_chat` and its check.
- `backend/app/agents/manifest.py:150-153,182,201` + `manifest.json` -- drop `profiles`, `has_profile`, `profiles()`; regenerate via `python -m app.agents.manifest`.
- `backend/app/modules/registry/application/registry.py:162,230,296,404` -- `effective_model`/`_custom_models` from DB only; `check_deployed` always calls `_profile_problem`; options from `verified_profile_names` only.
- `backend/app/modules/registry/application/model_profiles.py:138,303-307` -- drop built-in name check; `chat_profile` = DB lookup.
- `backend/app/main_api.py:94` -- pass `profile_resolver(engine)`.
- `backend/app/platform/model_gateway/smoke.py`, `backend/app/evals/{__main__,conflicts,critic}.py` -- required `--profile`, resolver.
- `backend/migrations/versions/20261102_0062_anthropic_custom_profiles.py` -- pattern (literal seed, `SEED_NAMESPACE`, no app imports). New `0063` follows it.
- Wording: `registry/domain/model_profiles.py:68`, `agents/contract.py:116`, `platform/errors.py:596`, `registry/api/routes.py:317`, `web/src/lib/model-profiles.ts:30`, `.env.example:69-86`, `README.md:141-205`, `evals/README.md`, `compose.yaml:114-122` comments.
- Tests: `test_model_gateway.py` (`_request` sets no profile; give tests a dict resolver), `test_registry.py`, `test_registry_model_profiles.py:226`, `test_model_gateway_anthropic.py`, `test_agent_contract.py`, `test_evals*.py`, plus single hits listed by `grep -rn "MODEL_PROFILES\|model_profile_chat\|get_profile\b" backend/tests`. Name-only uses of `ollama-cloud-chat` in fixtures stay valid once seeded.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261102_0063_seed_chat_profiles.py` -- seed rows per Always; downgrade deletes the seeded ids.
- [x] `profiles.py`, `gateway.py`, `port.py`, `config.py` -- remove built-ins and the default as mapped.
- [x] `manifest.py`, `manifest.json` -- drop profiles; regenerate.
- [x] `registry.py`, `model_profiles.py` (application) -- DB-only resolution and validation.
- [x] `main_api.py`, `smoke.py`, `evals/*` -- resolver and required `--profile`.
- [x] Docs and wording files listed in Code Map; regenerate `web/src/lib/api/schema.d.ts` from a fresh backend.
- [x] Tests -- update to the above; add: `0063` upgrade/downgrade round trip incl. pre-existing name, seeded rows listed by `read_model_profiles`, pin of seeded profile accepted, unknown name in gateway raises, missing `--profile` exits 2.

**Acceptance Criteria:**
- Given `0063` is applied, when an administrator opens Admin > Model profiles, then all three seeded profiles show as verified.
- Given an Agent pins `ollama-cloud-chat`, when its run calls the gateway, then the worker resolves the DB row and the call succeeds as before.
- Given the code, when searched for `MODEL_PROFILES` or `model_profile_chat`, then nothing remains in `backend/app`.

## Implementation Notes

- `smoke.py` sits in `app.platform` but now imports the registry's resolver: one `ignore_imports` entry in `backend/pyproject.toml` (import-linter), commented as a command-line entry point.
- The evals read the database for the profile only (no call rows), so `make eval-conflicts`/`eval-critic` need a migrated DB at `PSA_DATABASE_URL`.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Blind + Edge: unknown `--profile` in smoke/evals ends in a traceback | low | patch | `UnknownModelProfileError` is a `LookupError`; smoke and the eval loops catch `ModelGatewayError` only. A typo is likely; the fix is one except branch each. |
| Verification gap: eval runners' and smoke's resolver wiring never runs in a test | medium | patch | Eval tests pass `FakeGateway`; smoke test stops at argparse. Dropping `resolve_profile` would pass the suite. |
| Edge: seeded `verified` rows show "No result yet" | low | patch | `testResult` returns null when `latency_ms` is null; every admin sees three such rows. |
| Blind: `check_deployed` docstring garbled; `chosen = profile` alias | low | patch | Direct text/deletion fixes. |
| Blind + Edge: resolver serves retired/failed/untested profiles | false | rejected | By design (0061): every state keeps resolving for what is pinned; only pinning requires `verified`. |
| Blind + Edge: per-call DB lookup / DB blip fails calls | low | rejected | Custom profiles already resolved this way; one indexed read per multi-second model call; the worker needs the DB anyway. |
| Blind: no startup profile check | low | rejected | The user chose to drop the default; a missing pin fails as `UnknownModelProfileError` at run. |
| Blind: pre-existing row redirects pins after `0063` | false | rejected | Before `0063`, `create_model_profile` refused built-in names, so no such row can exist outside raw SQL. |
| Blind: `ON CONFLICT (name)` / defaults unverified | false | rejected | `0061` has plain `uq_registry_model_profiles_name`; `created_at` has a server default; no check ties `verified` to a test. |
| Blind: downgrade blocked by foreign keys | false | rejected | No FK references `registry_model_profiles.id` (grep of app and migrations). |
| Blind + Edge: shared-DB test flakiness (round trip, retire, options) | low | rejected | Suite runs serially (no xdist); round-trip migration tests are an existing pattern. |
| Blind + Edge: "Not in the deployed manifest" for profile problems | low | rejected | Pre-existing since `0061` for custom profiles; rewording changes an asserted API detail. |
| Blind: leftover "custom" names (`_custom_models`, `CustomProfile`) | low | rejected | Rename churn with no named harm. |
| Blind: `NO_PROFILES` gives no guidance | false | rejected | The list shows every state incl. retired, so it is never empty after `0063`. |
| Blind: fixtures shared via a test module | low | rejected | Works; no named breakage. |
| Blind: `create_app` resolver untested | low | rejected | The api process makes no chat calls today; the resolver there is harmless. |
| Blind: README lines over 100 columns | low | rejected | The file already has many longer lines. |
| Edge: retired seeded profile can't be restored | low | rejected | Same as any profile; a new name can be created. |

## Verification

**Commands:**
- `cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app` -- clean.
- `cd backend && uv run python -m app.agents.manifest --check` -- no drift.
- `cd backend && uv run pytest` against `127.0.0.1:5432/psa_test_profiles` with both app and owner URLs -- pass. Never `psa`.
- `cd web && npm run lint && npx tsc --noEmit && npx vitest run` -- pass.
