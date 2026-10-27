---
title: 'Story 9.6: Challenge reassessment run creates a new Estimate Version'
type: 'feature'
created: '2026-10-26'
status: 'ready-for-dev'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-5-raise-challenge.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Once the owner confirms a Challenge (Story 9.5), the `challenge` run reruns the confirmed specialists and the Critic, then stops. The Challenge stays `reassessing` forever. No new Estimate Version, no delta, and nobody hears back.

**Approach:** Give `challenge` runs their own plan: confirmed specialists (with the Challenge in a fenced data block), then Conflict detection, then the Critic, then a final `new_version` node. That node builds the new Estimate Version from the challenged one (changed lines from the reruns, the rest copied), carries Assumptions and Risks forward, completes the Challenge, supersedes the open requests on the old version, traces the delta, and notifies the owner and the challenger.

**Base (decision 2026-10-26):** worktree `D:\Projects\Office\pre-sales-agent-96`, branch `task/story-9-6-challenge-reassessment`, cut from `origin/main` (567c90b). Story 9.5 is not merged yet. Plan now, and **implement only after 9.5 merges** and this branch is rebased onto it. The Code Map cites 9.5 code at its in-progress state in `D:\Projects\Office\pre-sales-agent-95`; re-check those lines after the rebase.

**Diff view (decision 2026-10-26, option a):** build the new mockup's Estimate-tab "Diff vs vN" toggle, and link the Inbox item to `/opportunities/{id}/estimate?version=4&diff=1`.
- Story 9.7 (in progress in `D:\Projects\Office\pre-sales-agent-97`, migration 0051) already builds the version switcher, the `versions` list and the `GET /estimate?version=` read. Its spec leaves the diff to 9.9.
- 9.6 takes the diff from 9.9 and builds it on 9.7's switcher. **Implement after both 9.5 and 9.7 merge.**

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
- **Inbox copy:** "v4 created from {challenger}'s Challenge (+14.0 h on L1 WMS to SAP EWM interface)". With several changed lines: "(+22.0 h across 3 lines)". Use a `−` sign. Failure copy: "Reassessment for {challenger}'s Challenge failed. v3 is unchanged." Subject type `estimates.estimate_version`; the `inbox.py` href branch opens the new version's diff.
- **Run header:** a `challenge` run shows "Challenge reassessment" beside the status pill (from the run's `run_type`). The plan shows Conflict detection and New version as task rows with the existing task-card styling.
- **Diff toggle:** build it on the Estimate tab toolbar exactly as the mockup draws it (`new-mockups/…standalone.html`, Estimate tab; EXPERIENCE.md :110; DESIGN.md :378). It extends 9.7's switcher, `?version=` read and versions list, and doesn't rebuild them.
  - **Toggle:** after "From Assessments (run N)", a toggle button "Diff vs v{N-1}" with `aria-pressed` and primary tint when on, hidden for v1. The `d` key is bound only when single-key shortcuts are on.
  - **Grid with diff on:** the delta sits under each line's Total h: "no change", "+14.0 h" or "−6.0 h". Increases are amber; everything else is secondary text. The totals row shows no delta. Never use red or green. Lines new in this version show "new"; lines removed are not shown.
  - **URL param:** `?diff=1` sits alongside 9.7's `?version=`.
  - **Backend:** add `GET /opportunities/{id}/estimate-versions/{version_id}/compare`, which returns `VersionDiff` against the previous version number. It wraps `compare_versions` and has no `against` param (9.9 adds pairs).
- **Blockers:** no new code. Rerun Conflicts and critical Critic and Red Team Findings already reach `get_submission_blockers` for the new draft. Prove it with a test.
- Migration after 9.5's and 9.7's (main is at 0050, 9.7 takes 0051): `estimates_versions.source` check + `idempotency_key` column + partial unique index; notification kinds `challenge_completed`, `challenge_failed` (group `challenges`); `reviews_challenges.new_version_id`. Reversible.

**Never:**
- No cost fields; deltas are in hours (no rates exist).
- No Activity-tab build. Nothing from 9.7: no version switcher, no versions list, no Baseline. No Trace-tab compare or version-pair picker (9.9).
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

All paths are relative to `backend/app` unless they start with `web/` or `backend/`.

- **Workflows:**
  - `modules/workflows/application/runs.py:184-219`: `queue_run` (9.5 filters `agents` here).
  - `runs.py:415-484`: `finish_run`. Skip `build_from_assessments` and `detect_conflicts` for `challenge` runs, because the nodes do that work.
  - `runs.py:547`: `_fail_open`. `runs.py:378-387`: `cancel`. Hook the Challenge fail into both.
  - `domain/runs.py:173-189`: readiness.
  - `adapters/models.py:70-112,186-209`: tasks and plan versions.
  - 9.5 adds `RunType` and `run_type`/`trigger_ref` on `RunRecord`.
- **Orchestration:**
  - `orchestration/graph.py:130-214`: `run_task` and `build_graph`.
  - `orchestration/executors.py:46-202`: protocol, `SpecialistExecutor` (`prepare` :79-102), `CriticExecutor`, `EXECUTORS`.
  - `agents/specialist/agent.py:59-110`: `SpecialistTask` and `data_blocks`.
  - `platform/prompt_data.py`: `fence` and `new_token`.
- **Critic:** `modules/assessments/application/critic.py:164`. `load_critic_inputs` is scoped to the run, so it already sees only the rerun Assessments.
- **Estimates:**
  - `modules/estimates/application/draft.py:280-392`: `store_version`.
  - `application/from_assessments.py:373`: `build_from_assessments`.
  - `domain/from_assessments.py:361,435`: `AgentSizing` and `build_lines`. Lines keep no agent id, so match them by covered Requirement.
  - `application/compare.py:44,91`: `diff_lines` and `compare_versions`. Reuse these for the delta.
  - `domain/estimates.py:105`: `VersionSource`, plus the `adapters/models.py:93` check.
  - `repository.py:338`: `has_version_from`.
  - `public.py`: export from here.
  - `application/blockers.py:212,226,305`.
- **Reviews:**
  - `modules/reviews/application/supersede.py:83`: `supersede_open_requests`.
  - 9.5 code: `domain/challenges.py:45,66` (transitions), `application/challenges.py:164,479`, `adapters/repository.py:505` (`update_challenge`), `public.py`.
  - Add `complete_challenge` and `fail_challenge` with system actors.
- **Notifications:**
  - `modules/notifications/domain/notifications.py:23-56`: kinds and `KIND_GROUP`.
  - `adapters/models.py:12`: `KINDS`.
  - `application/inbox.py:90`: `_subject` href.
  - `application/notify.py:130`.
  - Kind-check migration pattern: `backend/migrations/versions/20261026_0050_review_outcomes.py:31-47`.
- **Trace:** `platform/trace/catalogue.py`. Add `ReviewsChallengeCompleted` and `ReviewsChallengeFailed` next to 9.5's challenge events.
- **Estimate tab:**
  - 9.7's work is not on main yet. Read the files after the rebase: `estimates/api/routes.py` (versions list, `?version=`), `web/src/components/opportunities/version-switcher.tsx`, `app/opportunities/[id]/estimate.tsx`, `estimate-grid.tsx`.
  - `api/routes.py:564` (`new-version`) is a style reference.
  - `application/compare.py:91` compares only against `version - 1`.
- **Web:**
  - `web/src/app/opportunities/[id]/estimate.tsx` and `data.ts`: read `diff` from `searchParams`.
  - `web/src/components/opportunities/estimate-grid.tsx:466-530`: `EstimateHeader`. Put the toggle here and the delta in the Total h cell.
  - `web/src/lib/estimates.ts:45`: columns. `fromRunLabel` is in the same file.
  - `web/src/components/opportunities/specialist-assessments.tsx:1038-1160`: run header.
  - `web/src/lib/assessments.ts:155-163`.
  - `web/src/components/inbox/inbox-view.tsx:149-207` and `web/src/lib/inbox.ts:41,106-126`.
  - `web/src/components/opportunities/review-panel.tsx:125-156`: `DiffView`.
  - `web/src/lib/reviews.ts:297-309`: `deltaLabel`. Use one decimal and "no change".
  - `web/src/lib/trace.ts`: labels.
  - `web/src/lib/api/schema.d.ts`: regenerate from a fresh local uvicorn.

## Tasks & Acceptance

**Execution:**
- [ ] `backend/migrations/versions/<next>_challenge_versions.py` -- the source check, `idempotency_key`, the partial unique index, notification kinds, `reviews_challenges.new_version_id`. Must be reversible.
- [ ] `modules/workflows/application/{runs.py,assessment_runs.py}`, `domain/runs.py` -- the challenge plan with pins, `finish_run`/fail/cancel branches.
- [ ] `orchestration/executors.py`, `agents/specialist/agent.py` -- the `conflict_detection` and `new_version` executors, and the CHALLENGE fence.
- [ ] `modules/estimates/{application/challenge_version.py,domain/from_assessments.py,public.py,domain/estimates.py,adapters/*}` -- changed-line rebuild and `create_version_from_run`.
- [ ] `modules/reviews/{application/challenges.py,public.py}`, `notifications/*`, `platform/trace/catalogue.py` -- complete and fail, the Inbox kinds and copy, and the trace events.
- [ ] `backend/tests/test_challenge_runs.py` -- every matrix row (Postgres, fake ModelGateway), the plan order and pins, the fence content, the replay guard, and migration down/up.
- [ ] `modules/estimates/{api/routes.py,application/compare.py}` + `backend/tests/test_estimates_compare_route.py` -- the compare route (200 and 403/404 paths).
- [ ] `web/src/{app/opportunities/[id]/estimate.tsx,app/opportunities/data.ts,components/opportunities/estimate-grid.tsx,lib/estimates.ts}` (+ tests) -- the diff toggle and the grid deltas.
- [ ] Web -- run-header label, the Inbox item and its href, trace labels, schema regen, and tests.

**Acceptance Criteria:**
- Given a confirmed Challenge on v3, when its run completes, then the owner's and the challenger's Inbox show "v4 created from …'s Challenge (+N h on …)", and opening it shows the v3→v4 line deltas.
- Given a rerun specialist task, when its prompt is built, then the Challenge reason appears only inside a CHALLENGE fence.
- Given v1 to v4 exist, when the user picks v3 in the switcher and turns on "Diff vs v2", then the URL holds `?version=3&diff=1`, and each line shows "no change", "new", or a signed one-decimal delta under Total h (increases amber).
- Given the new Inbox item, the switcher, the diff toggle and the run header, when axe runs, then there are no violations.

## Implementation Notes

## Spec Change Log

## Review Triage Log

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
