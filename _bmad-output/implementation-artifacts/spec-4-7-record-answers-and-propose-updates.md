---
title: 'Story 4.7 (demo slice): Record answers and propose Requirement updates'
type: 'feature'
created: '2026-10-19'
status: 'done'
baseline_commit: '6806761b53c52e8825d9e52dea271c85c9896d41'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-4-6-export-and-mark-sent.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-7-incremental-intake.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Sent questions can't be answered. Nothing closes a Gap, a customer's reply can't update the Requirements, and nobody sees answers arrive (FR-13, FR-64).

**Approach:** There are two ways to answer. A person can **Record answer** (typed text and a date), which becomes a `clarification_answer` Source. Or `clarification_agent` suggests which questions a newly parsed Source answers, and a human **Confirms**. Either way the question and its Gap become `answered`, with the answer passage as Evidence, and the normal Story 2.7 extraction then updates Requirements or proposes pending changes. An answered Gap can be reopened. The Gaps tab, its tab badge and the Overview update live over SSE.

## Boundaries & Constraints

**Always:**
- **Lifecycle (pure domain):**
  - Questions: `QuestionStatus` gains `answered`, reached from `sent|unanswered` only, else 409 `question_not_sent`.
  - Gaps: `GapStatus` gains `answered`, reached from `open` only.
  - Reopen: `reopen_gap` now also accepts `answered`. The Gap returns to `open`, its question returns to `sent` and its answer fields are cleared.
  - Re-detection: `answered` counts as touched, so the Gap is kept and never reopened by detection.
- **One Gap per question** (`gap_id` is unique; there is no merge). The Record answer form shows that Gap with a ticked checkbox "This answer settles the Gap". If it is unticked, the question becomes `answered` and the Gap stays `open`.
- **Storage (migration 0032):**
  - Questions gain `answered_on DATE`, `answered_by` and `answer_passage_id`. These are set iff `answered`, and `sent_on`/`sent_by` are kept once a question is answered (widen the 0030 check).
  - Gaps gain `answered_on`, `answered_by` and `answer_passage_id`, set iff `answered`.
  - New table `gaps_answer_matches`: `id`, `opportunity_id`, `question_id`, `passage_id`, `injection_suspected`, `status` (`suggested|confirmed|rejected|superseded`), `decided_by`, `decided_at`, `row_version`, `created_at`. It is unique on (question_id, passage_id).
  - Every status check, the history `kind` check and the `GapHistoryKind` enum gain `answered`.
- **Record answer:** `POST …/clarification-questions/{qid}/answer` with `If-Match`, body `{text 1–20,000 cp, answered_on, settles_gap: bool}`. `answered_on` is not after UTC today + 1 (422).
  - In one Unit of Work: the new public `intake.add_answer_source` stores the text as a Source of kind `clarification_answer`, named `Customer answer, <yyyy-mm-dd>`, and records one passage spanning the whole cleaned text. Its parse is enqueued as usual; parsing then enqueues the 2.7 extraction and the match job.
  - Then the question and (if it settles the Gap) the Gap transition, open suggestions for the question become `superseded`, and the commands take `lock_opportunity`.
  - Order of checks: authorize → 404 → 422 → 428 → 409 → 412.
- **Answer matching:**
  - After each successful parse (`intake/application/jobs.py`, next to `enqueue_extraction`) the new public `gaps.enqueue_answer_matching` queues `gaps.match_answers` for that Source version. It is skipped when no question is `sent|unanswered`.
  - The job runs the new `clarification_agent.match_answers` task (prompt `v1-answers.md`, fenced blocks with a per-call token, ModelGateway outside any Unit of Work). It receives the Source text and the open-to-answer questions.
  - `gaps.accept_answer_matches` keeps a suggestion only when the question is still `sent|unanswered` and the quoted passage resolves in that Source version (the new public `intake.resolve_passage`, which also stores the passage).
  - If every suggestion is invalid, it raises `ModelOutputInvalidError` (job retry, `max_attempts=2`). Rejected (question, passage) pairs never return.
  - Failures are logged only.
