# Spine Pair Review

Reviewed: `DESIGN.md` (187 lines) and `EXPERIENCE.md` (211 lines), dated 2026-10-01, status `draft` (fast-path).
Checked against: the skill references (`design-md-spec.md` and the shadcn, mobile and editorial examples), PRD `prd-pre-sales-agent-2026-10-01/prd.md` (UJ-1..UJ-5, glossary, FR-1..FR-65, NFR-7/8), and `ARCHITECTURE-SPINE.md` (statuses table, AD-11, AD-16, AD-23, AD-24, AD-27, AD-28, AD-30).
`[ASSUMPTION]` tags were treated as intentional and not counted as findings. Mockups are still being rendered into `.working/`, so category 5 is a note only.

## Overall verdict

**Adequate. Not yet ready for story-dev.**

The pair is well shaped. It follows the canonical structure, keeps to the shadcn delta, every `{token}` reference resolves, every colour has a light and dark pair, and the four flows it includes are vivid and use the glossary. A consumer can extract the *happy path* of R1 cleanly.

It is not yet a complete contract, because most domain lifecycles in the architecture statuses table have only one or two states with a UI surface. The gaps fall into four groups:

- Several components are described in one spine but not the other.
- The status-pill vocabulary is referenced but never defined.
- The submit gate and the Baseline gate are treated as one.
- The review loop has no response path for the author.

A story-dev agent would have to invent these, and two agents would invent them differently. One targeted revision pass, mainly adding rows to State Patterns and Component Patterns plus a status vocabulary table, would raise this to strong.

| # | Section | Verdict |
| --- | --- | --- |
| 1 | Flow coverage | adequate |
| 2 | Token completeness | adequate |
| 3 | Component coverage | thin |
| 4 | State coverage | thin |
| 5 | Visual reference coverage | note only (mockups pending) |
| 6 | Bloat & overspecification | strong |
| 7 | Inheritance discipline | adequate |
| 8 | Shape fit | strong |
| 9 | PRD/architecture reconciliation | thin |

## 1. Flow coverage

**Verdict: adequate**

Extracted from the PRD (§2.3): UJ-1 (Ravi, R1), UJ-2 (Lena, R1), UJ-3 (Ravi, R1 with an R3 Negotiation variant), UJ-4 (Ravi, Scenarios, R3), UJ-5 (Sam, R1 capture with an R4 Calibration climax).
Found in EXPERIENCE.md Key Flows: Flow 1 = UJ-1, Flow 2 = UJ-2, Flow 3 = UJ-3, Flow 4 = UJ-5.

| UJ | Protagonist | Numbered steps | Climax | Failure path |
| --- | --- | --- | --- | --- |
| UJ-1 | yes (Ravi) | yes (7) | yes | yes (Security Agent timeout) |
| UJ-2 | yes (Lena) | yes (5) | yes | yes (412) |
| UJ-3 | yes (Ravi) | yes (3) | yes | **missing** |
| UJ-4 | — | — | — | **flow missing** |
| UJ-5 | yes (Sam) | yes (3) | yes, but diverges from the PRD | **missing** |

