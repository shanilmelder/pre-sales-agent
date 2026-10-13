---
title: 'Story 7.6: Evaluation harness and reference set'
type: 'feature'
created: '2026-10-13'
status: 'done'
baseline_commit: '239f5996ab4d4657efc11598d190807a99a4dda3'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-7-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** We have no repeatable way to measure Agent quality. A model, prompt or Agent config change can make extraction, Gap detection or Findings worse, and nobody would know.

**Approach:**
- Commit an anonymised, annotated reference set of 10 Opportunities under `evals/reference/`.
- Add a `make eval` harness that runs the real job chain for each one in an isolated eval database: parse → extraction → Gap detection → Specialists → Estimate → Red Team.
- Score the outputs against the annotations and compare them with the last accepted result.
- Store the result in `registry_eval_results` and show it to admins on Admin → Evals.

## Boundaries & Constraints

**Always:**
- The harness refuses to run unless `PSA_EVAL_DATABASE_URL` and `PSA_EVAL_MIGRATIONS_DATABASE_URL` are set and name a different database from `PSA_DATABASE_URL`. Before each run it resets the eval DB with `alembic downgrade base` and then `upgrade head`.
- Config versions come from the main DB: `--config <agent_id>=<version>` can be repeated, and the default is current. Each chosen version is copied into the eval DB as that agent's newest version, so the job chain picks it up.
- Model calls go through the real `ModelGateway`. Agents already send `background` priority. Assumption-proposal jobs are not run.
- The whole eval has a timeout (`--timeout`, default 3600 s). On timeout it prints "Eval timed out — GPU busy", exits non-zero and stores nothing.
- The result is written to the main DB through the registry application layer, in one Unit of Work, together with `trace.append` of `registry.eval.completed` with `opportunity_id = null`. The payload holds IDs, counts and pass/fail only.
- `registry_eval_results` is insert-only for `psa_app`. Each row holds:
  - the config version IDs, model digests and prompt versions
  - the reference-set version (first 12 characters of the sha256 of the reference Opportunities that ran; see decision 3)
  - scores (JSONB: overall and per Agent), bars (JSONB: metric, threshold, value, status `pass|fail|not_measured`, delta), pending count, tokens, GPU seconds, cost (integer minor units and currency), `passed`, `accepted`, created by and created at.
- A row is `passed` only when every bar passes and no bar drops more than 5 points below the last `accepted` row of the same reference-set version. A passed row is stored with `accepted = true`.
- Bars:
  - FR-5: extraction recall ≥90% and citation validity 100%
  - FR-11: Gap recall ≥80%, irrelevant Gaps ≤20% and mandatory-item Gaps 100%
  - FR-25: Evidence support ≥95%. The schema-valid rate is reported but has no bar.
- Reads are admin-only (`_require_admin`) and every other user gets 403. Admin → Evals is gated on the web side with `isAdmin`.
- Reference sources use placeholders (`[CUSTOMER]`, `[SITE]`, `[PERSON_1]`…) and `.example` email domains, and a test enforces this.

**Never:**
- No Critic stage, because no Critic Agent exists yet. The report lists it as "not available".
- No CI gate or self-hosted runner (that is 7.8), and no single-agent baseline (7.7).
- No writing, updating or deleting eval rows from the web.
- The harness never connects to the main DB for anything except reading config versions and the last accepted row, and inserting the result row.
- No customer originals in the repository.

**Decisions:**
1. **Reference set:** I write all 10 reference Opportunities. Two are the anonymised `demo-data/` scenarios and eight are new fictional ones in different domains. Every `annotations.yaml` carries `annotator: draft` until experts review it, and the report says how many are still drafts.
2. **Evidence support:** this bar is scored only on judged pairs. With no judged pairs it reads `not_measured`, which is a warning and doesn't fail the gate. The report shows the pending count either way.
3. **Compare like with like** (decided in review): the reference-set version is the first 12 characters of the sha256 of the reference Opportunities that actually ran, so an `--only` run has its own version. A result is compared only with the last `accepted` row of the same reference-set version; with none, it is a first eval. Subset runs can be accepted for their own subset.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | `make eval`, every bar met | Report printed and `evals/out/<ts>/report.json` written. Row stored with `passed` and `accepted` both true, and a trace event appended. | N/A |
| Regression | Gap recall 84%, last accepted 91% | Row stored with `passed=false`, and the bar shows delta −7 with status `fail` | exit 1 |
| First eval | No accepted row | Bars are checked only against their thresholds, and the delta is null | N/A |
| Unjudged pairs | Finding→Requirement pairs with no judgement | Written to `evals/out/<ts>/review-pending.yaml` and counted as pending, never as passes | bar `not_measured` (warning) when nothing is judged |
| Same DB | Eval URL names the same database as the main URL | Nothing runs | exit 2, message |
| Unknown config | `--config security_agent=9` doesn't exist | Nothing runs | exit 2, message |
| Stage failure | Extraction job dead for one Opportunity | That Opportunity's later metrics score 0. The report names the failure. | row stored, `passed=false` |
| Non-admin | `GET /registry/evals` | 403 | problem+json |

