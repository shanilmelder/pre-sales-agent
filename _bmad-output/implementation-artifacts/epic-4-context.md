# Epic 4 Context: Find the gaps before estimating

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Before anyone estimates, the platform finds the information that is missing. It raises ranked Gaps from expert Checklists and the Knowledge Base, and drafts a customer-ready Clarification Question for each one. The presales engineer reviews the Gaps, edits and approves the questions. The presales engineer or sales representative exports them, marks them sent and records the answers. Each answer closes its Gaps and proposes updates to the related Requirements without overwriting human edits. This is the core of the product: Gaps that stay open later become Assumptions or Risks in the Estimate (Epic 8), so no Unknown is ever silently assumed away. The epic introduces the `gaps` module and the second agent, `clarification_agent`.

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
- **Mandatory items are deterministic:** every unanswered mandatory item in an applicable Checklist produces exactly one Gap, 100% of the time. No LLM output decides whether a mandatory Gap exists. A mandatory Gap can't be dismissed while its Checklist still applies (UI hides Dismiss, API rejects). It can only be answered or, in Epic 8, converted.
- **Detection quality bar:** at least 80% recall against expert-identified Gaps and at most 20% irrelevant, on the `evals/gaps/` fixtures (`make eval-gaps`). Dismissals with reason "Not relevant" must be queryable as the live irrelevance measure.
- **Clarification Questions:** customer-ready plain language, grouped by topic. Lifecycle `drafted → approved → sent → answered | unanswered`, with the date of each change. Editing an approved question returns it to `drafted`. Only approved questions can be marked sent.
- **Exports** (copy, `.docx`, `.eml` draft) contain only customer-facing wording: no internal reasons, impact, Knowledge Source names or Evidence. The platform never sends anything to the customer.
- **Answers:** recorded manually or matched from a new Source. Only a human confirmation marks a question or Gap answered; an agent may only suggest ("Possibly answered", "Possible answer in Source …").
- **Sales representatives** see Gaps and status read-only, see only approved/sent/answered/unanswered questions, and may mark sent, mark No answer and record answers. They can't tag Integration Types, change impact, dismiss or reopen Gaps, or edit, merge, drop or approve questions: the UI hides these and the API returns 403.
- **Privacy and untrusted content:** no question or customer text in logs; agents get only task-scoped data. Injection text in Sources or answers never changes any status, and affected suggestions carry `injection_suspected`.

## Technical Decisions

- **Ownership:** `gaps` owns Gap, Unknown and Clarification Question (`gaps_gaps`, `gaps_clarification_questions`). A Gap links to at most one question; one question may cover several Gaps after a merge. `knowledge` owns Checklists and the catalogue; `intake` owns Requirements and `source_passage`. Cross-module access only through each module's `public.py`.
- **Gap shape:** title, why it matters (text plus optional catalogue Integration Type or Work Package), trigger (`checklist_item` with Checklist ID, version and item ID, or a `knowledge_chunk` Evidence ref), impact with basis, `origin: mandatory_checklist | detected`, related Requirement refs with versions, status, `row_version`.
- **Lifecycle** (shared with Unknowns): `open → answered | converted | dismissed_with_reason`, plus reopen to `open`. Lives in `gaps/domain`, unit-tested without a DB. `converted` is reached only via Epic 8's `estimates.convert_to_*` calling `gaps.mark_converted`.
- **Detection job:** `gaps.detect_gaps` is enqueued in the same Unit of Work as `intake.accept_extraction` and as scope or tag changes. Deterministic mandatory step first, then the agent. Idempotent under reruns and concurrency (unique on Opportunity plus stable Checklist item ID); never reopens answered, converted or dismissed Gaps. A Gap whose Checklist no longer applies is kept, labelled "Checklist no longer applies", and only then becomes dismissable.
- **Agent:** `clarification_agent` is seeded in the registry and returns an `AgentResult` with candidates under `extensions.clarification_agent`. Inputs go in delimited data blocks; model calls go through the ModelGateway outside any open Unit of Work. `gaps.accept_gap_detection` / `gaps.accept_answer_matches` validate that every trigger, catalogue ref, Requirement version and `source_passage` resolves; invalid results retry within limit, then fail visibly while mandatory Gaps stay. Agent trace events use `actor_id = clarification_agent@<semver>`.
- **Answers:** stored as an Opportunity Source of kind `clarification_answer` via `intake.add_source`, then trigger incremental extraction focused on the answered Gaps' Requirements. `locked_by_human` Requirements get pending changes via `intake.propose_requirement_change`, never overwrites.
- **Locking:** Gap commands that change submission blockers (dismiss, reopen, answer) take `pg_advisory_xact_lock(opportunity_id)`.
- **Standard patterns:** mutations go through the Unit of Work with `identity.authorize`, `If-Match`/`row_version` (412 on mismatch) and a trace event in the same transaction. Trace events are `gaps.<entity>.<past_tense_verb>` (e.g. `gap.raised`, `gap.impact_changed`, `gap.dismissed`, `gap.reopened`, `gap.answered`, `clarification_question.drafted/edited/merged/approved/exported/sent/answered`), each with a catalogued payload model. Errors are problem+json with a stable `code`. Exports go through `platform.storage` with short-lived signed URLs. Opportunity status `gaps_open` is derived by query, never stored.