Findings:
- **[medium]** UJ-4 has no Key Flow. The IA mentions it only in one line ("R3 adds a Scenarios switcher", EXPERIENCE.md L48). Because there is no flow, the spine never states the R3 promises "Baseline never modified in place" and "compare side by side, then promote after commercial approval". (EXPERIENCE.md Key Flows.) *Fix:* add a short Flow 5 tagged R3 (create a Scenario from the Baseline, rerun only affected agents, compare side by side, promote through approval). Alternatively, add an explicit "UJ-4 deferred to R3 UX pass" line so consumers know the omission is deliberate.
- **[medium]** Flow 4's climax replaces the PRD's UJ-5 climax ("the Calibration report shows this integration type is underestimated across four projects") with a Decision Trace walk. That is a sensible R1-achievable climax, but the substitution is not stated, and the R4 Calibration suggestion ("accepts or overrides it") has no surface anywhere. (EXPERIENCE.md L205.) *Fix:* label the climax "R1 climax", and add an R4 variant line, as Flow 3 does for Negotiation, covering the Calibration report and the inline suggestion with accept or override.
- **[medium]** Flow 3 has no failure path. PRD FR-31 allows "escalating to a named reviewer", and AD-28 and the statuses table include Conflict `escalated`, but the flow never shows what Ravi sees after escalating or what the reviewer receives. (EXPERIENCE.md L193–199.) *Fix:* add "Failure: Ravi can't decide → Escalate to a named reviewer with a reason → Conflict shows `escalated` with the assignee → reviewer gets an Inbox item."
- **[medium]** Flow 4 has no failure or empty path. It doesn't cover Actuals not yet recorded, or a variance line whose Assumption link is missing. (EXPERIENCE.md L201–205.) *Fix:* add "Empty: no Actuals recorded for this Opportunity → Actuals tab shows the record or import action, and Reports excludes it with a count."
- **[low]** The UJ-1 edge case ("if the customer never answers a question, the Gap stays open and becomes a Contingency") is not walked. Flow 1 assumes every answer arrives. (EXPERIENCE.md L176.) *Fix:* add a sentence to Flow 1's failure block covering mark unanswered → convert to Contingency.
- **[low]** Flow 2 has Lena confirm which Assessments to rerun (L187), but PRD FR-38 says "the presales engineer confirms which to rerun" in R1. See §9 for the full effect. (EXPERIENCE.md L187.) *Fix:* align with FR-38 or record the decision as a deviation.

## 2. Token completeness

**Verdict: adequate**

Extracted from the DESIGN.md frontmatter:

- **colors:** 16 tokens (8 light/dark pairs: primary, primary-foreground, blocker, gap, resolved, agent, surface-sidebar, surface-inspector). All are hex, and all have dark pairs.
- **typography:** 8 roles.
- **rounded:** 4.
- **spacing:** 6 named tokens.
- **components:** 10 entries.

There are 25 distinct `{path.to.token}` references in the body. **All of them resolve.** No token is missing a light or dark pair, so there is no critical finding.

Contrast I computed (WCAG 2.x relative luminance):

| Pair | Ratio | Text AA 4.5:1 | Non-text 3:1 |
| --- | --- | --- | --- |
| primary `#4F5BD5` / white | 5.54 | pass | pass |
| primary-dark `#7C86E8` / primary-foreground-dark `#0E1030` | 5.66 | pass | pass |
| blocker `#DC2626` / white | 4.83 | pass | pass |
| blocker `#DC2626` / surface-sidebar `#F7F7F8` | 4.51 | borderline pass | pass |
| **gap `#D97706` / white** | **3.19** | **fail** | pass |
| **gap `#D97706` / surface-inspector `#FBFBFC`** | **3.08** | **fail** | pass |
| resolved `#16A34A` / white | 3.30 | fail (icon-only, so acceptable) | pass |
| all dark semantic tokens / near-black | 6.0–11.9 | pass | pass |
| surface-sidebar / white; surface-inspector-dark / near-black | 1.07 / 1.10 | n/a | below 3:1 |