</frozen-after-approval>

## Code Map

- `backend/app/modules/registry/` -- reuse the layout from 7.1:
  - `adapters/models.py` (add `EvalResultRow`) and `repository.py` (insert, list, latest accepted)
  - `application/registry.py` (`record_eval_result`, plus reads `read_evals` and `read_eval` behind `_require_admin`:135)
  - `public.py`, and `api/routes.py` (new `APIRouter(prefix="/registry/evals")` registered in `app/main_api.py:134`)
- `backend/app/platform/trace/catalogue.py:719-780` -- add `RegistryEvalCompleted` (`@register`).
- `backend/migrations/versions/20261013_0026_registry.py:167` -- the insert-only grant pattern. The new file is `20261013_0027_registry_eval_results.py` (revision `0027_registry_eval_results`, down revision `0026_registry`).
- Job chain and entry points:
  - `intake/application/sources.py:200` `add_file`, which queues the parse job; it ends in Red Team via `draft.py:365`
  - `opportunities/application/opportunities.py:246` `create(uow, Principal, …)`, where `Principal` is at `identity/domain/policy.py:31`
  - to drain jobs, reuse `app/main_worker.py:107` `run(…, job_types=…)` or `platform/jobs/runner.py:93` `run_job`, skipping the assumption-proposal job type
- Tables to score:
  - Requirements: `intake_requirements`, then `intake_requirement_evidence`, then `intake_source_passages` (character offsets). `intake_extractions.dropped_count` counts invalid citations.
  - Gaps: `gaps_gaps` with `gaps_gap_requirements`.
  - Specialist Findings: `assessments_assessment_findings` with `…_finding_requirements`.
  - Red Team Findings: `assessments_findings` (category `integration_harder` = integration risk) with `assessments_finding_requirements`.
  - Model calls: `platform_model_calls` (agent_id, config_version, model_digest, tokens, latency_ms, attempts, outcome `invalid_output`).
- `backend/app/platform/config.py:16` -- add `eval_database_url`, `eval_migrations_database_url`, `cost_per_gpu_second_minor` (default 0), `cost_per_1k_tokens_minor` (default 0) and `cost_currency` (`EUR`).
- `backend/tests/test_intake_parse_job.py:656` `_alembic`, and `tests/test_intake_extraction.py:78` `FakeGateway` / `drain`:242 -- patterns for the harness and its tests.
- `demo-data/` and `demo-data/elmbridge-fc-scenario/` -- 2 fictional scenarios to anonymise into reference Opportunities.
- `web/src/app/admin/catalogue/page.tsx` -- the page pattern: `getMe` → `isAdmin` → server `api.GET`, then a client component. `components/admin/admin-nav.tsx` (add Evals to `SECTIONS`). `components/admin/catalogue-table.tsx:10` `StatusPill` (icon plus label). `bg-diff-tint`, and `signedHours` in `lib/effort-comparison.ts:68` for the real minus sign. `src/test/axe.ts`.

## Tasks & Acceptance

**Execution:**
- [x] `_bmad-output/planning-artifacts/architecture/.../ARCHITECTURE-SPINE.md` -- check that "eval result" sits under `registry` in Entity Ownership (it already does), and note the table name.
- [x] `evals/reference/<slug>/` (×10) -- `sources/*.{txt,eml,vtt}` plus `annotations.yaml`:
  - `requirements`: id, text and the expected quote
  - `gaps`: id, match keywords and `mandatory`
  - `irrelevant_gaps`: match keywords
  - `integration_risks`: id and match keywords
  - `evidence`: judged pairs
  Add an `evals/README.md` that explains the format and the matching rules.
- [x] `backend/migrations/versions/…0027…` and the registry module -- the table, grants, command, reads and routes. Add the trace payload, and update `public.py`.
- [x] `backend/app/evals/` (`__main__.py`, `harness.py`, `scoring.py`, `annotations.py`, `report.py`) plus a root `Makefile` (`eval:` → `cd backend && uv run python -m app.evals run $(ARGS)`). Add an import-linter contract so the harness imports only `application.public` and `platform`.
- [x] `backend/tests/test_evals.py`:
  - pure scoring tests (recall, citation validity, irrelevant, mandatory, pending, regression delta, first eval)
  - the I/O matrix: same-DB refusal, unknown config, timeout, non-admin 403, insert-only grant, trace event
  - a test that the anonymisation check holds over `evals/reference/`
  - a harness smoke test on one Opportunity using `FakeGateway`
