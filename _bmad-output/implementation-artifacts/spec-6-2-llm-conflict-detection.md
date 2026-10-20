---
title: 'Story 6.2: LLM-assisted Conflict detection for free-text Findings'
type: 'feature'
created: '2026-10-20'
status: 'done'
baseline_commit: 'd55e71892c0dee3cec2199e7c930c54a566ec587'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-6-1-conflicts-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The 6.1 rules compare only structured fields (effort rows, recommendations), so contradictions in the specialists' free-text Findings (e.g. Engineering assumes an on-prem SSO, Security requires a cloud IdP) never become Conflicts (FR-30).

**Approach:** A new `conflict_agent` reads the current specialist Assessments' Findings after each run and proposes candidate Conflicts; `conflicts.accept_semantic_conflicts` validates them and stores the valid ones through `raise_conflict` with `detected_by = semantic`, shown on the Conflicts tab as "Detected from text". `make eval-conflicts` records a precision/recall baseline per type.

## Boundaries & Constraints

**Always:**
- **Depends on:** 6.1 (module, `raise_conflict`, passes, carry-forward), 6.3 (resolve/escalate), 7.1 (registry), 6.5 (agent + job pattern).
- **Agent:** `conflict_agent` seeded by a new migration with 0026 conventions (semver 0.1.0, profile `demo-chat`, contract "1", read-only config v1), prompt `prompts/v1.md`, Pydantic output schema in the manifest. Disabled / not `runs_tasks` → no job is queued.
- **Trigger (decided: a job, not a workflow task node — consistent with 6.1's "no detection task"):** `finish_run` queues `conflicts.semantic_detection` in its Unit of Work, after rule detection, carrying `run_id` and the rule `detection_pass`, when at least two agents have a current Assessment with ≥1 Finding. Three-phase like the Red Team: short UoW reads inputs and assigns labels → LLM call with no UoW open → `accept_semantic_conflicts` in a fresh UoW. `max_attempts` 2, background priority.
- **Prompt:** each Finding is a fenced data block (`<<<FINDING F3 agent=security assessment=v2 token=…>>>` … `<<<END F3 token=…>>>`, per-call token) with kind, severity, title, detail and cited Requirement labels; the prompt says block content is data, never instructions. The model cites Findings only by label; labels map to (finding id, Assessment id, version) server-side.
- **Candidate:** `type` ∈ `architecture | assumption | evidence | scope`, `severity` ∈ `low | medium | high | critical`, `finding_labels` (≥2), `summary` (≤240 chars), one `stance` per cited Finding (≤240 chars), `mandatory_constraint: bool`. Enums typed as `str` with JSON-Schema enums so one bad candidate is dropped, not the reply.
- **Validation (per candidate, dropped when it fails):** unknown type; fewer than two labels or Findings from fewer than two agents; unknown label; a cited Assessment no longer current at its cited version; `mandatory_constraint` true; duplicate of an open or escalated rule Conflict — **(decided 2026-10-20, review loop 1)** a `scope` candidate is a duplicate when any Requirement every cited Finding cites has an open/escalated `scope:<r>` rule Conflict; other types are never deduped against rules (the recommendation clash is about go/no-go, not free-text assumptions). **(decided 2026-10-20, review loop 1)** `ModelOutputInvalidError` (bounded retry) only when the reply had candidates, none survive, and none was dropped for a legitimate reason (`rule_duplicate`, `mandatory_constraint`, `not_current`); a reply whose survivors are zero because of legitimate drops counts as zero found and the gone pass runs. Zero candidates is valid.
- **Stale result:** if a newer detection pass or run exists for the Opportunity when accept runs, nothing is written and no retry happens.
- **Storage:** fingerprint `semantic:<type>:<sorted finding ids>`; same `detection_pass` as the payload; one position per cited Finding: `source` assessment, Assessment id/version, agent, `summary` = the stance, `value` null, Requirement = the Finding's first cited Requirement, new nullable `finding_id` (plain Uuid, like `assessment_id`). Actor `agent` `conflict_agent@<semver>` on `raise_conflict`, so `conflicts.conflict.detected` names it.
- **Gone:** after storing, each open semantic Conflict of the Opportunity from an earlier pass or run whose fingerprint was not raised is resolved by the system: "No longer present in <Agent> Assessment v<n>" (agents whose current version is newer than the cited one), else "Not raised again by the Conflict Agent." Rule auto-resolve stays rule-only; escalated semantic Conflicts stand. **(decided 2026-10-20, review loop 1)** When `finish_run` queues no job (fewer than two agents with Findings, or the agent disabled), it still resolves, in its Unit of Work, each open semantic Conflict whose cited Assessment is no longer current, with the same "No longer present in …" reason.
- **Live update (decided 2026-10-20: live):** every conflicts write that changes what the tab shows (`accept_semantic_conflicts`, the semantic gone pass, rule `detect_for_run`, 6.3 resolve/escalate) sends a `conflicts.changed` frame on the Opportunity's event stream (ids only, delivered on commit). The Conflicts tab label count and the open Conflicts tab refresh on it, like the Gaps tab's `useGapsEvents`.
- **Read/web:** `ConflictPosition` gains `finding: {id, title, kind} | null`. Rows and the inspector header show a "Detected from text" tag when `detected_by = semantic`; a position card with a Finding shows the Finding title and kind above the stance. 6.3 resolve/escalate works unchanged.
- **Eval:** `evals/conflicts/*.yaml` (≥6 cases: each of the four types plus two no-conflict decoys) with synthetic Findings per agent and expected Conflicts (type + Finding ids). `make eval-conflicts` runs the agent on the live gateway (no DB) through the same pure validation, matches a prediction to an expected Conflict when the type is equal and they share ≥2 Findings, and writes precision/recall per type to `evals/out/conflicts-<ts>/report.json`.
- **Privacy:** no Finding, stance or summary text in logs or trace.

**Never:**
- No change to the 6.1 rules or their auto-resolve; no `effort`, `timeline`, `resource` or `security` semantic types.
- No new workflow task kind or plan template change; no Critic or Red Team input; no Negotiation.
- No injection flag on Assessment Findings; no `registry_eval_results` storage or Admin → Evals change for conflicts; no CI gate.
- No live model in CI.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy | Eng F2 assumes on-prem SSO, Sec F5 requires cloud IdP | One open `architecture` semantic Conflict, two Finding positions, trace actor `conflict_agent@0.1.0` | N/A |
| Agree | Model returns no candidates | Nothing stored; earlier open semantic Conflicts resolved as gone | N/A |
| Same agent | Candidate cites two Engineering Findings | Dropped | N/A |
| Bad label | One candidate cites `F99` | That candidate dropped, others stored | N/A |
| All invalid | Every candidate malformed (unknown label/type, one agent, bad text) | Nothing stored | `ModelOutputInvalidError`, job retried once |
| All filtered | Every candidate is a rule duplicate, mandatory or not current | Nothing stored; earlier open semantic Conflicts resolved as gone; job succeeds | No retry |
| Mandatory | `mandatory_constraint: true` | Dropped | N/A |
| Rule dup | `scope` candidate whose Findings share R2 and R4 while rule `scope:R4` is open | Dropped | N/A |
| Clash | `assumption` candidate while a `recommendation_clash` is open | Kept | N/A |
| Stale | New run finished before accept | Nothing written | No retry |
| Rerun | New run; same contradiction | New Conflict (new Finding ids); earlier one resolved "No longer present in Engineering Assessment v3" | N/A |
| One agent | Only Engineering has Findings | No job queued; open semantic Conflicts citing superseded Assessments resolved as gone | N/A |
| Disabled | `conflict_agent` disabled | No job queued | N/A |
| Live | Conflicts tab open while the semantic job stores a Conflict | Badge count and list update without navigation | Stream drop: next navigation shows it |

</frozen-after-approval>

## Code Map

- `backend/app/modules/workflows/application/runs.py` -- `finish_run` (:364) → `detect_conflicts` (:418-437); queue the job right after, passing the pass returned by `detect_for_run`.
- `backend/app/modules/conflicts/application/conflicts.py` -- `raise_conflict` (:106, has `detected_by` and `actor`), `detect_for_run` (:247, pass = latest+1, rule-only gone at :277-297). Add `accept_semantic_conflicts` + the gone pass in a new `application/semantic.py`; export from `application/public.py`.
- `backend/app/modules/conflicts/domain/` -- `DetectedBy.SEMANTIC` (conflicts.py:60, already in the CHECK); fingerprint helper `rule_of` (rules/__init__.py:42) must not treat `semantic:` as a rule; reason helper beside `resolution.py:45`. Put candidate validation as a pure function in `domain/semantic.py` (shared with the eval).
- `backend/app/modules/conflicts/adapters/models.py:99-143` -- `conflicts_positions`: add `finding_id`.
- `backend/app/modules/assessments/` -- Findings in `assessments_assessment_findings` (models.py:206) + `…_finding_requirements` (:235); `current_assessments` / `findings_of` (assessment_repository.py:220/231). Add a principal-free public read of the current Assessments' Findings (id, agent, Assessment id/version, kind, severity, title, detail, Requirement ids/versions) and a by-id Finding title/kind read for the conflicts view.
- `backend/app/modules/assessments/application/review.py` -- the pattern: payload :89, `_start` :409, `_review` :488, accept :208, `register(JobType…)` :530. Register the module in `app/main_worker.py:47-59 _JOB_MODULES`.
- `backend/app/agents/red_team_agent/{agent,schema}.py` -- copy `data_blocks` (:85), `messages` (:134), `run` (:144) and the `str`+enum schema style into `app/agents/conflict_agent/`.
- `backend/app/agents/manifest.py:80-97` -- two `SchemaVersion("conflict_agent", …)` rows; regenerate `manifest.json` (`uv run python -m app.agents.manifest`).
- Migration `0033_conflict_agent`, `down_revision = "0032_gaps_answers"`: seed the agent + config v1 with `registry/domain/registry.py` id helpers (:27-37); add `finding_id`. Don't edit 0026; add the agent to the test seed lists (`tests/test_registry.py:80-89, :212, :239`).
- Tests: `FakeGateway` + `gateway` fixture (`tests/test_intake_extraction.py:81-104, :188`), `seed_config` (`tests/agent_configs.py`), `review_settings` monkeypatch as in `tests/test_assessments_red_team.py:56`.
- Web: `components/opportunities/conflicts-list.tsx` (row :75-113), `conflict-inspector.tsx` (header :557-570, `PositionBody` :95-126), `lib/conflicts.ts`, `app/opportunities/[id]/conflicts.tsx:8` (comment says "rules" only). Regenerate `lib/api/schema.d.ts` from a local uvicorn.
- Live update: copy `gaps/adapters/repository.py:125 notify_gaps_changed` (`pg_notify` on `psa_events`, `source`) as `notify_conflicts_changed`; map the new source in `workflows/application/events.py` (`GAPS_SOURCE` :49, source mapping :103-109, frame emit :144); web `lib/opportunity-events.ts` (`GAPS_CHANGED` :87, hook :136) → `CONFLICTS_CHANGED` + `useConflictsEvents`; wire in `components/opportunities/workspace-tabs.tsx:10-36` (badge) and the Conflicts section (`router.refresh()`); tests beside `lib/opportunity-events.test.tsx`.
- Eval: `Makefile` (only `eval` today), `backend/app/evals/__main__.py:31-55` (add a `conflicts` command or module), `evals/README.md`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/agents/conflict_agent/**`, `manifest.py`/`manifest.json` -- agent, prompt v1, schema
- [x] `backend/migrations/versions/20261020_0033_conflict_agent.py` -- seed + `finding_id`
- [x] `backend/app/modules/assessments/application/*` -- Findings reads
- [x] `backend/app/modules/conflicts/{domain,application,adapters,api}/**` -- validation, job, `accept_semantic_conflicts`, gone pass, `finding` on positions
- [x] `backend/app/modules/workflows/application/runs.py`, `app/main_worker.py` -- queue + register the job
- [x] `backend/tests/test_conflicts_semantic*.py` (pure + Postgres with fake gateway) -- every matrix row, trace actor, registry seed
- [x] `backend/app/modules/{conflicts,workflows}/**` -- `conflicts.changed` notify on every conflicts write + stream mapping, with a test
- [x] `web/src/**` -- schema, "Detected from text" tag, Finding on position cards, `useConflictsEvents` for the badge and tab, tests with axe
- [x] `evals/conflicts/*.yaml`, `backend/app/evals/conflicts.py`, `Makefile`, `evals/README.md` -- eval runner with a unit test on scoring

**Acceptance Criteria:**
- Given a run whose specialists contradict each other in free text, when the semantic job finishes and the Conflicts tab is opened, then the Conflict is listed as "Detected from text" with a card per cited Finding and can be resolved as in 6.3.
- Given CI, when it runs, then backend and web checks pass with no live model.
- Given a live model, when `make eval-conflicts` runs, then a report with precision and recall per type is written.

## Implementation Notes

- **Detection passes are recorded** (`conflicts_detections`, migration 0033): `detect_for_run` now records each pass even when the rules raise nothing. Without it a run whose rules raised nothing would reuse pass 1 on a retry, and the semantic job could not tell a newer pass or run happened (the Stale row). `latest_pass` takes the max of recorded passes and stored Conflicts (existing data is backfilled). `detect_for_run` returns `Detection(detection_pass, raised)`.
- **Module boundary:** `conflicts` still never imports `assessments` at module level (`assessments` imports `conflicts`). `conflicts/application/findings.py` imports `assessments.application.public` at call time for the current Findings, the current Assessment versions and the Finding titles, with one `ignore_imports` entry in the import-linter contract. `assessments.current_finding_snapshots` / `finding_titles` return `conflicts` DTOs, as `current_assessment_snapshots` already did.
- **The job lives in `conflicts/application/semantic.py`** and is registered on import of `conflicts.application.public`, so `finish_run` can enqueue it in either process; also listed in `main_worker._JOB_MODULES`. `queue_semantic_detection` decides "≥2 agents with Findings" and the registry check.
- **Candidate schema:** `stances` is a list of `{finding_label, stance}`; a cited Finding without a non-blank stance of ≤240 characters, a blank or over-240 summary, or an unknown severity also drops the candidate (as the Red Team drops bad Findings). A second candidate with the same fingerprint in one reply is dropped as a duplicate.
- **Rule dedupe keys** come from the rule Conflicts stored in the run's pass plus the Opportunity's open/escalated rule Conflicts (an escalated rule Conflict that "stands" stores nothing in the new pass).
- **Loop 1 — retry only bad output:** `SemanticValidation.retry` is true only when candidates were proposed, none survived and none was dropped as `rule_duplicate`, `mandatory_constraint` or `not_current` (`LEGITIMATE_DROPS`); `accept_semantic_conflicts` raises `ModelOutputInvalidError` only then, otherwise stores nothing and still runs the gone pass, and the job succeeds.
- **Loop 1 — gone pass without a job:** when `queue_semantic_detection` queues nothing (fewer than two agents with Findings, or the agent disabled), it locks the Opportunity's Conflicts and resolves each open semantic Conflict with a position whose (Assessment id, version) is no longer its agent's current one, with the same reason, `conflicts.conflict.resolved` event (`no_longer_present`, actor `system`/`conflicts.semantic_detection`) and `conflicts.changed` notify. In tests the "fewer than two agents" path can't be reached by a rerun (a specialist reply with no Findings is invalid, so the previous Assessment stays current); the integration test drives it through the disabled agent, which takes the same branch.
- **Loop 1 — dedupe per shared Requirement, scope only:** `rule_key` maps only `scope:<r>:…` to (scope, r); a `scope` candidate is a `rule_duplicate` when any Requirement every cited Finding cites (`shared_requirements`) has such a key. The `recommendation_clash` → assumption key is gone, so `assumption` candidates are never deduped against rules.
- **Loop 1 — gone pass when the job ends without an accept:** when `_start` finds the agent disabled or fewer than two agents with Findings, or the handler fails on its final attempt, `_gone_without_accept` runs the same superseded gone pass in a fresh Unit of Work, unless the pass is stale; on the final failure it runs before the re-raise and its own error is only logged. Inactive Requirements sort last (`math.inf`) when choosing a position's first Requirement.
- **Loop 1 patches:** title and detail are collapsed to one line in each Finding's data block (a newline can't fake a field line); the eval refuses unreadable or malformed YAML, non-string or single-agent `expected.findings` and boolean Requirement numbers with `CaseError` (exit 2); the 0033 downgrade docstring now says the Agent and its versions are deleted unconditionally.
- **Gone reason:** names every cited agent whose current Assessment is newer ("No longer present in Engineering Assessment v2 and Security Assessment v2"), else "Not raised again by the Conflict Agent."; actor `system` / `conflicts.semantic_detection`, `reason_kind` `no_longer_present`. Carried-forward semantic Conflicts (same Finding ids, e.g. a retry pass) are closed by `raise_conflict` as for rules.
- **Live:** `conflicts.changed` is sent by `detect_for_run` (when it creates or resolves), `accept_semantic_conflicts` (same), and every 6.3 resolve/escalate. The workspace tab strip takes `loadConflictCount` (server action `countOpenConflicts`); the Conflicts tab renders `ConflictsLiveRefresh` (`router.refresh()`). `useGapsEvents` and the new `useConflictsEvents` share one EventSource per Opportunity.
- **Eval:** `app.evals` may not import agents or `conflicts` internals, so `conflicts.evaluate_semantic` (public) runs the agent and the pure validation; the runner uses the live `ModelGateway` with its call-row write disabled (no database). `make eval-conflicts ARGS="--only <case> --profile <p>"`.

## Spec Change Log

- **Loop 1 (review #1–#3, intent gap):** legitimately filtered replies retried and died before the gone pass; no gone pass when no job was queued; the clash → assumption dedupe suppressed unrelated assumption Conflicts and scope dedupe missed multi-Requirement candidates. The human chose "retry only bad output" (with the no-job gone pass), "dedupe per shared Requirement, scope only", and "amend in place" (no revert). Amended (frozen, with approval): the Validation and Gone bullets and the All invalid / All filtered / Rule dup / Clash / One agent matrix rows. Avoids: dead jobs and stale open semantic Conflicts; dropped real assumption Conflicts. KEEP: everything else (agent, prompt, job phases, stale check, storage, positions, live updates, web, eval).

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind+edge+vgap | When every candidate is dropped for a legitimate reason (`rule_duplicate`, `mandatory_constraint`, `not_current`), `accept_semantic_conflicts` raises `ModelOutputInvalidError`: a useless retry, the job dies, and `_resolve_gone` never runs, so stale semantic Conflicts stay open | medium | intent_gap | Frozen: "If the reply had candidates and none survive → `ModelOutputInvalidError`"; the raise precedes `_resolve_gone` (semantic.py accept). Grouped with #2 (root: the gone pass only runs on a successful accept). |
| 2 | vgap other | No gone pass when no job is queued (a rerun leaves fewer than two agents with Findings, or the agent is disabled): open semantic Conflicts citing superseded Assessments stay open | medium | intent_gap | `queue_semantic_detection` returns before any write; `detect_for_run` skips semantic Conflicts by design. Frozen block does not say what happens then. |
| 3 | blind+edge | Dedupe key: while a `recommendation_clash` is open, every semantic `assumption` candidate whose Findings don't share exactly one Requirement is dropped; a `scope` candidate sharing two Requirements is never deduped against `scope:<r>` | medium | intent_gap | Frozen dedupe rule maps `recommendation_clash` → (assumption, none) and a candidate's Requirement to the single shared one, else none; `requirement_of` returns None for 0 or ≥2. |
| 4 | blind+vgap other+edge | `latest_detection` orders by `created_at = now()` (transaction start), so overlapping finishes could pick the older pass | false | reject | Only one run can be in progress per Opportunity (`run_in_progress` guard, assessment_runs.py:143/172, under the run lock), and the specialists finish inside one `workflows.execute` job, so two detection transactions of one Opportunity never overlap. |
| 5 | blind | Dedupe also uses every open/escalated rule Conflict of the Opportunity, wider than the docstrings' "same detection pass" | low | patch | Open rule Conflicts are carried into the latest pass, so the extra set is only escalated earlier ones, which deduping against is right; the docstrings in `domain/semantic.py` and `validate_semantic` misdescribe it. Fix the docstrings. |
| 6 | blind | Semantic Conflicts never carry forward across Assessment versions (new Finding ids) | false | reject | Frozen fingerprint is the Finding ids and the Rerun matrix row expects a new Conflict with the earlier one resolved. |
| 7 | blind+edge | Missing `conflict_agent` registry row makes `finish_run` raise | false | reject | Only reachable with migration 0033 unapplied, a deployment error that should fail loudly; the registry has no delete. |
| 8 | blind | Migration downgrade docstring says "unless something references its versions" but deletes unconditionally | low | patch | Docstring vs code at 0033 `downgrade`. Fix the docstring. |
| 9 | blind | `ValidSemantic.requirement_id` unused; positions use each Finding's first Requirement | false | reject | Frozen: position Requirement = "the Finding's first cited Requirement"; `requirement_id` is used for the dedupe key. |
| 10 | blind | `make eval-conflicts` exits 0 when every case errors | low | reject | Errors are listed in the report and printed; no gate is in scope; adding exit logic is new behaviour. |
| 11 | blind | Eval set too thin for per-type figures | low | reject | Frozen asks for ≥6 cases (four types + two decoys); a baseline, not a gate. |
| 12 | blind | A newline in a Finding title/detail can fake `severity:`/`requirements:` lines inside its block | low | patch | `data_blocks` writes title/detail raw; collapsing each to one line is a direct correction. |
| 13 | blind | No detection status on the Conflicts tab | low | reject | Not in the intent; new UI. |
| 14 | blind | Live refresh does several full reads per event; `countOpenConflicts` reads the whole view | low | reject | Efficiency only; a count endpoint adds API surface. |
| 15 | blind | Web casts `finding.kind` to `FindingKind` unchecked | false | reject | `assessments_assessment_findings.kind` has a CHECK limiting it to the four kinds. |
| 16 | blind+vgap | No test that escalating sends `conflicts.changed` | medium | patch | Pre-verified: only the resolve frame is tested; removing decisions.py:329 fails nothing. |
| 17 | blind | Untested: final failed attempt, concurrent finishes, missing registry row, gone with no agent | low | reject | Covered by #1/#2 (intent gap), #4 (unreachable), #7 (rejected); positions of an assessment-source Conflict always carry agent and version (CHECK). |
| 18 | vgap | No test that rule detection sends `conflicts.changed` | medium | patch | Pre-verified: deleting conflicts.py:318 fails no test. |
| 19 | vgap | No test where pass 1 stores nothing, so the recorded-pass numbering is untested | medium | patch | Pre-verified: every multi-pass test stores a Conflict in pass 1; reverting `latest_pass` fails nothing. |
| 20 | vgap | `countOpenConflicts` has no unit test (sibling `countOpenGaps` does) | medium | patch | Pre-verified: only a mock in pages.test.tsx. |
| 21 | edge | A person-resolved semantic Conflict re-proposed in a retry pass with reworded stances reopens (`_reads_the_same` compares summaries) | low | reject | Needs a retry pass of the same run with the same Findings after a person decided; rare; the fix adds a semantic branch to `raise_conflict`. |
| 22 | edge | Malformed or unreadable case YAML raises a traceback (exit 1) though the CLI docstring promises exit 2 | low | patch | `load_cases` doesn't wrap `yaml.YAMLError`/`OSError`; direct correction: raise `CaseError`. |
| 23 | edge | Non-string `expected.findings` items raise `TypeError` | low | patch | `set(cited_keys)` on unhashables; direct check in `parse_case`. Grouped with #22, #24, #25 (case validation). |
| 24 | edge | An expected Conflict citing one agent's Findings is a permanent false negative | low | patch | Validation drops one-agent candidates; `parse_case` should refuse it. |
| 25 | edge | `requirements: [true]` accepted as R1 | low | patch | `isinstance(True, int)`; add `not isinstance(r, bool)`. |
| 26 | edge | Greedy first-fit matching can under-report | low | reject | One expected Conflict per case today; optimal matching adds complexity. |
| 27 | edge | `extra="forbid"` lets one extra key fail the whole reply | low | reject | Same as the other agents' schemas; `format` constrains decoding and the gateway retries. |
| 28 | r2 blind | `requirement_id` unused; positions use each Finding's first Requirement | false | reject | carried #9. |
| 29 | r2 blind+edge | `created_at = now()` ordering race in `latest_detection` | false | reject | carried #4. |
| 30 | r2 blind | Eval exits 0 when every case errors | low | reject | carried #10. |
| 31 | r2 blind | Eval set too thin; hard-coded eval semver | low | reject | carried #11 (semver is the seeded v1, same as the migration's literal; a test pins the seed). |
| 32 | r2 blind | Live refresh fetches several times per change | low | reject | carried #14. |
| 33 | r2 blind | Unchecked `FindingKind` cast | false | reject | carried #15. |
| 34 | r2 edge | Fingerprint by Finding ids: decided Conflicts come back unlinked after a rerun | false | reject | carried #6. |
| 35 | r2 edge | Reworded stances reopen a decided Conflict in a retry pass | low | reject | carried #21. |
| 36 | r2 edge | Missing registry row aborts `finish_run` | false | reject | carried #7. |
| 37 | r2 blind | Generated `schema.d.ts`, `manifest.json` and compose files absent from the diff | false | reject | Excluded from the review diff on purpose: generated files, checked by `npm run typecheck` and `manifest --check`; the compose files are the user's pre-existing uncommitted pgAdmin change, not this story. |
| 38 | r2 blind+edge | No superseded-gone pass when the job is skipped at job time (`_start`: agent disabled, fewer than two agents) or dies on its final attempt (gateway down): stale semantic Conflicts citing old versions stay open | medium | patch | `_start` returns None and the handler re-raises without cleanup; loop-1 decision intends superseded semantic Conflicts to be resolved whenever no accept happens; a dead gateway (Ollama not running) is a real case. Smallest fix: run the existing superseded gone pass in a fresh Unit of Work on those exits. |
| 39 | r2 blind | `not_current` checked before `bad_summary`/`bad_stance`, so a malformed candidate that also cites a superseded Assessment suppresses the retry | low | reject | After the stale check (same latest pass), a cited Assessment can't be superseded: Assessments change only through a run, which records a newer pass; needs both conditions at once. |
| 40 | r2 blind | A non-repeat by the model resolves a Conflict whose Findings are unchanged (flapping) | false | reject | Frozen Gone rule: not raised again → "Not raised again by the Conflict Agent." |
| 41 | r2 blind | No size limits on the Findings sent or the reply | low | reject | Specialists return a handful of Findings; no named overflow; budgets are 5.6. |
| 42 | r2 blind | A live refresh could disrupt an open inspector mid-edit | false | reject | `ConflictsSection` derives the list and the selected Conflict from the refreshed props and keeps its own state; the open Conflict's form is untouched unless that Conflict changed. |
| 43 | r2 blind | A semantic position with `finding: null` uses the hours style | false | reject | Findings are insert-only (no delete grant), so a cited Finding's title always resolves. |
| 44 | r2 vgap | No test that a queued job is skipped once the agent is disabled | medium | patch | Pre-verified: no test disables the agent between queueing and draining. |
| 45 | r2 vgap | No test that a resolved semantic Conflict's cards keep the superseded Finding's title | medium | patch | Pre-verified: `finding` is only asserted on current-Assessment Conflicts. |
| 46 | r2 edge | `label_findings` sorts an inactive Requirement as `len(numbers)+1`, which is below a gapped active number (e.g. {1, 5}), so it can become `first_requirement` | low | patch | `requirement_numbers` values are R numbers, which can exceed the count; direct correction (`math.inf`). |
| 47 | r2 edge | Two quick `conflicts.changed` frames can resolve count reads out of order | low | reject | Rare; the next frame or navigation corrects it; the Gaps badge has the same accepted shape; the fix adds a sequence ref. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass

**Manual checks:**
- Run an assessment on the demo Opportunity with the cloud profile; a semantic Conflict appears with its Finding cards; `make eval-conflicts` writes a report.