Findings:
- **[high]** No contrast targets are stated anywhere in DESIGN.md. EXPERIENCE.md L130 defers visual contrast to DESIGN.md, which never addresses it. A consumer can't verify NFR-7 (WCAG 2.1 AA) for the brand-layer overrides. (DESIGN.md Colors.) *Fix:* add a contrast line to Colors: "Text and counts ≥ 4.5:1, icons and pill outlines ≥ 3:1, against background, card, surface-sidebar and surface-inspector in both themes." Include the verified ratios.
- **[high]** `gap` amber (`#D97706`) fails 4.5:1 for text in light mode (3.19 on white, 3.08 on the inspector surface). Yet `gap-badge.foreground` renders a count in this colour (DESIGN.md L103–105, L171). The count is 11–12px text, which is load-bearing: it shows blocker and gap counts in tab labels. (DESIGN.md frontmatter `gap`, Components "Blocker / gap badge".) *Fix:* darken light-mode `gap` to about `#B45309` (≈5.0:1 on white). Alternatively, keep amber for the icon only and render the count in `foreground`.
- **[medium]** Three visual treatments that EXPERIENCE.md depends on have no token: the Evidence span highlight in the source viewer (EXPERIENCE.md L77, which is Flow 2's key beat), the diff added/removed tint (DESIGN.md L176 "subtle background tint"), and banner styling (info, budget-stopped and submitted banners, EXPERIENCE.md L98–104). (DESIGN.md frontmatter `colors`.) *Fix:* add `highlight-evidence`, `diff-added`, `diff-removed` and a banner treatment (or state explicitly that banners use the shadcn `Alert` default), each with a dark pair.
- **[low]** `list-row-selected.background: 'shadcn accent'` and `evidence-chip.border: '1px shadcn border'` are free-text strings, not resolvable references (DESIGN.md L94, L112). They are readable, but a token resolver can't flatten them. *Fix:* write them as `'{shadcn.accent}'` with a note in the comment explaining the inherited namespace, or say explicitly that it is a "shadcn token name".
- **[low]** The Condition and Contingency distinction is committed as "icon + label, not colour alone" in `.memlog.md`, but DESIGN.md names no icons for it. Blocker and gap badges do name icons (`octagon-alert`, `circle-help`). (DESIGN.md Components.) *Fix:* name the two icons alongside the Assumptions Register spec.

## 3. Component coverage

**Verdict: thin**

| Component | DESIGN.md.Components (visual) | EXPERIENCE.md.Component Patterns (behaviour) |
| --- | --- | --- |
| Button (primary) | yes | n/a (shadcn) |
| List row | yes | yes |
| Status pill | yes | **missing** |
| Blocker / gap badge | yes | **missing** |
| Agent running dot | yes | **missing** (mentioned inside Agent run panel only) |
| Evidence chip | yes | yes |
| Inspector panel / Inspector | yes | yes (name differs) |
| Estimate grid | yes | yes |
| Diff view | yes | yes |
| Sidebar | frontmatter only | **missing** |
| Submission Blockers list | **missing** | yes |
| Agent run panel | **missing** | yes |
| Gap card | **missing** | yes |
| Conflict view | **missing** | yes |
| Assumptions Register | **missing** | yes |
| Review panel | **missing** | yes |
| Challenge form | **missing** | yes |
| Command palette | shadcn Command plus `{rounded.lg}` | yes |
| Toast | shadcn sonner | yes |
| Activity rail | width token only | **missing** (IA prose only) |
| Tab strip with count badges | **missing** | **missing** (IA prose only) |
| Source viewer (passage highlight) | **missing** | **missing** (Sources tab row only) |
| Banner | **missing** | **missing** (used in 4 State Patterns rows) |
| Status bar | **missing** | **missing** (used in State Patterns L103) |

Findings:
- **[high]** The status-pill vocabulary is a dangling reference. DESIGN.md L170 says "Pill vocabulary follows EXPERIENCE.md statuses", but EXPERIENCE.md has no status vocabulary section. Pills are the main state signal on every list. Without a table, each story will invent its own label, icon and colour mapping for the 9 state machines in the architecture statuses table. (DESIGN.md L170; EXPERIENCE.md.) *Fix:* add a "Status vocabulary" table to EXPERIENCE.md (or a Component Patterns row) mapping each domain status (Workflow Run, Task, Gap/Unknown, Clarification Question, Conflict, Finding, Estimate Version, Review Request, Opportunity lifecycle) to a pill label, an icon and a semantic token.
- **[high]** Seven behavioural components have no visual spec: Submission Blockers list, Agent run panel, Gap card, Conflict view, Assumptions Register, Review panel and Challenge form. Most are composed from shadcn primitives, but the spine doesn't say which, and several (the Conflict view's side-by-side layout, the Submission Blockers list as the Overview hero) are the product's signature surfaces. (DESIGN.md Components.) *Fix:* add a one-line visual spec per component (anatomy plus the primitives it composes), as the Drift example does for Focus card.
- **[medium]** The activity rail, tab strip with count badges, source viewer with highlighted passage, banner and status bar are used by flows and states but specified in neither spine. The status bar isn't part of the three-pane layout at all (DESIGN.md L151), yet State Patterns L103 places the reconnect indicator there. (EXPERIENCE.md L34, L39, L50, L98–104; DESIGN.md Layout.) *Fix:* add each to both Components sections, or remove the status bar and move the reconnect indicator to a named location (for example, the sidebar footer).
- **[medium]** Status pill, Blocker/gap badge, Agent running dot and Sidebar have visual specs but no behavioural row. For example: is a badge clickable, does it go to the filtered list, does the pill announce changes, and does the sidebar collapse with `[`? (EXPERIENCE.md Component Patterns.) *Fix:* add rows. The sidebar collapse is already in Responsive (L146), so reference it.
- **[low]** Component names drift between the spines: "Inspector panel" vs "Inspector", "Agent running dot" vs "running dot", "Blocker / gap badge" vs "blocker or gap count badge". (DESIGN.md L172–174; EXPERIENCE.md L34, L76, L78.) *Fix:* use the DESIGN.md names verbatim in EXPERIENCE.md.