- [x] `web` -- `npm run gen:api`, then:
  - `lib/evals.ts` (+ test)
  - `app/admin/evals/page.tsx` (+ test with axe)
  - `components/admin/evals-view.tsx`: the latest result per Agent against its thresholds, with pass/fail/not-measured pills, a history list, and a diff to the previous result (signed deltas, diff-tint)
  - an Evals entry in `admin-nav.tsx`

**Acceptance Criteria:**
- Given 10 annotated reference Opportunities, when `make eval` runs, then each one goes through every stage except Critic in the eval DB, and the report gives each metric overall and per Agent, plus tokens, GPU seconds and cost.
- Given a stored result, when an admin opens Admin → Evals, then the page shows each bar against its threshold with an icon-and-label pill, the history, and the diff to the previous result.
- Given the eval DB is reset, the main DB's data is untouched except for the new result row.

## Implementation Notes

- The harness reuses `app.main_worker.run` (spec Code Map) besides `application.public` and `platform`; the import-linter contract forbids every module's `domain`, `adapters` and `api` plus `app.agents`/`app.orchestration`, and `tests/test_evals.py` checks that `app.modules` imports are `application.public` only.
- The scores are read from the eval DB with plain SQL over the tables in the Code Map; Source text through `intake.extracted_text`.
- `registry_eval_results.created_by` is the actor id (`eval_harness`): `make eval` has no signed-in user.
- A failed stage scores that Opportunity's metrics from that stage on as 0; for irrelevant Gaps (lower is better) 0 means the worst value, 100%.
- PyYAML (MIT) was added to the dev dependency group for `annotations.yaml` / `review-pending.yaml`; `make eval` runs with `uv run`.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence / route |
|---|---|---|
| Same-DB guard compares host strings: `localhost` vs `127.0.0.1` for the same `psa` DB passes, and the reset downgrades the main DB (blind, edge, verification-gap) | high | `_same_database` compares raw `(host, port, database)`; CI uses `localhost`, `.env` practice `127.0.0.1`. Patch: normalise loopback hosts (`localhost`, `127.0.0.1`, `::1`) and test it. |
| `--only` runs become the accepted baseline; deltas compare across different reference sets (blind, edge ×2) | medium | `latest_accepted_eval` ignores the version; the digest covers all of `evals/reference/`. Intent gap, resolved by the human as decision 3 (compare like with like); fixed in place by human choice. Patch: digest the Opportunities that ran; filter the last accepted row by version. |
| Eval Source blobs written to the main `storage_dir` and never cleaned (blind, edge) | medium | `create_opportunities`/`collect` and the worker use `settings.storage_dir`. Patch: the harness runs with a temporary storage dir in `eval_settings`, removed after the run. |
| Keyword matching is substring: `line` hits "timeline", "online" (blind) | medium | `_hits` uses `k.lower() in haystack`; `beverage-pallet-warehouse` I1 has `line`. Patch: word-boundary matching, documented in `evals/README.md`. |
| A failed stage leaves Evidence / integration-risk `None` instead of 0 when the denominator is empty (blind, edge) | medium | `_apply_failures` zeroes only `if ratio.total`, against its docstring and the matrix ("later metrics score 0"). Patch: zero those of the failed stages unconditionally. |
| Smoke test skipped in CI: no eval DB configured (verification-gap, blind) | medium | `ci.yml` sets no `PSA_EVAL_*`; fixture skips. Patch: CI creates `psa_eval` with the `psa_app` grant and exports both URLs. |
| `_failures` never tested against stored rows (verification-gap, blind) | medium | Failure-path tests build `StageFailure` by hand. Patch: DB-backed test seeding a dead job / failed extraction in the eval DB. |
| CLI exit 0/1 untested (verification-gap) | medium | Only exit 2 tested; matrix says regression exits 1. Patch: stub `run_eval`, assert 1 and 0. |
| No negative test for `check_quotes` (verification-gap) | medium | No test asserts `ReferenceSetError`. Patch: tmp folder with a missing quote, unknown source, unknown evidence requirement. |
| Unknown `--only` slug / malformed annotations / alembic failure crash with a traceback and exit 1 (edge) | medium | `__main__` catches only refused/timeout. Patch: `ReferenceSetError` → exit 2 with message; alembic `RuntimeError` → printed error, exit 2. |
| Weak annotation quote (`beverage-pallet-warehouse` R5 "Please make the integration work with") (blind) | low | Quote doesn't carry the Requirement; a correct extraction citing the SAP sentence misses. Patch: quote the substantive sentence. |
| Import test accepts any name from `app.modules.X.application` (blind, edge) | low | The test checks module suffix only. Patch: require the imported name to be `public`. |
| `model_digests` falls back to the config digest when an Agent made no calls (blind) | low | `_store` uses `[v.model_digest]`. Patch: empty list (not called). |
| Reference-set test asserts every annotation is `draft` (blind) | low | Breaks when experts review, the intended workflow. Patch: drop that assertion. |
| `formatCost` assumes 2 minor digits (blind, edge) | low | JPY/BHD scale wrong. Patch: `Intl.NumberFormat` fraction digits for the currency. |
| Duplicate React keys when one Opportunity has two failed parses (edge) | low | `_failures` appends one per failed parse; key is `slug-stage`. Patch: one failure per stage in `_failures`. |
| Duplicate gap / risk ids double-count (edge) | low | `check_quotes` checks Requirement ids only. Patch: also gaps and integration risks. |
| Quote occurring twice matches only the first span (edge) | low | `find_span` uses `re.search`. Patch: match any occurrence. |
| Report directory stamped to the second, a second run in the same second overwrites (edge) | low | Patch: include microseconds. |
| `--config pm_agent=²` passes `isdigit` and crashes `int()` (edge) | low | Patch: `[0-9]+` fullmatch. |
| `dropped_count` read only from the latest extraction (blind) | false | Each extraction supersedes the earlier extracted, unlocked Requirements (`extraction.py:252`), so active Requirements come from the latest one. |
| Annotated quotes may be absent from the parsed text (edge) | false | Parsed all 27 reference Sources with `parse_cli`: every annotated quote is found (0 problems). |
| No extraction precision / unlabelled Gap noise metric (blind) | low | Not an FR-60 bar; irrelevant-Gap labels are the story's mechanism. Rejected: new metric, not a defect. |
| Timeout doesn't kill the alembic subprocess or an in-flight model call (blind, edge) | low | Delays the timeout message by at most one call; reset takes seconds. Rejected: needs async subprocess handling. |
| Concurrent `make eval` runs reset each other's DB (edge) | low | One operator runs evals by hand (7.8 adds the runner). Rejected: needs a lock. |
| Stages that never ran are not reported as failures (edge) | low | After a full drain nothing is queued; an empty chain scores low anyway. Rejected: extra branches. |
| Admin → Evals hides config ids, digests and prompt versions (blind) | low | Not in the AC; available from the API. Rejected. |
| Anonymisation check misses phones, URLs, addresses (blind) | low | Spec defines the check (placeholders, `.example`, demo names); sources are fictional. Rejected. |
| 100th result in the list shows "first result" (edge) | low | Needs 100+ evals. Rejected. |

