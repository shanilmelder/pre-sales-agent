# Epic 4 Context: Find the gaps before estimating

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Before anyone estimates, the platform finds the information that is missing. It raises ranked Gaps from expert Checklists and the Knowledge Base, and drafts a customer-ready Clarification Question for each one. The presales engineer reviews the Gaps, then edits and approves the questions. The presales engineer or sales representative exports them, marks them sent and records the answers. Each answer closes its Gaps and proposes updates to the related Requirements without overwriting human edits. This is the core of the product: Gaps that stay open later become Assumptions or Risks in the Estimate (Epic 8), so no Unknown is ever silently assumed away. The epic introduces the `gaps` module and the second agent, `clarification_agent`.

## Stories

- Story 4.1: Integration Types in scope and applicable Checklists
- Story 4.2: Deterministic Gaps from mandatory Checklist items
- Story 4.3: Detect Gaps and draft Clarification Questions with the Clarification Agent
- Story 4.4: Gaps tab with ranked Gap cards
- Story 4.5: Edit, merge, drop and approve Clarification Questions
- Story 4.6: Export Clarification Questions and mark them sent
- Story 4.7: Record answers and propose Requirement updates

## Requirements & Constraints

- **Gap content:** every Gap states why it matters (the estimate area it affects), cites its trigger (a Checklist item or a Knowledge passage), and carries an impact (High, Medium or Low) with a basis. Gaps are ranked by impact.
- **Mandatory items are deterministic:** every unanswered mandatory item in an applicable Checklist produces exactly one Gap, 100% of the time. No LLM output decides whether a mandatory Gap exists. A mandatory Gap can't be dismissed while its Checklist still applies (the UI hides Dismiss and the API rejects it). It can only be answered or, in Epic 8, converted.
- **Detection quality bar:** at least 80% recall against expert-identified Gaps and at most 20% irrelevant, on the `evals/gaps/` fixtures (`make eval-gaps`). Dismissals with reason "Not relevant" must be queryable as the live irrelevance measure.
- **Clarification Questions:** customer-ready plain language, grouped by topic. Lifecycle `drafted → approved → sent → answered | unanswered`, with the date of each change. Editing an approved question returns it to `drafted`. Only approved questions can be marked sent. "No answer" keeps the Gaps open and the question can still be answered later.
- **Exports** (copy, `.docx`, `.eml` draft) contain only customer-facing wording: no internal reasons, impact, Knowledge Source names or Evidence. The platform never sends anything to the customer.
- **Answers:** recorded manually or matched from a new Source. Only a human confirmation marks a question or Gap answered. An agent may only suggest ("Possibly answered", "Possible answer in Source …").
- **Sales representatives** see Gaps and status read-only, see only approved, sent, answered and unanswered questions, and may mark sent, mark No answer and record answers. They can't tag Integration Types, change impact, dismiss or reopen Gaps, or edit, merge, drop or approve questions: the UI hides these actions and the API returns 403.
- **Privacy and untrusted content:** no question or customer text in logs. Agents get only task-scoped data. Injection text in Sources or answers never changes any status, and affected suggestions carry `injection_suspected`.

## Technical Decisions

- **Ownership:** `gaps` owns Gap, Unknown and Clarification Question (`gaps_gaps`, `gaps_clarification_questions`). A Gap links to at most one question, and one question may cover several Gaps after a merge. `knowledge` owns Checklists and the catalogue. `intake` owns Requirements, Integration Type tags (`intake.tag_requirement_integration_types`; extraction never alters human-set tags) and `source_passage`. Cross-module access goes only through each module's `public.py`.
- **Gap shape:** title, why it matters (text plus an optional catalogue Integration Type or Work Package), trigger (`checklist_item` with Checklist ID, version and item ID, or a `knowledge_chunk` Evidence ref), impact with basis, `origin: mandatory_checklist | detected`, related Requirement refs with versions, status and `row_version`.
- **Lifecycle** (shared with Unknowns): `open → answered | converted | dismissed_with_reason`, plus reopen to `open`. It lives in `gaps/domain` and is unit-tested without a DB. `converted` is reached only through Epic 8's `estimates.convert_to_*` calling `gaps.mark_converted` in the same Unit of Work.
- **Detection job:** `gaps.detect_gaps` is enqueued in the same Unit of Work as `intake.accept_extraction` and as changes to scope, industry or tags. The deterministic mandatory step runs first, then the agent. The job is idempotent under reruns and concurrency (unique on Opportunity plus the stable Checklist item ID) and never reopens answered, converted or dismissed Gaps. A Gap whose Checklist no longer applies is kept and labelled "Checklist no longer applies"; only then can it be dismissed.
- **Agent:** `clarification_agent` is seeded in the registry and returns an `AgentResult` with candidates under `extensions.clarification_agent`. Inputs go in delimited data blocks. Model calls go through the ModelGateway outside any open Unit of Work. `gaps.accept_gap_detection` and `gaps.accept_answer_matches` check that every trigger, catalogue ref, Requirement version and `source_passage` resolves. An invalid result is retried up to the limit, then the job fails visibly while the mandatory Gaps stay. If the agent fails, mandatory Gaps fall back to the Checklist item's wording, labelled "from Checklist". Agent trace events use `actor_id = clarification_agent@<semver>`.
- **Answers:** stored as an Opportunity Source of kind `clarification_answer` through `intake.add_source`. They trigger incremental extraction (Story 2.7) focused on the answered Gaps' Requirements. Requirements with `locked_by_human` get pending changes through `intake.propose_requirement_change` and are never overwritten. New Sources trigger a `gaps.match_answers` job.
- **Locking:** Gap commands that change submission blockers (dismiss, reopen, answer) take `pg_advisory_xact_lock(opportunity_id)`.
- **Standard patterns:** mutations go through the Unit of Work with `identity.authorize`, `If-Match`/`row_version` (412 on mismatch) and a trace event in the same transaction. Trace event names follow `gaps.<entity>.<past_tense_verb>`: `gap.raised`, `gap.impact_changed`, `gap.dismissed`, `gap.reopened`, `gap.answered`, and `clarification_question.drafted`, `.edited`, `.merged`, `.approved`, `.exported`, `.sent`, `.answered`. Each has a catalogued payload model. Errors are problem+json with a stable `code`. Exports go through `platform.storage` with short-lived signed URLs. The Opportunity status `gaps_open` is derived by query and never stored.