## 4. State coverage

**Verdict: thin**

I walked every IA surface and workspace tab. States marked ✓ are present. States marked ✗ are expected but missing.

| Surface | Loading | Empty | Error | Domain states |
| --- | --- | --- | --- | --- |
| Inbox | ✓ (generic) | ✓ | ✗ | superseded ✓; overdue review reminder ✗; evidence/alternative requested ✗ |
| My / All Opportunities | ✓ | ✗ (new user, nothing yet) | ✗ | filter no results ✗; Opportunity lifecycle status vocabulary ✗ |
| Overview | ✓ | ✓ (no Sources) | — | waiting ✓, budget ✓, run queued ✗, run cancelled ✗, run completed ✗, Baseline set ✗ |
| Sources | ✓ | ✓ (via Overview) | **✗ upload rejected or parse failed** | extraction running ✓; source version ✗ |
| Requirements | ✓ | — | — | extracting ✓, pending change ✓, affected-Assessments flag after new Source (FR-7) ✗ |
| Gaps | ✓ | ✗ (zero Gaps) | — | weak coverage ✓; dismissed_with_reason ✗; question unanswered ✗ |
| Assessments | ✓ | ✗ (no run yet) | — | low confidence ✓; Finding overridden ✗; non-overridable Finding ✗; injection flag ✗ |
| Conflicts | ✓ | ✗ | — | escalated ✗; negotiating (R3) ✗ |
| Estimate | ✓ | **✗ (no Estimate Version yet)** | — | submitted ✓; in_review ✗; approved ✗; rejected ✗; superseded ✗; Baseline marker ✗ |
| Trace | ✓ | ✗ | — | — |
| Actuals | ✓ | ✗ (not yet delivered) | ✗ import errors | — |
| Knowledge | ✗ | ✗ | ✗ ingestion failure | stale source (FR-8) ✗ |
| Reports | ✗ | **✗ (empty for months after launch)** | — | — |
| Admin | ✗ | ✗ | ✗ | — |
| Command palette | — | ✗ (no matches) | — | — |
| Global | — | — | page-load failure ✗; session expired ✗ | 412 ✓, reconnect ✓, permission ✓ |