## Design Notes

- **Matching is deterministic.** An extracted Requirement matches an annotated one when one of its evidence passages overlaps the annotated quote's span in the parsed Source. A Gap matches when any of its keywords appears, case-insensitively, in the Gap's title or why-it-matters.
  - Gap recall is matched annotated Gaps divided by annotated Gaps. Irrelevant is detected Gaps that hit an `irrelevant_gaps` label, divided by all detected Gaps. Mandatory recall uses only the Gaps with `mandatory: true`.
  - Mandatory items are marked in the annotations, because Checklists are not built yet (deferred-work, Stories 4.1/4.2).
- **Citation validity** is valid citations divided by (valid + `dropped_count`). Stored citations are literal by construction, so invalid citations only show up as drops.
- **Per Agent:**
  - Extraction metrics → `intake_agent`.
  - Gap metrics → `clarification_agent`.
  - Evidence support → engineering, pm, security and red_team.
  - Integration-risk recall (over Red Team `integration_harder` plus specialist risks) is reported for 7.7 but has no bar.
- **GPU seconds** is the sum of `latency_ms` (model-call wall time, a proxy until 7.5). Cost is `gpu_s × rate + tokens/1000 × rate`, as integers in minor units.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest` -- all pass. Run against `psa_test` at `127.0.0.1`, never the dev `psa` DB.
- `cd backend && uv run alembic upgrade head && uv run alembic downgrade 0026_registry && uv run alembic upgrade head && uv run alembic check` (on `psa_test`) -- clean.
- `cd web && npm run gen:api` (fresh local uvicorn), then `npm run lint && npm run typecheck && npm test` -- all pass.

**Manual checks:**
- Run `make eval ARGS="--only <slug>"` against a scratch `psa_eval` DB with the demo profile. The report prints, and a row appears on Admin → Evals.