## UX & Interaction Patterns

- **Visual reference:** the redesign v2 prototype (`ux-designs/.../imports/presales-agent-design-spec-standalone-v2.html`), which includes the question lifecycle screens (export, mark sent, answer). Where it disagrees with DESIGN.md or EXPERIENCE.md, those two documents win. The older `mockups/` are superseded. The Convert form belongs to Epic 8.
- **Gap rows** (padded list rows per the density token): sorted by impact (High first, mandatory first within a level). Each row shows a 3-segment impact bar filled in the impact colour (High blocker, Medium gap, Low neutral) plus the word, the title, the affected area, the trigger label, a "Mandatory" label where it applies and the question status pill. High-impact open Gaps get the blocker tint and a 3px blocker left edge. Dismissed Gaps are greyed at the bottom. Filters: Impact, Area and Question status, kept in the URL. Keys: `j`/`k`, Enter, `x` multi-select, `e` edit question, `c` new question, `4` opens the tab. Footer hint: "j / k move · x select · e edit question · ] inspector".
- **Inspector (420px right pane):** why it matters, the trigger and related Requirements as Evidence chips (clicking one opens the Checklist item or cited passage), impact basis, the question draft editable inline in a bordered textarea ("Edits are traced"), and history. The primary button follows the question state: Approve question, Mark as sent, Save answer (disabled until an answer is typed), Reopen. Bulk actions: **Approve N selected** and **Export questions**. Saves on blur with If-Match; `Esc` closes.
- **Dismiss** requires a reason ("Not relevant" or "Other"). Dismissed Gaps can be reopened with a reason. A question row shows "Dismissed" only as its Gap's status.
- **Gaps tab header:** applicable Checklists with their versions; "Detecting Gaps" with the static loader icon while detection runs; a notice for integration Requirements without an Integration Type; a weak-coverage info banner linking to Knowledge → Coverage. Empty state: "No Gaps" / "Gaps appear after Requirements are checked against Checklists." / Open Requirements.
- **Status pills:** Gap: Open (impact-coloured), Answered (check, resolved), Converted (arrow-right, neutral), Dismissed (ban, neutral). Question: Draft (pencil, neutral), Approved (check-circle, resolved), Sent (send, agent), Answered (resolved), No answer (gap). Colour is never the only signal.
- **Live updates:** over SSE, the list, the tab badge (open Gap count, blocker-tinted while blocking) and the Overview update without a refresh. The derived status shows "Gaps open". A polite `aria-live` region announces count changes. The command palette finds Gaps by title on Opportunities the user can access.
- **Copy:** glossary terms, counts and specific wording such as "Answered by customer, 12 Oct". No emoji or celebration copy. A 412 shows "Not saved: this question changed (412)" with Reload and View diff.
- **Open discrepancy:** EXPERIENCE.md says reopening returns the question to Draft. Story 4.7 says reopening an answered Gap returns its question to `sent`. Settle this in the story spec.

## Cross-Story Dependencies

- **Depends on Epics 1–2:** Unit of Work, authorization, trace, app shell, list row, inspector, status pill, command palette; job queue and worker, SSE stream, ModelGateway, agent contract and registry seed, `source_passage` Evidence, `intake.add_source`, Story 2.7 incremental extraction with `intake.propose_requirement_change`, injection flagging.
- **Depends on Epic 3:** catalogue Integration Types, `knowledge.public.find_applicable_checklists`, `knowledge.public.search` and `knowledge.public.get_coverage`.
- **Within this epic:** 4.1 → 4.2 (tags drive applicable Checklists) → 4.3 (the agent runs after the deterministic step) → 4.4 (renders Gaps and questions) → 4.5 → 4.6 → 4.7 (question lifecycle). Story 1.11 (saved views) depends on 4.4's Gap filters. Status: 4.3–4.7 are built; 4.1 and 4.2 are in the backlog, so mandatory-Gap determinism and tagging may still be missing from the code.
- **Later epics:** Epic 5 registers Unknowns through `gaps.register_unknown` (they appear in the Gaps tab). Epic 8 adds Convert through `gaps.mark_converted` and counts open Gaps and Unknowns in `estimates.get_submission_blockers`. Epic 7 reuses the Gap eval for the single-agent comparison. Epic 17.3 restyles the Gaps tab with no change in behaviour.