Findings:
- **[high]** The Estimate Version lifecycle is mostly missing. Only `submitted` has a state. `in_review`, `approved`, `rejected` and `superseded` have no treatment, and nothing in any spine shows which version is the **Baseline**: no badge, no version-switcher marker, no Overview line. The Baseline is the platform's core commitment object (FR-62, AD-26). (EXPERIENCE.md State Patterns L99; Component Patterns L81.) *Fix:* add a row per Estimate Version status, plus a Baseline marker in the version switcher and the Overview Estimate summary.
- **[high]** Estimate tab before any Estimate Version exists: the spines never say how the first Estimate Version comes into being (automatically at run completion, or by a user action), or what the tab shows before then. Every UJ passes through this transition. (EXPERIENCE.md IA L45; State Patterns.) *Fix:* add an empty state ("No Estimate yet. Run assessment to produce v1.") and state the creation trigger.
- **[high]** Source upload and parse failures have no state. AD-18 rejects files on size, extension allowlist and magic bytes, and parses them in a sandbox with time and memory limits. FR-4 lists 7 formats. A rejected or unparseable transcript in Flow 1 step 2 has no defined treatment. (EXPERIENCE.md State Patterns.) *Fix:* add "Source rejected" (inline at the drop zone, with the reason) and "Source parse failed" (the source row shows a failed pill, retry, and "this source contributed no Requirements").
- **[medium]** Workflow Run `queued` is missing. Under the architecture's single-GPU deviation ("Runs queue on one GPU"), runs may wait in the queue for a noticeable time, and with no state the run looks frozen. `cancelled` and `completed` have no treatment either. (EXPERIENCE.md Component Patterns L78; State Patterns.) *Fix:* add a "Queued, position N" pill on the run panel, a cancelled state ("Cancelled by [user]; completed results kept", per FR-63), and a run-complete summary.
- **[medium]** Task `timed_out` is shown as "failed: model timeout" (Flow 1, L181), but the architecture has a distinct `timed_out` status, and FR-19 routes it through a recovery policy. (EXPERIENCE.md L97, L181.) *Fix:* give `timed_out` its own pill label, or state that it renders as failed with the reason.
- **[medium]** Empty states are missing for My Opportunities, Gaps (zero Gaps: is that good, or a sign of weak coverage?), Assessments before the first run, Conflicts, Trace, Actuals before delivery, Command palette no-match, and Reports. Reports will be empty for months after R1 launch (PRD §6 note). (EXPERIENCE.md State Patterns.) *Fix:* add one row per surface, in the existing "Nothing waiting for you." voice.
- **[medium]** Knowledge and Admin have no states at all: no ingestion progress or failure, stale Knowledge Source (FR-8 12-month flag), loading or empty states. (EXPERIENCE.md IA L28, L30.) *Fix:* add at least ingestion running/failed, stale, and empty catalogue rows. Alternatively, mark Admin as "standard shadcn CRUD, states inherit the global rows" so the omission is a decision.
- **[medium]** Session expiry and page-level load failure are not covered. With SSO and bearer-token SSE (AD-16), token expiry mid-session breaks the stream and every save. (EXPERIENCE.md State Patterns.) *Fix:* add "Session expired" (re-auth prompt that preserves unsaved inline edits) and "Couldn't load [surface]" (problem+json `title` and a retry).

## 5. Visual reference coverage

**Verdict: note only (mockups pending in `.working/`)**

- EXPERIENCE.md Information Architecture has no "→ Composition reference: `mockups/…`. Spine wins on conflict." line, which both examples include. `.working/` is currently empty. Once the mockups land, add the reference line, and check that each mockup uses the component names and state rows above. This is not scored.

## 6. Bloat & overspecification

**Verdict: strong**

- Both spines are close to the size of the examples (DESIGN 187 lines vs 109–157; EXPERIENCE 211 vs 112–133), which is proportionate for a 9-tab workspace. The DESIGN.md body restates almost no token values; it cites `{tokens}` instead.
- The precise numbers it commits to (150 ms minimum skeleton, 5 s aria-live throttle, 60 s offline cut-off, 28px button) are the right kind of specificity for downstream consumers, not bloat.
- **[low]** The EXPERIENCE.md Foundation glossary sentence (L18) lists 16 terms and claims "Every term follows the PRD glossary exactly". The list adds nothing a consumer needs, and it is incomplete. (EXPERIENCE.md L18.) *Fix:* replace the list with "Terms follow PRD §3 verbatim".
- **[low]** The Inbox includes "mentions" (L24). No PRD FR defines mentions or comments, so this is a small scope invention. (EXPERIENCE.md L24.) *Fix:* remove it, or tag it `[ASSUMPTION]` and add it to Open Questions.

## 7. Inheritance discipline

**Verdict: adequate**

- **Sources resolve:** all three `sources` paths in the EXPERIENCE.md frontmatter resolve on disk (PRD, architecture spine, brief). DESIGN.md has no `sources` field, which matches the examples.
- **UJ names verbatim:** Flows 1–3 are verbatim. Flow 4 drops ", Head of Delivery,": "Sam finds out why a project overran" vs "Sam, Head of Delivery, finds out why a project overran". (EXPERIENCE.md L201.) Low.
- **Token references resolve:** yes, all 25.
- **Component names identical:** no. See §3, low.