## UX & Interaction Patterns

- **Visual reference:** `mockups/gaps.html` sets layout and density; where it disagrees with the UX spines (DESIGN.md, EXPERIENCE.md), the spines win. The mockup's Convert form is Epic 8, not this epic.
- **Gap card rows (32px):** sorted by impact (High first, mandatory first within a level). Each row: impact label with a neutral 1–3 segment bar, trigger label in meta type, "Mandatory" label where it applies, question status pill. Dismissed Gaps greyed at the bottom. Keyboard: `j`/`k`, Enter, `x` multi-select, `e` edit, `c` new question, `4` opens the Gaps tab.
- **Inspector (420px right pane):** full reason, trigger and related Requirements as Evidence chips (click opens the Checklist item or cited passage), impact basis, question draft in a bordered textarea, history. Saves on blur with If-Match; `Esc` closes.
- **Dismiss** requires a reason ("Not relevant" or "Other"); dismissed Gaps can be reopened with a reason.
- **Gaps tab header:** applicable Checklists with versions; "Detecting Gaps" with a running dot (reduced-motion fallback) while detection runs; notice for integration Requirements without an Integration Type; weak-coverage info banner linking to Knowledge → Coverage.
- **Status pills:** Gap: Open (circle-help, gap amber), Answered (check, resolved green), Converted (arrow-right, neutral), Dismissed (minus, neutral). Question: Draft, Approved, Sent (send, neutral), Answered (resolved), No answer (gap amber). Colour is never the only signal; resolved green is an icon tint, not a fill.
- **Live updates:** over SSE the list, tab badge (open Gap count) and Overview update without refresh; derived status shows "Gaps open"; a polite `aria-live` region announces count changes. The command palette finds Gaps by title on accessible Opportunities.
- **Copy:** glossary terms, counts and specific wording such as "Answered by customer, 12 Oct"; no emoji or celebration copy. A 412 shows Reload and View diff.

## Cross-Story Dependencies

- **Depends on Epic 1–2:** Unit of Work, authorization, trace, app shell, list row, inspector, status pill, command palette; job queue and worker, SSE stream, ModelGateway, agent contract and registry seed, `source_passage` Evidence, `intake.add_source`, Story 2.7 incremental extraction with `intake.propose_requirement_change`, injection flagging.
- **Depends on Epic 3:** catalogue Integration Types, `knowledge.public.find_applicable_checklists`, `knowledge.public.search`, `knowledge.public.get_coverage`.
- **Within this epic:** 4.1 → 4.2 (tags drive applicable Checklists) → 4.3 (agent runs after the deterministic step) → 4.4 (Gaps tab renders Gaps and questions from 4.2/4.3) → 4.5 → 4.6 → 4.7 (question lifecycle).
- **Later epics:** Epic 5 registers Unknowns via `gaps.register_unknown` (they appear in the Gaps tab). Epic 8 adds Convert via `gaps.mark_converted` and counts open Gaps and Unknowns in `estimates.get_submission_blockers`. Epic 7 reuses the Gap eval for the single-agent comparison.
