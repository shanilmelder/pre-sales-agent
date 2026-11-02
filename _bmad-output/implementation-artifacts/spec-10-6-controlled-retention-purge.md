---
title: 'Story 10.6: Controlled retention purge'
type: 'feature'
created: '2026-10-28'
status: 'done'
baseline_commit: 'a9249f7ad958d778c95b1172e9484d03615ab40d'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-10-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-10-5-record-the-opportunity-outcome-and-retention-dates.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 10.5 gives each closed Opportunity a retention date, but nothing deletes its data once that date passes. The app role (rightly) cannot delete most tables, so there is no compliant path to meet deletion duties.

**Approach:** A new `psa_purge` DB role, used only by a daily `platform.purge` worker job, deletes each Opportunity past its retention date in its own transaction. It runs every module's registered purge step in dependency order, decrements file refcounts (blob deleted at zero) and appends one `platform.purge.completed` event. A read-only Admin → Retention tab shows what is due and what was purged. `ops/runbooks/restore.md` documents the backup interplay.

## Boundaries & Constraints

**Always:** Due means `retention_until(...) < today (UTC)`, computed with the domain function (never SQL or browser re-derivation of the rule). One transaction per Opportunity on the purge engine; a failure rolls back only that Opportunity, the rest continue, and the job then raises so it retries with backoff; reruns are idempotent. Steps cover every per-Opportunity row: all module tables, its `platform_trace_events`, `platform_model_calls`, `platform_tool_calls`, `platform_jobs`, `workflows_*` (incl. `workflows_progress`), `notifications_notifications`, and its LangGraph checkpoint threads (`thread_id = str(run_id)`). `platform.purge.completed` is appended in the same transaction with `opportunity_id = null`, subject = the purged UUID, the rule (`lost_3y`/`won_7y`), row counts per module, files deleted. No names or content in the event or logs. Shared data (knowledge sources, catalogue, registry, users, identity) is never touched. The API, other jobs and tests of other modules never get the purge URL. Retention tab is platform-administrator only (new action `platform.retention.read`, also in `seed_auth0.py`); others 403. UI follows the new mockup's Admin pattern (segmented tab, `CardTable` header grid, tint pills, footnote).

**Never:** No on-demand delete button or endpoint. No DELETE grants to `psa_app`. No cross-module FKs or imports outside `application/public.py`; `platform` must not import modules (modules register their steps). No sops/age tooling, no generic dead-job sweep (prod-infra track, skipped).