Findings:
- **[medium]** The two spines give semantic colours different meanings. DESIGN.md L131 restricts `gap` amber to "open Gaps, Unknowns and unanswered Clarification Questions". EXPERIENCE.md also uses amber for "Waiting for you" (L96) and pending Requirement changes (L102). Separately, DESIGN.md defines pills as "a neutral outline with a coloured leading icon" (L170), while EXPERIENCE.md describes "an amber pill" and "a red pill" (L96–97), which reads as filled. (DESIGN.md L131, L170; EXPERIENCE.md L96–97, L102.) *Fix:* either widen the DESIGN.md amber definition to "needs human attention", or switch those states to `agent` or neutral. Reword EXPERIENCE.md to say "pill with amber icon".
- **[low]** Glossary drift in the UI copy: "run", "Run assessment" and "Agent run panel" stand in for **Workflow Run**; "Review" for **Review Request** (L100, L185); "Sources" tab for **Opportunity Sources** (a tab label is acceptable). (EXPERIENCE.md L78, L100, L185.) *Fix:* use "Workflow Run" in component names and states. Keep short labels only where the space constraint is stated.
- **[low]** The Evidence chip kinds in DESIGN.md L173 (requirement, source, knowledge, research, actual) don't map 1:1 to AD-13 `kind` (`source_passage`, `knowledge_chunk`, `research_snapshot`). (DESIGN.md L173.) *Fix:* add the mapping in parentheses so the frontend can switch on the API enum.
- **[low]** DESIGN.md L153 sets the minimum supported width at 1280px, while EXPERIENCE.md L147 defines a 1024–1279px best-effort tier. (DESIGN.md L153; EXPERIENCE.md L147.) *Fix:* say "1280px minimum for full support" in DESIGN.md.
- **[low]** The two spines handle unavailable actions differently. "Actions the user can't take are hidden" (L106), but the Review panel says "Approve is disabled if you authored the target" (L83). (EXPERIENCE.md L83, L106.) *Fix:* state the rule. For example: hidden for role permissions, disabled with a tooltip for rule-based blocks such as self-approval or a non-overridable Finding.

## 8. Shape fit

**Verdict: strong**

- DESIGN.md body order matches the canonical spec order exactly: Brand & Style → Colors → Typography → Layout & Spacing → Elevation & Depth → Shapes → Components → Do's and Don'ts. The frontmatter has every spec key (`name`, `description`, `colors`, `typography`, `rounded`, `spacing`, `components`). The extra `status`, `created` and `updated` keys are harmless.
- EXPERIENCE.md has every section the examples use: Foundation, Information Architecture, Voice and Tone, Component Patterns, State Patterns, Interaction Primitives, Accessibility Floor, Responsive & Platform, Inspiration & Anti-patterns, Key Flows. It adds Open Questions, which suits a draft.
- **[low]** The IA has no composition-reference line yet (see §5).

## 9. PRD/architecture reconciliation

**Verdict: thin**

These are user-facing capabilities in PRD FR-1..FR-65, NFR-7/8 or the architecture spine that have no UX surface or state, or a surface that contradicts the source.