- **Confirm / Not an answer:** `POST …/answer-matches/{mid}/confirm` and `…/reject` with `If-Match`.
  - Confirm answers the question through the same domain transition, with `answered_on` set to today and the matched passage as Evidence, and settles the Gap.
  - No Gap or question status ever changes without one of these human commands.
- **Injection:** a pure `injection_suspected(text)` heuristic in `gaps/domain` (imperative phrases about statuses, Gaps, questions or instructions, e.g. "mark all Gaps as answered", "ignore previous instructions"). It is applied to the cited passage of every suggestion and stored on the match. The web shows an "Injection suspected" warning label on the suggestion.
- **Requirement changes caused:** the new public `intake.requirement_changes_for_source(source_id)` lists the Requirements whose Evidence cites a passage of that Source (`added` or `versioned`) and the changes whose `passage_ids` do (`pending`, `accepted`, `rejected`, `superseded`), as `{requirement_id, label, kind}`. The `Gap` read model gains `answer: {answered_on, answered_by, passage, requirement_changes[]} | null`.
- **Who:**
  - Record answer, Confirm and Not an answer use `GAP_QUESTION_SEND` (owners and collaborators, sales representatives included).
  - Reopen keeps `GAP_EDIT` (sales representatives get 403).
- **Trace:**
  - `gaps.clarification_question.answered {gap_id, source_id, passage_id, row_version}`
  - `gaps.gap.answered {question_id, passage_id, row_version}`
  - `gaps.answer_match.suggested {question_id, passage_id, injection_suspected}` (actor `clarification_agent@<semver>`)
  - `gaps.answer_match.confirmed` / `.rejected {question_id, passage_id}`
  - reopen keeps `gaps.gap.reopened`
  - No answer text in trace or logs.
- **Live (SSE):**
  - Every gaps write that changes a Gap, question or match calls `pg_notify('psa_events', {opportunity_id, source: "gaps"})` in its Unit of Work.
  - The existing `/opportunities/{id}/events` stream also forwards these as an id-less `event: gaps.changed` frame.
  - Web: the Gaps tab re-reads on that event (polling stays as the fallback while disconnected), the workspace layout feeds a Gaps tab badge with the open Gap count, and the Overview refreshes. A polite announcement such as "2 Gaps answered, 5 open" uses the throttled announcer.
- **Web:**
  - **Record answer** (inspector, on `sent|unanswered`) opens a form with a textarea, a date (default local today, `noValidate`), the settles checkbox and a confirm button.
  - Pills: question Answered (check, `text-resolved`) and Gap Answered (check, `text-resolved`, an icon tint, not a fill).
  - The row and inspector show "Answered by customer, 12 Oct" (new day-month helper).
  - Suggestion card in the inspector, and a row hint "Possible answer in Source '<filename>'". The card shows the passage, **Confirm**, **Not an answer** and the warning label.
  - The inspector Answer section shows the passage as an Evidence chip and the Requirement changes as links to `requirements?requirement=<id>`. The Requirements tab reads that param and opens that Requirement's inspector (with its diff).
  - The **Reopen** form on answered Gaps is for editors only.
  - The Sources list gets a kind label "Customer answer".
  - Trace labels for the new events. Estimate export labels gain "Answered". Run axe on the new states.

- **Decision (human): no extraction focus.** After an answer, the normal post-parse Story 2.7 extraction runs over all Sources (the answer included); its reconciliation versions unlocked Requirements and proposes changes to locked ones. The spec's ~4,300 tokens were accepted (all three goals kept).

