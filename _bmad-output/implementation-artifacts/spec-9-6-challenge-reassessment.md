---
title: 'Story 9.6: Challenge reassessment run creates a new Estimate Version'
type: 'feature'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
baseline_commit: '76a2ac3faa26c23a80a1e575928eef0590ee7881'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-5-raise-challenge.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Once the owner confirms a Challenge (Story 9.5), the `challenge` run reruns the confirmed specialists and the Critic, then stops. The Challenge stays `reassessing` forever. No new Estimate Version, no delta, and nobody hears back.

**Approach:** Give `challenge` runs their own plan: confirmed specialists (with the Challenge in a fenced data block), then Conflict detection, then the Critic, then a final `new_version` node. That node builds the new Estimate Version from the challenged one (changed lines from the reruns, the rest copied), carries Assumptions and Risks forward, completes the Challenge, supersedes the open requests on the old version, traces the delta, and notifies the owner and the challenger.

**Base (amended 2026-10-30):** worktree `D:\Projects\Office\pre-sales-agent-96`, branch `task/story-9-6-challenge-reassessment`, rebased onto `origin/main` (8eba0835b657e1ec6cf01c7d8b06e27c64e66431). Stories 9.5, 9.7 and 9.9 are all merged.

**Diff view (amended 2026-10-30, user decision):** Story 9.9 already shipped the Estimate-tab "Diff vs v{n}" toggle (`diff-toggle.tsx`), `?diff={n}` and `GET …/estimate-versions/compare?from&to`. 9.6 reuses them and builds no diff UI or compare endpoint. The Inbox item links to `/opportunities/{id}/estimate?version={new}&diff={challenged}`, which opens 9.9's diff of the new version against the challenged one.

**Red Team (decision 2026-10-26, option a):** keep it as the job that `store_version` queues on the new version. It is not a plan task. Its critical Findings still gate v4.

**Size (decision 2026-10-26):** keep one spec, accepting about 2,800 tokens.

## Boundaries & Constraints

**Always:**
- **Plan** (`queue_run` with `run_type=challenge`): one task per confirmed agent (`challenge.confirmed`) → `conflict_detection` (after all specialists) → `critic_agent` (after conflicts) → `new_version` (after critic). Unconfirmed agents' current Assessments are reused and not rerun. The plan-version JSON records the pins: each task's `config_version_id`, the active Requirement ids and versions, and the source ids and versions at plan time.
- **Non-agent nodes** go into the executor registry (`orchestration/executors.py`) under the task's `agent` key, with the same `prepare → run → submit` contract. They make no LLM call; `run` is a no-op.
  - `conflict_detection`: `conflicts.detect_for_run` + `conflicts.queue_semantic_detection` for this run.
  - `new_version`: below.
- **Challenge data block:** `SpecialistTask` gains an optional `challenge` (reason, target kind and label, challenged version). `data_blocks` emits it with `prompt_data.fence("CHALLENGE", ...)`, only for tasks in a `challenge` run.
- **`new_version` node** (one Unit of Work, system actor):
  1. Fail the run (`estimate_changed`) if any Estimate Version was created after the run started.
  2. Rebuild lines with `build_lines` from current Assessments. A line counts as changed when a confirmed agent's rerun sizing for its covered Requirements differs from that agent's previous Assessment. Changed lines take the rebuilt hours and basis; all other lines are copied verbatim from the challenged version, edits included.
  3. Write through a new `estimates.public.create_version_from_run(uow, run_id, base_version_id, lines, reason, idempotency_key)` built on `store_version`, with `source='challenge'`, `source_run_id=run_id`, and `idempotency_key=node:<run>:<task>:<attempt>`. A unique partial index on `(source_run_id) WHERE source='challenge'` makes a replay return the existing version. `store_version` already carries the accepted Assumptions and the Risks, supersedes drafts, and queues the Red Team Review on the new version.
  4. Then: `reviews.public.complete_challenge` (→ `completed`, stores `new_version_id`), `reviews.public.supersede_open_requests(old, new)`, trace `reviews.challenge.completed` (challenge id, run id, previous and new version id and number, per-line `{line_id, title, before_h, after_h, delta_h}`, total delta), and Inbox `challenge_completed` to the owner and the challenger (dedupe `challenge:{id}:completed`).