**Decisions (2026-10-28, planner; prod-infra memory):**
- Credentials: `PSA_PURGE_DATABASE_URL` set only on the `worker` service in `compose.yaml`/`compose.nexus.yaml` and `.env.example`; sops deferred. Unset → the job logs `purge.not_configured` and completes without deleting.
- Role: migration 0058 creates `psa_purge` (LOGIN, password from `PSA_PURGE_DB_PASSWORD` at migration time, else NOLOGIN) and grants SELECT/DELETE on per-Opportunity tables, INSERT on `platform_trace_events`, UPDATE on `platform_files`, DELETE on checkpoint tables (existing + default privileges for role `psa_app` in schema `orchestration_checkpoints`); `ops/postgres/init/` gets the same for fresh volumes.
- Dead-job alert: on its last attempt with failures, the handler enqueues `platform.alert_email` with a new `PurgeFailedAlert` kind (counts and UUIDs only).
- Admin list: Opportunities with retention dates up to today + 30 days, including overdue not yet purged; recent = last 20 purge events.
- Unrefcounted export blobs (gaps question export, actuals error reports) are out of scope → `deferred-work.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Due lost | lost, recorded 1 Jan 2023, today 28 Oct 2026 | all rows gone; event with `lost_3y` and counts | N/A |
| Not yet due | retention = today | untouched | N/A |
| Open / won future | no outcome, or won with future date | untouched | N/A |
| Shared blob | file used by A (due) and B | count −1, blob stays | N/A |
| Sole blob | file used only by A | row and blob deleted | missing blob file ignored |
| One fails | A's step raises, B due | A intact, B purged, job retries | dead after max attempts → alert email |
| Rerun | A purged earlier | A not selected; others purged | N/A |
| Not configured | no purge URL | nothing deleted | logged, job succeeds |
| Non-admin | HoD calls retention API | — | 403 |

</frozen-after-approval>

## Code Map

- DB roles: `ops/postgres/init/10-app-role.sh` (template), `migrations/versions/20261001_0002_platform_trace.py:78-88` default grants, `20261014_0028_workflows.py:173` checkpoint schema; latest `20261027_0057_opportunities_outcome.py` (next `0058_purge_role`). Append-only test `tests/test_trace.py:184` and `tests/test_db_roles.py`.
- Config/engine: `platform/config.py:16` Settings (add `purge_database_url: str | None`), `platform/db.py:30 create_engine`, `platform/uow.py:38 unit_of_work`, `main_worker.py:48-63 _JOB_MODULES`, `:175` engine.
- Jobs: `platform/jobs/registry.py:85` `JobType`, `:55 PermanentJobError`; schedule seed pattern `20261025_0048_notifications.py:170-175` (86,400 s); handler template `modules/reviews/application/reminders.py:31` (system actor `Actor(type="system", id=...)`). Alert: `platform/alerts/jobs.py` (make payload a discriminated union on `kind`).
- Files: `platform/files.py:33 add_reference` (add `release_reference` → returns True at zero); `platform/storage.py:51 path_for`, `:118 _unlink_quietly` (expose a delete). Blob unlink only after commit.
- Per-Opportunity tables (no cascades across modules; children cascade within): intake (`intake_sources`, `_extractions`, `_requirements`; versions hold `file_sha256`), gaps (`gaps_detections`, `_gaps`, `_answer_matches`), estimates (`estimates_baselines` before `_estimate_versions`, `_drafts`), assessments, conflicts (self-ref `previous_conflict_id`), reviews (decisions/replies before requests), actuals (`_actuals`, `_deliveries`, `_imports` with `file_sha256`), knowledge `knowledge_research_snapshots` (`content_sha256`), notifications, workflows (`workflows_runs` cascades), opportunities (`opportunities_opportunities` last; collaborators cascade).
- Trace: `platform/trace/catalogue.py:39-56` `@register`, `trace/writer.py:22 append`; cross-Opportunity listing model `platform/tool_gateway/denials.py:51`.
- Retention: `opportunities/domain/opportunity.py:77 retention_until`; expose due-list query via `opportunities/application/public.py`.
- Identity: `identity/actions.py:22`, `identity/domain/policy.py:207`, `scripts/seed_auth0.py:51`.
- API template: `modules/registry/api/routes.py:75-81`, mounted in `main_api.py:157`.
- Web: `components/admin/admin-nav.tsx:5` (add Retention), page skeleton `app/admin/agents/page.tsx:54-80`, `components/admin/card-table.tsx`, `ui/pill.tsx`, `ui/empty-tab-card.tsx`, `lib/opportunities.ts:75 formatDate`, `lib/sources.ts:61 formatDateTime`, `lib/outcome.ts:23 OUTCOME_LABELS`; tests `app/admin/evals/page.test.tsx`, `components/admin/tool-denials-table.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261028_0058_purge_role.py` + `ops/postgres/init/20-purge-role.sh` -- role, grants, daily `platform.purge` schedule -- privileged path.
- [x] `backend/app/platform/purge/` (`registry.py`, `job.py`) + `config.py`, `files.py`, `storage.py`, `alerts/jobs.py`, `main_worker.py` -- step registry (`register_step(module, order, fn)`; fn(session, opportunity_id) → `StepResult(rows: int, released_sha256: list[str])`), job, refcount release, alert kind.
- [x] `backend/app/modules/*/adapters/purge.py` (each module above) -- delete its rows for one Opportunity -- per-module ownership.
- [x] `platform/trace/catalogue.py` + `web/src/lib/trace.ts` -- `PlatformPurgeCompleted` payload/label.
- [x] `identity` action/policy/seed + `backend/app/platform/purge/api.py` (or registry-style module) -- `GET /api/v1/admin/retention` → `{due: [{opportunity_id, outcome, retention_until}], recent: [{purged_opportunity_id, rule, rows_by_module, files_deleted, occurred_at}]}`.
- [x] `web/src/app/admin/retention/page.tsx`, `components/admin/retention-tables.tsx`, `admin-nav.tsx`, `npm run gen:api` -- two CardTables (Due for purge: UUID mono, outcome pill, retention date; Recent purges: when, UUID, rule, rows, files) with empty states; footnote "Purged automatically each day after the retention date. Nothing can be deleted from here."
- [x] `ops/runbooks/restore.md` -- 35-day backup age-out; run purge after restore before users return.
- [x] Tests: `backend/tests/test_purge.py` (I/O matrix, every table empty for A afterwards via a seeded full Opportunity, B untouched, shared data untouched, event payload has no content, app role still cannot DELETE trace, purge role cannot touch identity/knowledge-source tables), `tests/test_retention_api.py`, web vitest + axe.

**Acceptance Criteria:**
- Given a module adding a new per-Opportunity table, when `test_purge.py` runs, then a schema check fails unless every table with an `opportunity_id` column is covered by a registered step.
- Given Admin → Retention, when an administrator opens it, then no control that deletes exists.

## Implementation Notes

- Registry (`platform/purge/registry.py`): `register_step(module, order, fn, *, tables)` (`tables` names every table the step empties, cascaded children included; the schema check uses it), `register_selector` (opportunities' `retention_due`, domain rule) and `register_run_ids` (workflows). Steps live in `modules/*/adapters/purge.py` and are registered by `modules/*/application/purge.py`, which only the worker imports (`main_worker._PURGE_MODULES`; an import-linter contract keeps them and `platform.purge.job` out of `main_api`). Steps delete children first with literal SQL so row counts are exact. The platform's own rows (trace, model/tool calls by `opportunity_id` or run id, jobs) are deleted by the job itself; checkpoint threads by the workflows step.
- `platform_files` rows stay at `ref_count = 0` (purge has UPDATE, not DELETE); blobs at zero are deleted after commit while their rows are locked (`files.unreferenced ... FOR UPDATE`). `files_deleted` counts references that reached zero (a blob already missing on disk counts too).
- Retention API lives in `opportunities` (`api/retention_routes.py`, `GET /api/v1/admin/retention`), since `registry` may not import other modules and `platform` may not import `identity`. Recent purges read via `platform/purge/history.py` (partial index on `platform.purge.completed`).
- Alert payload: `AlertEmailJob(alert: ToolDenialAlert | PurgeFailedAlert)` discriminated on `kind`, stored flat (old queued rows still load). A run-level failure on the last attempt also alerts ("could not run").
- Migration 0058 leaves the cluster-wide `psa_purge` role on downgrade (revokes its grants in that database).
- Tests run the purge as `psa_purge` via the owner URL with `-c role=psa_purge`; a catalogue-driven seeder writes one row into every purge table (checkpoint tables included).

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence | Route |
|---|--------|---------|---------|----------|-------|
| 1 | blind | schema.d.ts not regenerated | false | Regenerated in the tree (+170 lines); excluded from the review diff only for size | reject |
| 2 | blind | `opportunities_imports` never purged | medium | No `opportunity_id`; linked only by `consumed_at`, pre-existing design (`opportunities/adapters/models.py:88`) | defer |
| 3 | blind+edge | Upload reusing a blob while purge unlinks it | medium | `put_stream` before `add_reference`; row lock guards the count only | defer |
| 4 | blind+edge | No re-check that an Opportunity is still due inside its transaction (reopen / contract change / concurrent run) | high | Selection and purge are separate transactions; no lock on the Opportunity row; a second run appends a zero-count event | patch |
| 5 | blind | Won without contract end never purged | false | Story 10.5 check constraint: won ⇒ `contract_end_date` not null | reject |
| 6 | blind+edge | Timeout (CancelledError) on last attempt → no alert | low | 30-min timeout on a daily purge; fix adds BaseException handling | reject |
| 7 | edge | `_alert` failure masks original error | low | Enqueue failure in same DB just after a failure; unlikely; adds branches | reject |
| 8 | blind | `failed_count == 0` doubles as "could not run" | low | Single caller; no named diverging caller | reject |
| 9 | blind | No test that flat legacy alert payloads load | medium | Only serialization asserted (`test_tool_gateway_unauthorized.py:343`); `_wrap_flat` load unpinned | patch |
| 10 | blind | Page gated on `isAdmin`, not the permission | low | Same as every Admin page; API 403 renders NoAccess | reject |
| 11 | blind | Due list unbounded | low | Admin-only, small closed set | reject |
| 12 | blind+edge | `platform_jobs` with only a run id survive | low | Payloads hold ids only, no content | reject |
| 13 | blind | `files_deleted` counts zero-ref blobs, not unlinks | low | Cosmetic count difference | reject |
| 14 | blind | Migration password in echoed SQL / offline mode | low | Echo off by default; offline mode unused | reject |
| 15 | blind | Runbook omits `PSA_PURGE_DB_PASSWORD` and 35-day source | low | Direct doc fix | patch |
| 16 | vgap | Run-id-only platform rows untested | medium | Seeder sets both ids on every row | patch |
| 17 | vgap | Last-attempt "could not run" alert untested | medium | No test makes `run_purge` raise | patch |
| 18 | vgap+edge | Blob delete failure after commit: OSError untested; non-OSError marks a committed purge failed | medium | `_delete_blobs` outside the try in `purge_opportunity` | patch |
| 19 | vgap | >50 failed ids slice untested | low | Slice present; test-only | reject |
| 20 | edge | Zero-ref blob left after unlink failure never retried | medium | No sweep of `ref_count = 0` | defer |
| 21 | edge | Deleting a queued/running job row of the Opportunity | low | Closed 3+/7+ years; no live jobs expected | reject |
| 22 | edge | Malformed purge event → Retention page 500 | low | Events written only by this job with the same model | reject |

## Verification

**Commands:**
- `cd backend && PSA_DATABASE_URL=… /psa_test106 PSA_MIGRATIONS_DATABASE_URL=… uv run pytest tests/test_purge.py tests/test_retention_api.py tests/test_trace.py tests/test_db_roles.py` -- pass
- `uv run ruff check . && uv run mypy app` -- clean; `alembic check` -- no drift
- `cd web && npm run typecheck && npx eslint src && npx vitest run src/app/admin src/components/admin` -- pass

**Environment (this machine):** work only inside `D:/Projects/Office/pre-sales-agent-106`. Tests use a dedicated DB `psa_test106` (create it on the Docker Postgres as owner `psa` if missing); never the dev `psa` DB. Build both URLs from `.env` with host/db swapped to `127.0.0.1:5432/psa_test106`: `PSA_DATABASE_URL` (psa_app) and `PSA_MIGRATIONS_DATABASE_URL` (owner psa); grep only those values, never `source .env`. Regenerate the web client against a freshly started local uvicorn (or dumped `app.openapi()`), not the Docker api. No Prettier in `web/`: hand-format to ~100 columns.