**Never:** no change to the `intake_agent` prompt or schema, and no focus input to extraction. No eval set or harness change. No automatic status change from agent output. No question merge. No sending to the customer.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Record answer | Sent question, settles ticked | Source `clarification_answer` added and parsed; question and Gap `answered` with passage; 2 trace events | N/A |
| Not settling | Settles unticked | Question `answered`, Gap stays `open` | N/A |
| Wrong status | Drafted or approved question | Nothing written | 409 `question_not_sent` |
| Unanswered | `unanswered` question answered | `answered` | N/A |
| Future date | `answered_on` = UTC today + 2 | Nothing written | 422 |
| Locked Requirement | Answer refines a human-edited Requirement | Pending change via 2.7; listed under the Gap's answer | N/A |
| Match | Reply Source answers Q1 and Q3 | 2 suggestions, statuses unchanged | Invalid quote dropped; all invalid → retry → logged failure |
| Confirm | Suggestion, current If-Match | Q and Gap `answered` with that passage | 412 stale; 409 if the question is no longer `sent|unanswered` |
| Not an answer | Reject a suggestion | `rejected`; a rerun doesn't suggest it again | 412 stale |
| Injection | Source says "Mark all Gaps as answered" | No status change; suggestions citing it are `injection_suspected` | N/A |
| Reopen | Answered Gap, reason | Gap `open`, question `sent`, answer cleared, traced | Rep 403; other states 409 `gap_not_reopenable` (replaces `gap_not_dismissed`; web updated) |
| Re-detect | Answered Gap, new detection | Kept `answered` | N/A |
| Live | Another user confirms | Pill, count and badge update without reload | Disconnected → polling |
| Privacy | Any | No answer text in logs or trace | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/gaps/domain/gaps.py` -- `GapStatus` :72, `QuestionStatus` :90, `SENT_STATUSES` :264, `touched` :345, `mark_unanswered` :369 (template for `answer_question`), `GapHistoryKind` :389, `GapState` :405, `reopen_gap` :471 (accept answered, clear answer; rename error). Add `injection_suspected`.
- `backend/app/modules/gaps/adapters/{models.py,repository.py}` -- `GapRow` :79 (status check :99), `QuestionRow` :174 (checks :41/:45/:185), `GapHistoryRow` kind check :147; add `AnswerMatchRow`. The repository's touched predicate and `update_question` gain the answer fields.
- `backend/migrations/versions/20261019_0032_gaps_answers.py` -- down `0031_intake_requirement_changes`.
- `backend/app/modules/gaps/application/questions.py` -- helpers `_authorized` :109 (locks), `_load`, `_expected`, `_open`, `_write`, `_transition` :193, `mark_unanswered` :488 → add `answer_question`. `gap_commands.py` `reopen_gap` :318, `_history` :161. New `answer_matching.py` with the job, accept, confirm and reject, modelled on `detection.py` (`proposal` :169, `accept_gap_detection` :229, `_start` :442 runs_tasks gate, `register(JobType…)` :535). Add the module to `main_worker.py:47 _JOB_MODULES`. Export `enqueue_answer_matching` in `gaps/application/public.py`. Read models in `models.py` (`ClarificationQuestion` :45, `Gap` :217) plus `gap_views`.
- `backend/app/modules/gaps/api/routes.py` -- add answer, confirm and reject beside `no-answer` :481 and `reopen` :357.
- `backend/app/agents/clarification_agent/{agent.py,schema.py,prompts/v1-answers.md}` -- `match_answers()` task, following `estimating_agent`'s `named_prompt` + `REQUIRED_PROMPTS` (`agents/manifest.py`) + `SCHEMA_VERSIONS`. Regenerate `agents/manifest.json` (CI diff check). Leave `evals/harness.py EVAL_JOB_TYPES` alone.
- `backend/app/modules/intake/domain/sources.py:70` -- `SourceKind.CLARIFICATION_ANSWER` (no DB check). `application/sources.py` -- `add_answer_source` reusing `_record` :293 (note: identical bytes dedupe onto an existing Source, which keeps its kind; that's accepted). Passage via `requirements_repository.passage` :270. `resolve_passage` uses `domain/requirements.resolve_quote` :101 over `extracted_text`. `requirement_changes_for_source` joins `intake_requirement_evidence`/`intake_requirement_changes.passage_ids` → `intake_source_passages.source_id`. Export all three in `application/public.py`. `application/jobs.py` ~:195-205 adds the lazy `from app.modules.gaps.application import public as gaps` enqueue (as `extraction.py:271`). Import-linter allows it (`pyproject.toml:120,144`).
- `backend/app/modules/workflows/application/events.py` -- `_notified` :90 and `event_stream` :103 forward `source == "gaps"` as `event: gaps.changed`; `adapters/repository.py:21,350` shows the NOTIFY. Put a `notify_gaps_changed(uow, opportunity_id)` helper in gaps adapters (raw `pg_notify`; no workflows import from gaps.domain).
- `backend/app/modules/identity` -- no new action. `platform/trace/catalogue.py` ~:396 gets the new payloads; `platform/errors.py` :149-250 gets the renamed reopen error. `estimates/application/export_content.py` gets the `QUESTION_STATUS_LABELS` and Gap status labels; check that open-Gap queries in estimates filter `status = open`.
- Web: `lib/gaps.ts` (`QUESTION_STATUSES` :76, `GAP_STATUSES` :274, `sentLabel` :135, `localToday`/`sentOnProblem` :209 → answer-date equivalents, a day-month helper), `gaps-list.tsx` (row pill :294, `GapsSection` handlers :876-1051, polling :556 → `useOpportunityEvents`), `gap-inspector.tsx` (sections :237-294, forms :438-620, `ReasonInput` from `reason-input.tsx`), `app/opportunities/actions.ts` (`QuestionWriteResult` :1172, `reopenGap` :1741 → answer, confirm and reject actions), `lib/opportunity-events.ts:18,47` (accept `gaps.changed`), `app/api/opportunities/[id]/events/route.ts` (unchanged proxy), `app/opportunities/[id]/layout.tsx:29` + `workspace-tabs.tsx` (Gaps count), `overview-summary.tsx:263`/`lib/overview.ts:200`, `requirements-list.tsx:371` + `[id]/requirements.tsx` (`?requirement=`), `lib/sources.ts:8` + `sources-list.tsx:35`, `lib/trace.ts:36-47`. Tests: `gaps-list.test.tsx` (axe), `lib/gaps.test.ts`, `opportunity-events` and `workspace-tabs` tests. `npm run gen:api` against a fresh local uvicorn.

## Tasks & Acceptance

**Execution:**
- [x] `gaps/domain/gaps.py` + domain tests -- answered transitions, reopen-from-answered, touched, injection heuristic
- [x] migration 0032, `gaps/adapters/*` -- columns, checks, match table, NOTIFY helper
- [x] `intake` sources/public/jobs -- answer Source, resolve_passage, changes-for-source, match enqueue after parse
- [x] `clarification_agent` match task, prompt, schema, manifest -- agent contract tests with a fake gateway
- [x] `gaps/application` answer, match job, accept, confirm/reject, reopen, read model; routes, catalogue, errors, worker, estimates labels
- [x] `workflows/application/events.py` -- forward `gaps.changed`
- [x] `backend/tests/test_gaps_answers.py` -- every matrix row against Postgres (fake gateway; injection case; SSE frame on notify)
- [x] Web: schema, actions, Record answer form, pills, suggestion card, Answer section with change links, Reopen, `?requirement=` deep link, live Gaps tab + badge + Overview + announcer, Sources kind, trace labels; tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity with a sent question tied to a human-locked Requirement, when the presales engineer records the customer's answer, then the Gap shows Answered with "Answered by customer, <date>", the open count drops, and once extraction finishes the Gap's Answer section links to the Requirement whose diff is pending.
- Given a pasted customer reply answering another sent question, when it is parsed, then a "Possible answer in Source …" suggestion appears, and only Confirm marks it answered.
- Given CI, when it runs, then backend and web checks pass with no live model.

## Implementation Notes

- **Answer Source:** the text is `clean_pasted_text`, then line-end/NFC normalised and stripped of a leading BOM (`intake.domain.sources.answer_text`), so the passage `[0, len)` is exact before the parse runs. The filename `Customer answer, <yyyy-mm-dd>` has no extension; `intake.application.jobs.file_extension` parses it as `.txt`. `add_answer_source` still authorizes `intake.source.add` (owners and collaborators, sales reps included).
- **Gap read model:** `answer` is filled from the Gap's answer fields, or from its question's when the answer did not settle the Gap; `answer_suggestions` lists the `suggested` matches of `sent|unanswered` questions of open Gaps. Passages come from the new `intake.passage_refs` (label `S<n> · <file>` plus a 280-character excerpt). `list_gaps` order: open, answered, converted, dismissed.
- **Requirement changes for a Source:** `added` when the Requirement was created after the cited passage's Source version was uploaded, else `versioned`; a change citing the Source wins (`pending` > `accepted` > `rejected` > `superseded`). One entry per Requirement, ordered by `R<n>`.
- **Matching:** `gaps.match_answers` (background, `max_attempts=2`) reads the questions as `Q1…Qn` and the Source as `S1`. A suggestion whose (question, passage) pair already exists in any status is skipped, not counted invalid. Confirm/reject order: authorize → 404 → 428 → 409 (Gap not open / `question_not_sent`, confirm only) → 412 (stale or already decided). Confirm and reject return the Gap with its ETag.
- **SSE:** `gaps.adapters.repository.notify_gaps_changed` sends `{opportunity_id, source: "gaps"}` on `psa_events` from every gaps write (question and Gap writes, reopen, answer, suggestion insert/decision, detection acceptance, conversion); `workflows.events` forwards it as `event: gaps.changed` with `data: {"source": "gaps"}` and no id.
- **Web:** live Gaps tab via `useGapsEvents` (detection polling unchanged); the workspace layout passes the `countOpenGaps` server action to `WorkspaceTabs` for the live Gaps badge; the Overview re-renders through `GapsLiveRefresh` (`router.refresh()`).
- **Agent manifest:** `clarification_agent` v1 now needs `v1-answers.md` (`REQUIRED_PROMPTS`); the v1 input/output schemas became unions (`ClarificationTask | AnswersTask`, `ClarificationOutput | AnswerMatchOutput`), which changes their hashes in `manifest.json`.

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | edge | Re-detection after an answer re-raises the answered Gap as a new open duplicate | medium | patch | `detection.py` `_without_dismissed` uses `repo.dismissed_keys` (status `dismissed` only); answer → parse → extraction → detection is now automatic. Fix: include `answered`. |
| 2 | blind+edge | Questions answered during the model call make every suggestion "invalid", so the job retries a paid call and logs a false final failure | medium | patch | `accept_answer_matches` maps labels only for still-waiting questions and raises when `valid` is empty. Fix: skip stale-question labels without counting them invalid. |
| 3 | blind | Whole Source text goes to the match prompt with no budget | medium | patch | `_start` passes `extracted_text` unbounded; extraction guards with `input_budget_chars(get_profile(...).num_ctx)` (`extraction.py:628`). Fix: skip (logged) over budget. |
| 4 | blind+edge | Downgrade leaves `clarification_answer` Sources that the older `SourceKind` can't read | low | patch | Migration 0032 `downgrade` never touches `intake_sources`; one-line `UPDATE … SET kind='note'`. |
| 5 | blind | A failed Record answer closes the form and loses the typed answer | medium | patch | `gap-inspector.tsx:315` closes on `"failed"` (copied from Mark sent, which has no typed text). Fix: close only on `"ok"`. |
| 6 | verify | Overview "questions sent" drops answered questions of open Gaps | medium | patch | `lib/overview.ts` `gapCounts` still filters `sent|unanswered` while `isSent` now includes `answered`. |
| 7 | edge | Gaps tab has no polling fallback while the stream is disconnected (spec: "polling stays as the fallback") | medium | patch | `gaps-list.tsx` ignores `useGapsEvents`' `connected`; only detection polling exists. |
| 8 | blind+edge | Up to three EventSources per page (badge, Gaps tab, Overview) plus Assessments, exhausting HTTP/1.1 per-origin connections | medium | patch | Each `useGapsEvents` call opens its own `EventSource` (`opportunity-events.ts`). Fix: one shared, ref-counted EventSource per Opportunity. |
| 9 | verify | Only the Record-answer write is covered for the `gaps.changed` frame | medium | patch | Pre-verified: one stream test (`test_gaps_answers.py:716`) through `questions._write`. |
| 10 | verify | `added`/`versioned` Requirement-change kinds untested | medium | patch | Pre-verified: only `pending` asserted (`test_gaps_answers.py:392`). |
| 11 | verify | 0032 downgrade untested | medium | patch | Pre-verified: no downgrade test, unlike `test_gaps_commands.py:628`. |
| 12 | verify | `countOpenGaps` and `GapsLiveRefresh` never run in tests; `countOpenGaps` duplicates `openGapCount` | medium | patch | Pre-verified: `pages.test.tsx:33` mocks it; no test imports `GapsLiveRefresh`. |
| 13 | blind | `gapAnswer()` in `lib/gaps.ts` is dead code with a misleading comment | low | patch | Exported, never called; deletion. |
| 14 | blind+edge+verify | An answered question on an open Gap (settles unticked) can't be re-answered or reopened | low | reject | Intent: "If it is unticked, the question becomes `answered` and the Gap stays `open`"; the Gap stays actionable (dismiss, Estimate Assumption). A settle-later command is new surface. Reported to the human. |
| 15 | blind | Confirm stamps UTC today, unlike Record answer's +1 day and the Source's upload date | low | reject | Intent: "Confirm … with `answered_on` set to today"; changing the date source is new design. |
| 16 | blind+edge | `answered_on` may precede `sent_on` | low | reject | Not in intent; same call as Story 4.6 triage #15 (past dates allowed). |
| 17 | blind | Reopen sends the question back to `sent` without its own trace event | low | reject | Intent: "reopen keeps `gaps.gap.reopened`"; the Gap event records the reopen. |
| 18 | blind | Sales reps can settle but not reopen | false | reject | Intent "Who" sets exactly this (answer with `GAP_QUESTION_SEND`, reopen keeps `GAP_EDIT`). |
| 19 | blind | Heavier Gaps reads (passage texts, per-Source change queries, layout `listGaps`) | low | reject | Demo scale (tens of Gaps); batching adds surface. |
| 20 | blind+edge | Answer's Requirement changes cover the whole Source (and older versions), not the passage | low | reject | Intent defines `requirement_changes_for_source(source_id)`; narrowing changes the spec. |
| 21 | blind | Identical answer texts dedupe onto an existing Source | low | reject | Intent Code Map accepts it ("identical bytes dedupe … that's accepted"). |
| 22 | blind | Injection label adds no extra confirmation step | low | reject | Intent asks for a warning label only. |
| 23 | blind+edge | Record answer 404 shows "suggestion gone" when the Gap has suggestions | low | reject | Rare (questions are never deleted); fix adds a parameter. |
| 24 | blind | Question export shows no answer text/date | low | reject | Not in intent (only the "Answered" label). |
| 25 | edge | Superseded/confirmed pairs stay "known", so a reopened question never gets them suggested again | low | reject | Unique (question, passage) by design; re-suggesting needs a status reset path. |
| 26 | edge | Suggestions on dismissed/converted Gaps reappear after a reopen | low | reject | They are still valid suggestions for a sent question; nothing changes status without a person. |
| 27 | edge | `insert_match` conflict still traces a suggestion | false | reject | Unreachable: `accept_answer_matches` takes `lock_opportunity` and reads `known_match_pairs` under it before inserting. |
| 28 | edge | A rejected text returns for a re-uploaded Source version (new passage id) | low | reject | Re-uploads of the same bytes are rare; text-level dedupe is new design. |
| 29 | blind | Missing tests list | low | reject | Covered by rows 9–12; the remaining items exercise rejected rows. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1/psa_test> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1/psa_test> uv run pytest` -- expected: all pass, none skipped (never the dev `psa` DB)
- `cd backend && uv run ruff format --check . && uv run python -m app.agents.manifest && git diff --exit-code -- app/agents/manifest.json` -- expected: no diff after the committed regen
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