Findings:
- **[high]** The submit gate and the Baseline gate are treated as one. The Submission Blockers list includes "pending Review" as a blocker and makes Submit primary when the list is empty (EXPERIENCE.md L75). But the Estimate Version lifecycle is `draft → submitted → in_review → approved`, and review is requested *after* submission (Flow 1 L179: "He submits and requests review"). FR-62 gates the **Baseline**, not submission, on approved reviews. AD-27 uses one `get_submission_blockers` for both, so the UI needs to show which gate each blocker applies to. As written, Flow 1 would show a "pending Review" blocker right after it reads "0 blockers". The "Set Baseline" moment also has no flow, state or blocked treatment. (EXPERIENCE.md L75, L179; ARCH AD-27; PRD FR-14, FR-62.) *Fix:* split the list into "Before submit" (Gaps, Unknowns, Assumptions, Conflicts, critical Findings) and "Before Baseline" (adds pending and approved Review Requests and policy approvals). Add a Set Baseline step to Flow 2's resolution and a "Baseline blocked" state.
- **[high]** AD-28 review decisions have no author-side outcome. The reviewer can choose `rejected`, `evidence_requested`, `alternative_requested` or `escalated` (Review panel L83), but nothing shows what the presales engineer sees or does next. There is no Inbox item type, no state on the Estimate Version or Assessment, and no response action (attach Evidence, propose an alternative, resubmit). The same applies to `escalated` from the new reviewer's side and to Review Request `cancelled`. (EXPERIENCE.md L24, L83, L100; ARCH AD-28; PRD FR-37.) *Fix:* add State Patterns rows for each decision as the author sees it, an Inbox item type per decision, and a response action per decision.
- **[high]** It is unclear who confirms the Challenge rerun, and who requests the next review. FR-38 (R1) says the platform suggests affected Assessments and *the presales engineer confirms* which to rerun. The Challenge form (L84) and Flow 2 (L187) let the challenger (Lena) confirm. Flow 2's climax also has Lena approve v3 without anyone creating a Review Request for v3, even though AD-28 marks the v2 request `superseded`. (EXPERIENCE.md L84, L187–189; PRD FR-38; ARCH AD-28.) *Fix:* either show "Challenge awaiting engineer confirmation" as an Inbox item for Ravi, or record the change as a deliberate PRD deviation. State whether a new Review Request to the same reviewer is created automatically when the version supersedes.
- **[medium]** Gap `dismissed_with_reason` (AD-23 lifecycle) and FR-12's "drop" and "merge" questions have no actions. FR-11's quality bar (≤20% of raised Gaps judged irrelevant) assumes the engineer can mark a Gap irrelevant. "Convert to Risk" is listed as an action (L41), but the Gap card only describes the Condition/Contingency form. (EXPERIENCE.md L41, L79.) *Fix:* add Dismiss (reason required), Merge questions and a Risk form (likelihood, impact) to the Gap card.
- **[medium]** FR-35 says engineers "adjust line items and Assumptions **with a reason**". The Estimate grid allows reason-less inline cell edits and ⌘Z undo (L81, L126). (EXPERIENCE.md L81, L126; PRD FR-35.) *Fix:* state where the reason is captured, for example one reason per edit batch when leaving draft, or a reason field in the inspector. Alternatively, record that draft edits are exempt and only version creation needs a reason.
- **[medium]** FR-29 override paths have no surface. The override form (person and reason) isn't specified. "Supply Evidence" as a way to clear a blocking Finding has no action. Mandatory security Findings that can never be overridden need a visible explanation, not a hidden action. FR-25's needs-human-review flag and AD-9's prompt-injection flag on a Finding have no UI either. (EXPERIENCE.md L42, L105–106.) *Fix:* add an Override form row (reason required, confirm dialog), an "Add Evidence" action, a "Can't be overridden: mandatory security policy" disabled state, and flag chips for needs-review and possible injection.
- **[medium]** FR-7 incremental intake: after a new Source is added, the platform flags which Assessments the changes affect, and in R1 the engineer chooses what to rerun. Flow 1 step 4 skips straight to "Run assessment" with no affected-Assessments prompt. (EXPERIENCE.md L176; PRD FR-7.) *Fix:* add an "N Assessments affected by new Source. Rerun selected?" state on Overview or Assessments.
- **[medium]** Opportunity creation and lifecycle. FR-1 requires customer name, products in scope, industry, target proposal date and collaborators. Flow 1 only "names the Opportunity", and there is no collaborator-management surface. The PRD lifecycle (intake, gaps open, assessing, in review, approved, delivered, closed) has no pill vocabulary, and there is no action to mark an Opportunity delivered or closed. Both are needed before Actuals (FR-49) and for FR-29's "Opportunity is closed" exit. (EXPERIENCE.md L25, L173; PRD FR-1, FR-2.) *Fix:* add a Create Opportunity dialog spec, a Collaborators section on Overview, the lifecycle in the status vocabulary, and Mark delivered and Close actions.
- **[medium]** Role-specific experiences are undefined for the sales rep (FR-64: add Sources and context, view approved questions, mark sent, record answers, *can't* edit Assessments, Estimates or Assumptions), the delivery manager (FR-49) and the admin. Only "actions are hidden" is stated, and Open Question 2 covers landing pages for reviewers only. (EXPERIENCE.md L106, L210.) *Fix:* add a short "Role views" table (landing page, visible tabs, editable objects) for each FR-58 role.
- **[medium]** Knowledge Base admin capabilities are an IA row only: FR-8 (register, tag, owner, last-reviewed, stale flag), FR-9 (Checklist authoring with mandatory items, versioning), FR-10 (coverage view) and FR-65 (catalogue, retired entries). The same is true of Admin: FR-56 (registry), FR-57 (tool permissions), FR-58 (users and roles), FR-59 (cost and observability) and FR-60 (evals). These are R1 scope. (EXPERIENCE.md L28, L30.) *Fix:* add a sub-table per surface (Knowledge, Admin) like the workspace tab table, or explicitly defer it to an Admin UX pass with "standard shadcn Table + Sheet CRUD".
- **[medium]** Review Request creation is underspecified. FR-37 allows a review of an Estimate Version *or specific Assessments* by *named* engineering, PM or security reviewers, and AD-28 targets `{kind: estimate_version | assessment}`. The UX only shows Estimate reviews ("request review"). FR-37 R1 reminders after N days also have no surface. (EXPERIENCE.md L45, L83; PRD FR-37.) *Fix:* add a Request review dialog (target, reviewer type, named reviewer) and an "Overdue" marker in the Inbox.
- **[medium]** Duplicate run start (FR-16 idempotency; AD-24 keys) has no defined UI behaviour when **Run assessment** is pressed while a run is active. FR-15's visible plan and its escalation of tasks with disabled or unavailable agents are also not surfaced. (EXPERIENCE.md L38, L78.) *Fix:* say that Run assessment is replaced by "View run" while a run is active. Add a "Plan" disclosure on the Agent run panel and a waiting-for-human item for uncovered tasks.
- **[low]** AD-16/AD-30 SSE: reconnect with `Last-Event-ID` replay is covered (L103). An SSE stream authorization failure (expired token, or access revoked mid-session) is not; see §4 session expiry. (EXPERIENCE.md L103.) *Fix:* add a stream-401 row that leads to re-auth, and a 403 row that leads to "You no longer have access".
- **[low]** FR-36 export and FR-49 Actuals import have no in-progress or failure states. Downloads use signed URLs (AD-16), and an expired link needs a treatment. (EXPERIENCE.md L45–46.) *Fix:* add export-preparing, import-validation-errors (per row) and link-expired rows.
- **[low]** Source versioning (FR-4) and run input pins (FR-63) are not visible. Evidence chips show a version (L77), but the Sources tab doesn't show source versions. (EXPERIENCE.md L39.) *Fix:* add a version label and history to the source viewer header.
- **[low]** NFR-7 and NFR-8 are covered: WCAG 2.1 AA, axe in CI, the shortcut toggle per WCAG 2.1.4, focus management, and Chrome/Edge desktop. The remaining NFR-7 risk is contrast (see §2).

## Mechanical notes

- **Files read:**
  - Skill references: `references/design-md-spec.md`, `assets/design-example-shadcn.md`, `assets/experience-example-shadcn.md`, `assets/design-example-mobile.md`, `assets/experience-example-mobile.md`, and `assets/design-example-editorial.md` (frontmatter).
  - Workspace: `DESIGN.md`, `EXPERIENCE.md`, `.memlog.md`.
  - Inputs: the PRD (all 588 lines) and `ARCHITECTURE-SPINE.md` (all 599 lines).
- **Token references:** I extracted the 25 distinct `{x.y}` references with a regex. All resolve to frontmatter keys. There are no `{token}` references in EXPERIENCE.md.
- **Contrast:** computed with the WCAG 2.x relative-luminance formula. The shadcn neutral `background` was taken as `#FFFFFF` (light) and about `#0A0A0A` (dark). Inherited shadcn tokens were not re-verified.
- **Source paths:** all 3 `sources` in the EXPERIENCE.md frontmatter resolve from the workspace directory. The brief was not read beyond confirming that it exists.
- **Visual references:** `.working/` and `imports/` were empty at review time.
- **Finding counts:** critical 0, high 10, medium 22, low 16 (48 total).
- **Spines:** not edited.