- **Failure:** a cancelled or failed `challenge` run moves the Challenge to `failed` (`reviews.public.fail_challenge`), appends `reviews.challenge.failed`, and sends `challenge_failed` to both people. The old version stays untouched.
- **Inbox copy:** "v4 created from {challenger}'s Challenge (+14.0 h on L1 WMS to SAP EWM interface)". With several changed lines: "(+22.0 h across 3 lines)". Use a `−` sign. Failure copy: "Reassessment for {challenger}'s Challenge failed. v3 is unchanged." Subject type `estimates.estimate_version`; the `inbox.py` href branch opens `/opportunities/{id}/estimate?version={new}&diff={challenged}` (the failure item opens the challenged version without a diff).
- **Run header:** a `challenge` run shows "Challenge reassessment" beside the status pill (from the run's `run_type`). The plan shows Conflict detection and New version as task rows with the existing task-card styling.
- **Diff:** reuse 9.9's toggle, `?diff={n}` and compare endpoint unchanged. The per-line delta in the trace event and Inbox copy comes from the existing `diff_lines`.
- **Blockers:** no new code. Rerun Conflicts and critical Critic and Red Team Findings already reach `get_submission_blockers` for the new draft. Prove it with a test.
- Migration after the current head (0058 on main, so this is 0059): `estimates_versions.source` check + `idempotency_key` column + partial unique index; notification kinds `challenge_completed`, `challenge_failed` (group `challenges`); `reviews_challenges.new_version_id`. Reversible.

**Never:**
- No cost fields; deltas are in hours (no rates exist).
- No Activity-tab build. Don't rebuild 9.7 (version switcher, versions list, Baseline) or 9.9 (diff toggle, compare endpoint, lineage); reuse them.
- No LLM or HTTP call inside an open Unit of Work. Don't change `create_version`'s person-facing rules.
- Don't run Prettier on `web/`. Don't run tests against the dev `psa` DB.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Challenge on v3, Engineering confirmed | plan Eng → conflicts → critic → new_version; v4 draft based on v3, Challenge `completed`, v3 requests `superseded`, 2 Inbox items, trace | N/A |
| Unchanged line | line's sizing unchanged by rerun | copied with its edits | N/A |
| Node replay | `new_version` reruns after a crash | same v4, no second version or event | N/A |
| Estimate changed | v4 created by someone mid-run | no version; run and Challenge `failed`, Inbox | `estimate_changed` |
| Run cancelled | owner cancels | Challenge `failed`, v3 untouched | N/A |
| Rerun raises Conflict | open Conflict after rerun | appears in v4's Blockers to submit | submit → 409 |
| Assessment run | `run_type=assessment` | plan and `finish_run` unchanged | N/A |

</frozen-after-approval>

## Code Map

Refreshed 2026-10-30 against the rebased branch, with 9.5, 9.7 and 9.9 merged. All paths are relative to `backend/app` unless they start with `web/` or `backend/`.

- **Already there (don't rebuild):**
  - Workflows runs have `run_type`, `trigger_ref` and `idempotency_key`; `queue_run` takes `agents`; `start_run` is idempotent (migration 0051).
  - `ChallengeStatus.COMPLETED` and `FAILED` exist, and `REASSESSING → COMPLETED/FAILED` is allowed. Nothing uses them yet.
  - 9.9's `compare_any`, the `?diff={n}` handling and the Total h `DeltaLine` exist.
- **Missing:**
  - `finish_run`, `cancel` and `_fail_open` don't branch on `run_type`.
  - `update_challenge` can't set `new_version_id`.
  - The web run view doesn't expose `run_type`; add it to the run read model and `schema.d.ts`.
  - `VersionSource` has no `challenge`.
  - There is no `idempotency_key` on estimate versions and no `reviews_challenges.new_version_id`.
- **Workflows:**
  - `modules/workflows/application/runs.py:185-243`: `queue_run`. The agents filter is at :204-209 and the Critic append at :210-218.
  - `runs.py:437-516`: `finish_run`. `build_from_assessments` is at :499-504 and `detect_conflicts` at :505. The `specialists_changed` guard is at :450-456.
  - `runs.py:357-411`: `cancel`, which also builds and detects at :403-409.
  - `runs.py:414-434`: `fail_stale`. `runs.py:569-596`: `_fail_open`.
  - `application/assessment_runs.py:293-337`: `start_run`.
  - `domain/runs.py:61-66`: `RunType`. `domain/runs.py:181-197`: readiness.
  - `adapters/models.py:42-75`: runs. `:78-122`: tasks. `:194-217`: plan versions.
  - `adapters/repository.py:35-44`: `RunRecord`.
- **Orchestration:**
  - `orchestration/graph.py:118-191`: `run_task`. `:192-214`: `build_graph`.
  - `orchestration/executors.py:46-51`: protocol. `:72-140`: `SpecialistExecutor`, with `prepare` at :79-101. `:150-189`: `CriticExecutor`. `:191-204`: `EXECUTORS`.
  - `agents/specialist/agent.py:59-66`: `SpecialistTask`. `:67-84`: `data_blocks`.
  - `platform/prompt_data.py:33,58`: `new_token` and `fence`.
- **Critic:** `modules/assessments/application/critic.py:165`: `load_critic_inputs`. It is scoped to the run.
- **Estimates:**
  - `modules/estimates/application/draft.py:276-394`: `StoredVersion` and `store_version`.
  - `application/from_assessments.py:40`: `build_from_assessments`.
  - `domain/from_assessments.py:64,138`: `AgentSizing` and `build_lines`. Lines keep no agent id, so match them by covered Requirement.
  - `application/compare.py:88`: `diff_lines`. `:291-320`: `compare_any`, which should give the delta. Leave `compare_versions` at :135 alone.
  - `domain/estimates.py:106-111`: `VersionSource`. `adapters/models.py:93-96`: the source and `source_has_run` checks, from migration 0022.
  - `adapters/repository.py:271`: `insert_version`. `:331`: `has_version_from`. `:647`: `version_by_number`. `:1245`: `versions_of`.
  - `application/public.py`: exports.
  - `application/blockers.py:207-243`: `blockers_for`, `get_submission_blockers`, `current_blockers`, `submission_blocker_counts`.
  - `application/versions.py:109`: `create_version`. Leave it unchanged.
- **Reviews:**
  - `modules/reviews/application/supersede.py:83`: `supersede_open_requests`.
  - `domain/challenges.py:29-66`: status, transitions and `transition`.
  - `application/challenges.py:458`: `_notify`. `:485-540`: `_confirm`, which starts the `CHALLENGE` run at :496-503 and moves to `REASSESSING` at :505.
  - `adapters/repository.py:521`: `ChallengeRecord`. `:644`: `update_challenge`. `adapters/models.py:150`: `ChallengeRow`.
  - `application/public.py:15-30,82-155`: exports. Add `complete_challenge` and `fail_challenge` with system actors.
- **Notifications:**
  - `modules/notifications/domain/notifications.py:23-37`: kinds. `:44-48`: `InboxGroup.CHALLENGES`. `:59-69`: `KIND_GROUP`.
  - `adapters/models.py:13-16`: `KINDS`.
  - `application/inbox.py:91`: `_subject`. The challenge branch is at :116-133.
  - `application/notify.py:29`: `notify`.
  - Kind-check migration pattern: `backend/migrations/versions/20261026_0051_reviews_challenges.py:31-45,126-138`. The head is `20261028_0058_purge_role.py`, so this migration is 0059.
- **Trace:** `platform/trace/catalogue.py:1636-1678`: the challenge events. Add `ReviewsChallengeCompleted` and `ReviewsChallengeFailed` after them.
- **Web:**
  - Estimate diff (reuse): `web/src/lib/estimates.ts:838,843`: `parseDiffParam` and `withDiffParam`. `estimate-grid.tsx:1546-1600`: `DiffEffects`.
  - `web/src/components/opportunities/specialist-assessments.tsx:1049-1190`: run header (`data-testid="run-header"` :1104).
  - `web/src/lib/assessments.ts:154-166`: run status labels.
  - `web/src/components/inbox/inbox-view.tsx:93-235`: `Row`, `DetailBody` and `Detail` (challenge detail :212-226).
  - `web/src/lib/inbox.ts:40,70,117-140,191-203`: the challenge subject, kinds, `itemBody` and trace events.
  - `web/src/lib/trace.ts:104-106,148`: challenge labels.
  - `web/src/lib/api/schema.d.ts`: regenerate from a fresh local uvicorn on `psa_test96`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/<next>_challenge_versions.py` -- the source check, `idempotency_key`, the partial unique index, notification kinds, `reviews_challenges.new_version_id`. Must be reversible.
- [x] `modules/workflows/application/{runs.py,assessment_runs.py}`, `domain/runs.py` -- the challenge plan with pins, `finish_run`/fail/cancel branches.
- [x] `orchestration/executors.py`, `agents/specialist/agent.py` -- the `conflict_detection` and `new_version` executors, and the CHALLENGE fence.
- [x] `modules/estimates/{application/challenge_version.py,domain/from_assessments.py,public.py,domain/estimates.py,adapters/*}` -- changed-line rebuild and `create_version_from_run`.
- [x] `modules/reviews/{application/challenges.py,public.py}`, `notifications/*`, `platform/trace/catalogue.py` -- complete and fail, the Inbox kinds and copy, and the trace events.
- [x] `backend/tests/test_challenge_runs.py` -- every matrix row (Postgres, fake ModelGateway), the plan order and pins, the fence content, the replay guard, and migration down/up.
- [x] Web -- run-header label, the Inbox item and its href, trace labels, schema regen, and tests.

**Acceptance Criteria:**
- Given a confirmed Challenge on v3, when its run completes, then the owner's and the challenger's Inbox show "v4 created from …'s Challenge (+N h on …)", and opening it lands on `/estimate?version=4&diff=3` with 9.9's v3→v4 line deltas.
- Given a rerun specialist task, when its prompt is built, then the Challenge reason appears only inside a CHALLENGE fence.
- Given the new Inbox items and the run header, when axe runs, then there are no violations.

## Implementation Notes

- **Migration** `20261030_0059_challenge_versions.py` also widens `workflows_tasks` (agent `conflict_detection`/`new_version`, `config_version_id` nullable and null exactly for those nodes, error code `estimate_changed`) and adds `workflows_plan_versions.pins` (JSONB: requirement and source ids/versions, `latest_estimate_version`). `RunErrorCode` and `TaskAgent` gained the matching values (schema regenerated).
- **Plan:** `new_version` runs `after` the Critic and also `requires` every confirmed specialist, so a failed or skipped rerun skips it and the run's end fails the Challenge (the old version stays).
- **Estimate changed:** the `new_version` executor's `accept` marks its own task `failed`/`estimate_changed` (no job retry); `finish_run`'s challenge branch (`_end_challenge`) then calls `fail_challenge` with that code.
- **Changed lines:** a changed line keeps its section, title and covers but takes the rebuilt hours, role mix and basis; its edit on the challenged version is not carried (`store_version(skip_edits=…)`). A line whose Requirements nobody sizes any more is dropped; a newly sized changed Requirement gets its rebuilt line at the end.
- **Inbox dedupe keys** carry the recipient (`challenge:{id}:completed:{recipient}`, `…:failed:{recipient}`), since `dedupe_key` is globally unique. Copy with no changed line: "(no line changed)". The items' link is built in `inbox.py` through `reviews.public.challenge_version_link` (notifications may not import estimates).
- **Retry:** tasks of a `challenge` run are never retried (409), since a retry could not reopen a completed or failed Challenge.
- **Risk:** the node's submit Unit of Work locks its task row before the Opportunity lock; a concurrent cancel takes them in the other order, so a deadlock is possible (Postgres aborts one; the node retries on the next attempt).

## Spec Change Log

- **2026-10-30, frozen block amended by the user:** 9.9 merged with the Estimate diff toggle, `?diff={n}` and the any-two compare endpoint. 9.6 now reuses them: the diff-toggle build, the `/{version_id}/compare` route and their task and AC were removed, and the Inbox href became `?version={new}&diff={challenged}`. The migration moved to 0059. Known-bad state avoided: a second compare endpoint and a duplicate toggle. KEEP: everything else in the intent.

## Review Triage Log

Loop 0 (2026-10-30). BH = Blind Hunter, EC = Edge Case Hunter, VG = Verification Gap.

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | BH, EC | Two base lines covering the same changed Requirement each take its full rebuilt hours | medium | patch | `rebuild_changed` looks each line's sources up in `by_requirement` with no record of use. Lines added or split by hand (8.2) can share a Requirement. |
| 2 | BH, EC | A newer draft that existed at confirm time passes the guard and is superseded by a version built from the older challenged one | medium | patch | `latest_at_start` is the latest number at queue time, so a v4 draft created before confirm on v3 passes. `store_version` then supersedes v4 and its edits are lost. Fail `estimate_changed` unless the challenged version was the latest at start. |
| 3 | EC | `new_version` doesn't wait for `conflict_detection`; a failed detection still produces v4 | medium | patch | `requires=specialists` only (`runs.py`). The rerun Conflicts would then never reach v4's Blockers. |
| 4 | BH, EC | Downgrade leaves plan JSON with non-agent nodes, null `config_version_id` and dangling ids | medium | patch | Pre-0059 `plan_versions_of` calls `UUID(t["config_version_id"])`, which raises on null. |
| 5 | BH, EC | Inbox copy sums line deltas, counts zero-hour lines, and prints "+0.0 h" | low | patch | Direct fix in `completed_summary`: use the total delta and count only lines whose hours changed. |
| 6 | EC | The run-started trace's `agent_count` counts the two non-agent nodes | low | patch | Direct fix: exclude `NON_AGENT_NODES`. |
| 7 | BH | No index on `reviews_challenges.new_version_id`, which the Inbox reads on every outcome item | low | patch | The migration is new; add a partial index. |
| 8 | VG | The edit-drop on rebuilt lines is never exercised | gap | patch | No fixture edits a rebuilt line. |
| 9 | VG | The challenge-run retry 409 test passes without the new check | gap | patch | The only retry hits a cancelled run. |
| 10 | VG, BH | A specialist failing in a challenge run (`new_version` skipped → Challenge failed) is untested | gap | patch | Every fixture executor succeeds. |
| 11 | VG | Merging several rebuilt Requirements into one line is untested | gap | patch | Every test line has one cover. |
| 12 | BH | `schema.d.ts` and `manifest.json` are missing from the diff | false | reject | Excluded from the review diff as generated files; both are changed in the worktree. |
| 13 | BH | Tracking files not advanced | false | reject | The spec is `in-review`; sprint status moves at the end of the build. |
| 14 | BH, EC | `skip_edits` keyed by (section, title) | low | reject | Needs a same-section, same-title line pair. The fix re-keys by line identity, which is more than a direct correction. |
| 15 | BH | `challenge_delta` uses estimates' private helpers | false | reject | Same module (`estimates`), and the architecture test passes. |
| 16 | BH | `estimate_changed` relies on `complete_task` being a no-op on a failed task | low | reject | Works and is tested; restructuring adds surface. |
| 17 | BH | A failed Challenge can't be retried | low | reject | Intended (Implementation Notes); the owner can raise it again. The failure copy is frozen. |
| 18 | BH | `idempotency_key` is never read | false | reject | Required by the frozen intent and kept for the trace (Design Notes). |
| 19 | BH | Placeholder values (`v0`, `""`, bare `assert`) | low | reject | Unreachable for a challenge run. |
| 20 | BH | `run_sizing_pairs` pairs each rerun with `version - 1` | false | reject | The spec defines a change against "that agent's previous Assessment". |
| 21 | EC | Missing pins silently skip the guard | false | reject | `queue_run` always writes plan v1's pins for challenge runs. |
| 22 | EC | Requirement and Source pins are never checked | low | reject | The intent records pins and doesn't ask for a check; assessment runs don't check them either. |
| 23 | EC | Conflict detection runs before v4 exists | maybe-false | defer | The order is frozen. It is medium if a Conflict rule reads Estimate lines; settle it by checking `conflicts.detect_for_run`'s rule inputs. |
| 24 | EC | Non-agent node errors are recorded as `model_unavailable` | low | reject | The node retries first; changing the error mapping adds branches. |

## Design Notes

- **"Estimate changed"** means a version newer than the latest version at run start. `queue_run` records that number in the plan pins, and the node compares against it. That is cheaper and clearer than diffing lines.
- **Why a unique index and not a `platform_idempotency` table:** spec 5.2 ruled the table out. The `node:` key is still stored on the version for the trace. The `(source_run_id)` uniqueness is what actually stops a second version on replay, whatever the attempt number.
- **Copying unchanged lines verbatim** keeps human line edits (8.2) that a full rebuild would lose.

## Verification

`{project-root}` is the worktree `D:\Projects\Office\pre-sales-agent-96`. Work only there and do not commit or push. Test DB `psa_test96`: take both DB URLs from `.env`, with the host swapped to `127.0.0.1` and the db to `psa_test96`.

**Commands:**
- `cd backend && uv run pytest tests/test_challenge_runs.py tests/test_reviews_challenges.py tests/test_workflows*.py tests/test_estimates*.py tests/test_trace_catalogue.py tests/test_architecture.py` -- expected: pass.
- Full backend suite on `psa_test96` -- expected: no new failures.
- `cd web && npm run typecheck && npx eslint src && npm test` -- expected: pass.
