# Sprint Change Proposal: adopt the 2026-10-21 UX redesign

Date: 2026-10-21
Workflow: BMad Correct Course
Change scope: **Major**
Status: **APPROVED for implementation on 2026-10-21.** All 18 proposals (P1-P18) approved by the product owner. Edits to the PRD, architecture, epics and UX spines are handoff work and are not yet applied.
Routed to: product manager and architect (P1-P7), then product owner or scrum master (P8-P18), then the developer agent (Story 17.1 first).
Source analysis: `_bmad-output/planning-artifacts/.correct-course-analysis.md` (evidence, impact and verbatim old text)
Document language: English. Personas are named by role.

---

## 1. Issue Summary

### Trigger

A stakeholder-driven UX redesign was adopted wholesale by the product owner (`.memlog.md`: "[ADOPTED] ... adopt the new redesign wholesale"). No single story triggered it. It is a cross-cutting change that:

- replaces the visual identity (dense 13px Linear-style, to roomy 14px card-based);
- restores two keyboard and viewport rules the redesign had omitted (the built code already implements them);
- renames the product to "Pre Sales Agent Framework";
- fixes seven contrast failures (for example the 1.52:1 input border);
- adds three in-scope features that have no PRD or architecture backing: **Knowledge Graph**, **Reports Pipeline and Cost tabs**, and the **Requirement confirmation status** (Unconfirmed, Confirmed, Needs review);
- adds about a dozen screens and behaviours never specified in `epics.md` (Settings card, Estimate lifecycle stepper, Findings table, Challenge dialog, Trace event Inspector, empty-state cards, Offline strip, Actuals table, Overview recomposition).

Issue type: new requirement emerged from stakeholders.

Problem statement: the planning set (PRD, architecture, epics) and roughly 60% of the built web UI no longer match the approved UX spines, and three new feature areas lack requirements, data model and stories.

### How it was discovered

The UX spines (`DESIGN.md`, `EXPERIENCE.md`) were revised on 2026-10-21 from the imported v1 and v2 prototypes. `EXPERIENCE.md` itself states under "Scope needing PRD backing" that Graph, Pipeline, Cost and the Requirement status have "no PRD or architecture requirement yet", and lists Open Questions 3-14 as unresolved. This run compared the spines with the PRD, the architecture spine, `epics.md`, 52 done story specs and the `web/` code.

### Evidence

- `.memlog.md` decisions of 2026-10-21 and `.working/redesign-v2-delta.md`.
- `epics.md` still cites the old identity: UX-DR1 (Inter 13px, radii 4/6/8, 32px or 28px rows, rail 300px), UX-DR6 (32px row), UX-DR10 (running dot), UX-DR25 (`mockups/*.html`), Story 1.5 title and ACs, and 32px or 28px rows in Stories 1.7, 3.1, 3.2, 4.4, 5.7, 6.1, 7.3, 9.2, 9.8 and 11.1.
- Built code (`web/src/app/globals.css`, `status-pill.tsx`, six `animate-pulse` running dots, JetBrains Mono, `h-row` used 49 times) implements the old tokens.
- Internal spine contradictions: the Estimate grid row says both "Inline cell editing" and "Cells are read-only"; the Review panel says "More menu is gone" while Story 9.3 and UX-DR16 still use More.
- Stale text unrelated to the redesign but found: `epics.md` Additional Requirements still says Auth0 RBAC is not used, which AD-15 (amended) and Story 1.9 reversed.

---

## 2. Impact Analysis

### Implementation baseline

- There is **no `sprint-status.yaml`** under `_bmad-output`. Status was derived from the 52 `implementation-artifacts/spec-*.md` files (all `done`), `deferred-work.md` and `git log`.
- Of the **77 Release 1 stories, 43 have a done spec** (several are demo slices with `[post-demo]` remainders) and **34 have none**. Releases 2-4 (Epics 11-16, 34 stories) are all backlog.
- No story is in progress. The working tree holds only UX spine edits.

### Epic impact (Epics 1-17)

| Epic | Status (stories with done spec) | Impact | Specifics |
| --- | --- | --- | --- |
| 1 Secure workspace | In progress: 1.1, 1.4-1.9 done; 1.2, 1.3 backlog | Modify + Add | Story 1.5 (done) carries the old tokens; superseded by Epic 17, not edited. Epic goal says "Linear-style app shell". 1.7, 1.8 cite 32px rows and mockups. 1.2 and 1.3 unaffected. |
| 2 Input to Requirements | In progress: 2.1-2.7 done; 2.8 backlog | Modify + Add | 2.6 confirm is a nullable `confirmed_at/by`; the three-state vocabulary needs a stored `needs_review`. New Story 2.9. 2.5 "running dot" wording changes. |
| 3 Knowledge Base | In progress: 3.1-3.3 done; 3.4, 3.5 backlog | Modify + Add | Graph builds on 3.4 and 3.5. 3.5 cell vocabulary changes (Ready, Partial, Missing). 3.4 denial banner made generic. New Story 3.6. |
| 4 Find the gaps | In progress: 4.3-4.7 done; 4.1, 4.2 backlog | Modify (light) | 4.4 bar colour and 32px rows; 4.3 running dot wording. No new stories. |
| 5 Multi-agent assessment | In progress: 5.1-5.3, 5.5, 5.7-5.9 done; 5.4, 5.6, 5.10 backlog | Modify | 5.7 rows and loader icon; 300px rail becomes the 420px pane Activity tab; 5.3 becomes the Findings table; severity vocabulary aligned to as built. |
| 6 Critic, Red Team, conflicts | In progress: 6.1-6.3, 6.5 done; 6.4, 6.6 backlog | Modify | 6.3 "Superseded by Assessment v2" tag; 6.1 "32px rows". |
| 7 Quality, cost, admin | In progress: 7.1, 7.6 done; others backlog | Modify | 7.5 Cost moves from Admin to Reports; 7.3 "32px rows"; Admin sub-tabs change (UX-DR21). |
| 8 Estimate and Register | In progress: 8.1-8.5, 8.7, 8.8 done; 8.6 backlog | Modify + Add | 8.2 empty state and edit model; 8.7 state pills and stepper; new Story 8.9 (Overview). |
| 9 Review, Baseline, Trace | In progress: only 9.8 done; others backlog | Modify (before build) | Cheapest epic to change: 9.3 visible buttons, 9.4 outcomes list, 9.5 Challenge dialog, 9.8 Trace Inspector. |
| 10 Actuals and reporting | Backlog (0 of 6) | Modify + Add | 10.1 Actuals table; 10.3 Reports sub-tabs; new Story 10.7 (Pipeline). |
| 11 Approvals, notifications (R2) | Backlog | Modify (flag only) | 11.1 "Settings → Notifications" conflicts with the v2 Settings card. Left [DECISION PENDING]. |
| 12 Pricing, proposals (R2) | Backlog | None | |
| 13 Connected systems (R2) | Backlog | Modify (flag only) | 13.4 "Connect Microsoft 365 in Settings" has no home in Settings. Left [DECISION PENDING]. |
| 14 Negotiation (R3) | Backlog | None | Inherits tokens. |
| 15 Scenarios (R3) | Backlog | None | Inherits version switcher and lifecycle card. |
| 16 Learning (R4) | Backlog | None | |
| **17 Redesign refit (new, R1)** | Not started | **Add** | Stories 17.1-17.4: tokens and primitives, shell and Settings and a11y, refit of built tabs, Opportunity list and Overview chrome. |

No epic is removed or redefined. Epic 1 can still be completed.

### Story impact

- **New stories:** 2.9, 3.6, 8.9, 10.7, 17.1, 17.2, 17.3, 17.4.
- **Modified stories:** 1.7, 1.8, 2.5, 3.1, 3.2, 3.4, 3.5, 4.3, 4.4, 5.3, 5.7, 6.1, 6.3, 7.3, 7.5, 8.2, 8.7, 9.2, 9.3, 9.4, 9.5, 9.8, 10.1, 10.3 (and R2 flags on 11.1 and 13.4).
- **Done stories touched by wording only:** 1.7, 1.8, 2.5, 4.3, 5.7 and others (P10). Story 1.5 receives only a superseded note. Done specs are left as history.
- **Dependencies:** 3.6 depends on 3.4 and 3.5; 10.7 on 8.6 and the status query; 8.9 on 8.6; 17.1 precedes every new UI story.

### Artifact conflicts

**PRD** (`prds/prd-pre-sales-agent-2026-10-01/prd.md`)
- No conflict with Vision, JTBD or success metrics. MVP stays achievable.
- Gaps: no Requirement confirmation state (FR-6); no FR for the Knowledge Graph; no FR for a Pipeline report (and the non-goal "not a CRM" needs a scope sentence); Cost content exists in FR-59 but location and roles change; FR-35 wording versus in-place draft edits; NFR-7 lacks the single-key switch, skip link and live region; product name still "working title".

**Architecture** (`architecture/architecture-pre-sales-agent-2026-10-01/ARCHITECTURE-SPINE.md`)
- AD-11 lacks `confirmation_status`.
- No graph, pipeline or cost read model; AD-1 forbids a new datastore, so these must be derived read models (new AD-33). Retrieval statistics need one new insert-only table without query text.
- Preferences storage and the UI mappings (version lifecycle, finding severity, question "Dismissed") are undocumented divergences.
- Capability map and Entity Ownership need rows.

**UX** (`EXPERIENCE.md`, `DESIGN.md`)
- Internal contradictions (Estimate grid row, More menu) and unanswered Open Questions.
- `mockups/` superseded.

**Other**
- `epics.md` UX-DR block and Epic 1 intro; derived `epic-N-context.md` files; `deferred-work.md`; stale Identity bullet; no `sprint-status.yaml`.

### Technical impact

- About **67 built `.tsx` files** use `h-row`, the type-role classes or `rounded-*`; 77 test files exist. A token swap in `globals.css` is cheap; the density change (fixed-height rows to padded rows), the pill anatomy and the removal of six `animate-pulse` dots touch components and tests.
- `web/src/lib/contrast.test.ts` reads `globals.css` and asserts WCAG pairs. It must be rewritten against the DESIGN.md contrast table and will fail on the first token swap (a useful guard).
- `ui/` has only six shadcn components; the redesign needs Select, Tabs, Tooltip, Toast, Table, Avatar, Skeleton, Switch, Sheet, Popover, DropdownMenu, Card, KPI tile and Stepper.
- **API client:** `npm run gen:api` already runs in CI (`.github/workflows/ci.yml`); regenerate after Stories 2.9, 3.6 and 10.7 add endpoints. No CI change needed.
- Backend: new `confirmation_status` column with backfill (migration), `knowledge.public.get_graph`, `opportunities.public.status_summary`, `knowledge_retrievals` table (later, with Story 5.4). `platform_model_calls` has no GPU-seconds column; Story 7.5 derives it from configured rates.
- No Storybook exists.

---

## 3. Recommended Approach

**Direct Adjustment**, with an MVP review used for **sequencing only**.

- Modify planning artifacts, add Epic 17 (refit) and feature stories 2.9, 3.6, 8.9 and 10.7 inside their epics, change the ACs of unbuilt stories now, and re-skin built screens incrementally.
- **Effort: Medium-High.** Token swap Low; density, pill and primitives across 67 files Medium; Graph and Pipeline Medium each; Reports and Cost High because Epic 10 is unbuilt.
- **Risk: Medium.** UI regression across 77 test files; Graph definitions are new.

### Sequencing (from the MVP review)

1. Epic 17 first: Story 17.1 (tokens and primitives) before any new UI story, then 17.2.
2. Stories already on the plan (3.4, 3.5, 4.1, 4.2, 8.6, 9.1-9.7, 10.1) are built directly on the new tokens.
3. **8.6, 9.x and 10.1 stay ahead of the Graph and Pipeline.**
4. 2.9, 8.9, 17.3 and 17.4 follow.
5. **Graph (3.6) and Pipeline (10.7) go last in R1.** They add no estimate-quality value (SM-1 to SM-7) and the PRD's R1 goal does not depend on them.

### Rationale

1. The change is a skin plus additive features on a modular monolith whose ADs (AD-1, AD-2, AD-10, AD-26) already absorb derived read models.
2. The cheapest moment to align is now: Epics 8 (mostly), 9, 10 and Stories 3.4 and 3.5 are unbuilt, so their ACs change at zero code cost.
3. Done behaviour (APIs, domain, queue, workflows) is unaffected; only the skin and a few behaviours change.
4. The three PRD-less features get requirements first (P1-P3, P5-P6), as `EXPERIENCE.md` itself requires.

### Alternatives considered

| Option | Effort / Risk | Verdict |
| --- | --- | --- |
| 1 Direct Adjustment | Medium-High / Medium | **Chosen** |
| 2 Rollback of done stories | High / High | Not viable. Discards verified work (43 stories with done specs) for a change that is only a skin. |
| 3 MVP review (cut Graph, Pipeline, part of v2) | Low / Low-Medium | Used for sequencing only. A scope cut contradicts the wholesale adoption by stakeholders. |

---

## 4. Detailed Change Proposals

All proposals have status **APPROVED**. Paths are relative to `_bmad-output/planning-artifacts/` unless stated. Amendments from the approval decisions are already applied to the NEW text.

### 4.1 PRD (`prds/prd-pre-sales-agent-2026-10-01/prd.md`)

#### P1. FR-6 and glossary: Requirement confirmation state (APPROVED)

Section §4.2 FR-6.

OLD:
> A presales engineer can add, edit, split, merge, delete and confirm Requirements. - Human edits are recorded in the Decision Trace and are never overwritten by later extraction runs.

NEW: the same two sentences, plus:
> - Every Requirement has a confirmation state: **Unconfirmed** (the initial state of an extracted Requirement), **Confirmed** (a person confirmed it; set automatically for a Requirement the person created) or **Needs review** (a Confirmed Requirement whose text changed through an accepted pending change, an edit by someone other than the confirmer, or an agent flag). An edit by the confirmer themselves keeps the Requirement Confirmed.
> - Confirmation state never blocks submission.
> - Changes of state are recorded in the Decision Trace.

Section §3 Glossary, **Requirement**. OLD: "...It is classified (functional, integration, data, security, non-functional, commercial) and linked to the source text it came from." NEW: append " It has a confirmation state (Unconfirmed, Confirmed, Needs review)."

Rationale: the built code already has Confirmed (`confirmed_at`); `deferred-work.md` holds the open "edit of a confirmed Requirement" rule; the Overview KPI "Requirements confirmed n of total" relies on the state; gives Story 2.9 an FR to trace to. The `[ASSUMPTION]` tag is removed (decision recorded).

#### P2. New FR-66 Knowledge Graph view [R1] (APPROVED)

Section §4.3 Knowledge Base, after FR-10.

OLD: FR-10 text ends "This shows where risk detection is weak."

NEW (added after it):
> #### FR-66: Knowledge graph. The roles that can edit Checklists (Story 3.4) and platform administrators can explore a graph of Products, Integration Types, Knowledge Sources and Checklists, with their links, search and type filters.
> - Each node shows its Coverage score (0 to 100, calculated deterministically from FR-8 and FR-9 data: Ready non-stale Knowledge Sources and active published Checklists for the product and Integration Type pair), its owner and last-reviewed date, and its status (Ready, Partial or Stale, Missing or Failed, Embedding).
> - Missing coverage is shown as a distinct link.
> - The same facts are available as tables (FR-10) so the graph is never the only route.
> - Retrieval statistics ('used by agents', 'last retrieved') are not part of the first slice and are shown only once agent retrieval is logged.

Also: §6 Release Plan R1 feature list add "4.3 (graph)"; §16 Assumptions Index add the FR-66 score definition.

Rationale: the Graph is in scope but has no FR; keeps AD-10 (deterministic score) and NFR-7 (non-graph alternative). "Designated experts" is replaced by the Checklist-editor roles plus administrators.

#### P3. New FR-67 Pipeline report; amend FR-59 and the Non-Goals (APPROVED)

Section §4.14 (after FR-50, or a new §4.18 Reports). ADD:
> #### FR-67: Pipeline report [R1]. The Head of Delivery and platform administrator can see Opportunities grouped by derived status and the Opportunities whose target proposal date is due soon.
> - Derived only from platform data (FR-2 status, target proposal date). It does not read or write CRM pipeline stages (§5).

Section §4.16 FR-59.

OLD: "A platform administrator can see per-Workflow-Run and per-Agent traces, latency, failures, retries, token use and model cost, linked by correlation ID. - Cost per Opportunity is reported (input to SM-C2)."

NEW: "A platform administrator can see ... (unchanged). The Head of Delivery can view the cost and usage summary read-only. - Cost per Opportunity is reported (input to SM-C2). - Usage is summarised per Agent as runs, tokens, compute time and failures."

Section §5 Non-Goals, first bullet. OLD: "**Not a CRM, PSA or project-management tool.** The platform links to these and does not replace them." NEW: append " The Pipeline report (FR-67) shows only platform-derived status and dates."

Rationale: Pipeline has no FR; Cost is already FR-59 but moves under Reports; scope guard against CRM overlap (HubSpot, Story 13.3). Viewer roles: Head of Delivery and platform administrator.

#### P4. Housekeeping: name, NFR-7, status (APPROVED)

Title block and §0. OLD: `title: "PRD: Agentic AI Presales Platform (pre-sales-agent)"` and "*Working title. Confirm.*" NEW: product name "Pre Sales Agent Framework" confirmed (2026-10-21 decision); keep the file path; update `updated:` and add a change-log line.

NFR-7. OLD: "The web UI meets WCAG 2.1 AA." NEW: "The web UI meets WCAG 2.1 AA. Single-key keyboard shortcuts can be turned off (WCAG 2.1.4), every screen has a skip link, and live changes are announced politely."

Rationale: closes the brand question and records the a11y behaviours the redesign makes concrete. FR-14 and FR-33 are intentionally not changed here; they change only if an uncovered Requirement becomes a submission blocker (open item).

### 4.2 Architecture (`architecture/architecture-pre-sales-agent-2026-10-01/ARCHITECTURE-SPINE.md`)

#### P5. AD-11 and Consistency Conventions: Requirement confirmation state (APPROVED)

AD-11 Rule bullet.

OLD: "Requirements carry `origin: extracted | human` and `locked_by_human`."

NEW: "Requirements carry `origin: extracted | human`, `locked_by_human` and `confirmation_status: unconfirmed | confirmed | needs_review` (with `confirmed_by`, `confirmed_at` while confirmed). Transitions live in `intake/domain`: unconfirmed to confirmed (person confirms; creating a Requirement sets confirmed); confirmed to needs_review (an accepted pending change, an edit by someone other than the confirmer, or an agent flag); needs_review to confirmed (a person re-confirms). An edit by the confirmer keeps the Requirement confirmed. Each transition appends an `intake.requirement.*` trace event."

Consistency Conventions, Statuses row: add "**Requirement confirmation:** `unconfirmed, confirmed, needs_review`." Migration: add the column, backfill `confirmed` where `confirmed_at IS NOT NULL`, else `unconfirmed`.

Rationale: the model has only nullable `confirmed_at/by` (`intake/adapters/models.py:199-201`); resolves the deferred decision; basis for Story 2.9.

#### P6. New AD-33: derived read models for Knowledge Graph, Pipeline and Cost (APPROVED)

ADD after AD-32:
> ### AD-33: Graph, Pipeline and Cost are derived read models. **Binds:** FR-10, FR-50, FR-59, FR-66, FR-67; AD-1, AD-2, AD-10, AD-26. **Prevents:** a graph database, duplicated status logic, and LLM-derived scores. **Rule:**
> - The Knowledge Graph is computed by `knowledge.public.get_graph(filters)` over `knowledge_*` tables; there is no graph store (AD-1). Nodes are Products (from tags), Integration Types, Knowledge Sources and Checklists; edges come from tags and Checklist scopes.
> - Coverage score and status are pure domain functions in `knowledge/domain` (AD-10).
> - Retrieval statistics come from an insert-only `knowledge_retrievals` table (chunk ID, agent ID, run ID, time; no query text, NFR-9) written by the ToolGateway search tool; until Story 5.4 and this table exist the graph omits those fields.
> - The Pipeline report reuses the single Opportunity status query (AD-26) through `opportunities.public.status_summary()`; it never duplicates the derivation.
> - Cost and usage read `reporting_*` views over `platform_model_calls` and workflow tables (Story 7.5); roles are enforced in the API (AD-15).

Entity Ownership table: add "Knowledge retrieval log: `knowledge`". Capability to Architecture Map: add "4.3 Knowledge graph (FR-66): `knowledge`, `web`: AD-14, AD-33" and "Reports: pipeline and cost (FR-59, FR-67): `reporting_*`, `opportunities`: AD-2, AD-26, AD-33".

Rationale: gives the three features an architecture home inside existing rules; flags the one new table.

#### P7. UI preferences, UX-to-domain mapping and version labels (APPROVED)

Add a "UI preferences" bullet under AD-16 (or Consistency Conventions):
> Theme, density and the single-key shortcut switch are per-browser preferences stored in the `psa_prefs` cookie read by the root layout (no server table, no localStorage), so server rendering paints the right theme. The single-key shortcut switch defaults to **Off**, with a first-run hint (the built code defaults On; Story 17.2 changes it).

Consistency Conventions, Statuses. ADD:
> UI mapping: the Estimate version lifecycle stepper (Draft, In review, Approved, Baseline) is derived from the Estimate Version status plus the Baseline pointer (`submitted` is shown as Draft-complete; the stepper is never a control). Finding severity values are `low | medium | high | critical` (as built). The UI may show 'Dismissed' on a Clarification Question row only as the status of its Gap. Estimate version labels are whole numbers (v1, v2, v3). Draft lines are edited in place (row_version plus a trace event), not as a new version per edit.

Decisions applied: (a) cookie, not localStorage; (b) shortcut default Off with first-run hint; (c) whole-number labels and in-place draft edits. All [DECISION PENDING] markers removed.

Rationale: records divergences between built code, spine and redesign so later stories do not re-decide them.

### 4.3 Epics and stories (`epics.md`)

#### P8. UX Design Requirements block: rewrite stale items (APPROVED)

- **UX-DR1.** OLD: "Implement the DESIGN.md token layer on top of shadcn/ui: the primary colour, the four semantic colours (blocker, gap, agent, resolved), sidebar and inspector surfaces, diff and blocker tints, light and dark pairs, Inter at 13px with the type roles, tabular figures, tight radii (4/6/8) and density tokens (32px or 28px rows, sidebar 220px, inspector 420px, activity rail 300px)." NEW: "Implement the DESIGN.md token layer on top of shadcn/ui: canvas, background, surface and surface-alt; primary, primary-tint, primary-text, link and ring; the four semantic colours with their tints (blocker, gap, agent, resolved) plus neutral; control borders on `border-strong`; light and dark pairs; Inter at 14px with the type roles (title 24/32, section 16/24, body 14/21, control 13, meta 12, eyebrow, KPI), tabular figures, no mono face; radii 6/8/10/12; card elevation; and density tokens (row padding 12 or 6px, rows about 56-72px, buttons about 38px, sidebar 220px or 64px collapsed, right pane 420px)."
- **UX-DR2.** OLD: "...a main pane, and a right pane (inspector or activity rail, `]` toggles)." NEW: "...a main pane, and one 420px right pane with Inspector and Activity tabs (`]` cycles closed, open, closed). Header with organisation switcher, Search button, Settings reached from the avatar button. Skip link as first tab stop. Offline strip." Keep the four responsive tiers.
- **UX-DR6.** OLD: "List row component: 32px, hover and focus row actions, ..." NEW: "List row component: padded rows per the density token (about 56-72px comfortable), hover and focus row actions, ...".
- **UX-DR10.** OLD: "...a running dot (reduced-motion fallback), ..." NEW: "...a static loader icon for Running (no pulse), model chip and token or time bar, ...".
- **UX-DR16.** OLD: "Review panel and author-side outcomes: Approve (disabled for the author) and Reject, with the rest under More." NEW: "...Approve (disabled for the author), Reject and Challenge, with Request evidence, Request alternative and Escalate as a second row of buttons; a Review outcomes list on the author's own request."
- **UX-DR17.** OLD: "Challenge form, plus a 'Confirm reassessment' item for the presales engineer (FR-38 R1)." NEW: "Single Challenge dialog (520px) with a required reason and Assessment toggle cards (Suggested, Optional); the owning presales engineer confirms from the same dialog before the run starts (FR-38 R1)."
- **UX-DR21.** OLD: "...Admin views (Agents with config history, Users and roles, Catalogue, Cost, Evals; ...)." NEW: "...Admin views (Users and roles, Agents with config history, Catalogue, Evals; ...)" and add "Knowledge Graph (nodes, filters, legend, node drawer)".
- **UX-DR22.** OLD: "Reports: variance table grouped by Integration Type, with drill-down to the Actuals tab and Assumptions. Calibration view in R4." NEW: "Reports: sub-tabs Estimate vs actual (variance by Integration Type, drill-down), Pipeline and Cost and usage; Calibration in R4."
- **UX-DR25.** OLD: "Visual references: `mockups/opportunity-overview.html`, `mockups/gaps.html` and `mockups/estimate.html`. The spines win on conflict." NEW: "Visual reference: `ux-designs/.../imports/presales-agent-design-spec-standalone-v2.html`. The spines win on conflict. The older `mockups/` are superseded."
- **Add UX-DR26 to UX-DR30:** Settings card; Estimate Version lifecycle stepper and version state pills; Findings table; Trace event Inspector; per-tab empty-state cards (copy in EXPERIENCE State Patterns); Offline strip and 412 inline alert; Actuals entry table; Submission pipeline and KPI tiles; Knowledge Graph.
- **Epic 1 intro (both occurrences).** OLD: "works inside the Linear-style app shell." NEW: "works inside the app shell."

Rationale: keeps the inventory true so later stories cite the right DRs. Decision applied: single 520px Challenge dialog where the owning engineer confirms.

#### P9. New Epic 17 "Redesign refit (visual identity and shell)" [R1] (APPROVED)

Add to the Epic List (Release 1) and the FR Coverage Map note: "no FR; UX-DR1-2, 4-6, 8, 10, 20, 23-24, 26-30; NFR-7, NFR-8". Order: 17.1 before any new UI story.

- **Story 17.1: Token layer and primitives.** Given `globals.css`, When the redesign tokens are applied, Then every colour, type, radius, spacing and shadow token equals the DESIGN.md front matter (light and dark), `border-strong` outlines inputs, secondary buttons, chips and the switch, and JetBrains Mono is removed. Given `contrast.test.ts`, When tokens change, Then it asserts every pair in the DESIGN.md contrast table (including the seven fixes) and fails CI otherwise. Given the Button, Status pill, Card, Input, Select, Tabs, Switch, Dialog, Table, Skeleton, Avatar and Tooltip primitives, When rendered, Then they match DESIGN.md Components (primary about 38px, secondary 32px, tint-filled pills, 12px cards, disabled opacity .4). Given a Running state, When shown, Then it is a static loader icon, and the six `animate-pulse` dots are removed with tests updated. Given the product name, When any page title renders, Then it reads "Pre Sales Agent Framework".
- **Story 17.2: App shell, Settings and accessibility behaviours.** One 420px right pane with Inspector and Activity tabs replacing the 300px rail; sidebar collapses to 64px with the 0.16s transition, organisation switcher, Search button and footer; Settings card (760px) with Theme and Density radio cards and the single-key switch with a visible On/Off label, opened from the avatar button and the palette command "Open Settings", header toggle also updates the saved preference; preferences stay in the `psa_prefs` cookie; **the single-key shortcut switch defaults to Off (the built code defaults On, so this story changes it) and a first-run hint explains how to turn shortcuts on**; skip link; polite live region announcing screen name; Offline strip with Retry (the 60 s state from Story 2.3); viewport tiers unchanged; axe has no violations.
- **Story 17.3: Refit built tabs to the redesign.** Per tab: Sources, Requirements, Gaps, Assessments, Conflicts, Estimate and Trace use padded rows, tint pills, card surfaces and empty-tab cards with the copy in EXPERIENCE State Patterns; 412 alerts use the inline alert; no behaviour change (existing tests pass with updated selectors).
- **Story 17.4: Opportunity list and Overview chrome.** List columns (Opportunity with customer, Status, Owner, Proposal date, Open items, Estimate), views All, Mine, Due in 14 days, Blocked; header with breadcrumb, owner and collaborator chips, due-date countdown, Submit and "Resolve N blockers" buttons. (Overview body is Story 8.9.)

Rationale: Epic 1 is mostly done and merged; a new epic avoids reopening done stories and gives the refit its own status and retrospective.

#### P10. Global AC edits in unbuilt and done stories (batch) (APPROVED)

Note: this batch edits **wording in some already-done stories (1.7, 1.8, 2.5, 4.3, 5.7 and others)**. The done specs under `implementation-artifacts/` stay untouched as history. **Story 1.5 receives only a superseded note**, not edited ACs.

- Story 1.7 AC: "in 32px list rows" to "in list rows (density token)". Story 3.1: "two groups of 32px list rows" to "two groups of list rows". Story 3.2: "in 32px rows" to "in list rows".
- Story 4.4: "in 32px rows sorted by impact" and "a neutral 3-segment bar" to "in list rows sorted by impact" and "a 3-segment bar filled in the impact colour (High blocker, Medium gap, Low neutral) plus the word".
- Story 5.7: "one 28px row per task ... and a running dot while active" and "The running dot is static ..." to "one row per task with an agent avatar, a Task status pill, elapsed time ... and a static loader icon while Running".
- Story 6.1: "lists them as 32px rows" to "lists them as list rows". Story 7.3: "in 32px rows" to "in list rows". Stories 9.2, 9.8, 11.1: "32px list rows" to "list rows".
- Stories 1.8, 4.4, 8.2 (`Given the visual reference mockups/...`): replace with "the redesign v2 prototype (UX-DR25)".
- Story 1.5 title "Linear-style app shell and design tokens": add the note "Superseded in visual identity by Epic 17 (redesign 2026-10-21); behaviour unchanged." Do not edit its done ACs.
- Story 2.5 AC "with a running dot" and Story 4.3 AC "with a running dot (reduced-motion fallback)": change to "with the loader icon".

Rationale: these literals cannot be built to as written without contradicting DESIGN.md. One mechanical review pass.

#### P11. Epic 2: Story 2.6 note and new Story 2.9 (APPROVED)

Story 2.6 (done): add the note "Confirmation state vocabulary is extended by Story 2.9." No AC change to done text.

New **Story 2.9: Requirement confirmation state (Unconfirmed, Confirmed, Needs review).** As a presales engineer, I want each Requirement to show whether I have confirmed it and whether it needs another look, So that I can see how much of the list I vouch for.
- Given an extracted Requirement, When it is created, Then `confirmation_status` is `unconfirmed` (FR-6, AD-11).
- Given an unconfirmed Requirement, When I press Confirm (or Confirm all), Then it becomes `confirmed` with confirmer and time and a trace event is appended.
- Given a Requirement I create, Then it starts `confirmed`.
- Given a confirmed Requirement, When an accepted pending change (Story 2.7) or an edit by someone other than the confirmer changes its text, or an agent flags it, Then it becomes `needs_review` and shows a gap-coloured "Needs review" pill with a triangle icon. When the confirmer edits it themselves, Then it stays `confirmed`.
- Given a `needs_review` Requirement, When I press Confirm, Then it returns to `confirmed`.
- Given the Requirements tab, Then each row shows the pill, group headers read "n · m confirmed", Low-confidence unconfirmed rows get an amber edge, and filters offer State.
- Given the Overview, Then the KPI "Requirements confirmed n of total" and the pipeline step "Requirements confirmed" read from this status, and confirmation never blocks submission.
- Given a migration, Then existing rows backfill `confirmed` where `confirmed_at` is set. Resolves the `[post-demo]` item in `deferred-work.md` on editing a confirmed Requirement.

#### P12. Epic 3: Story 3.4, Story 3.5 and new Story 3.6 Knowledge Graph (APPROVED)

Story 3.5. OLD ACs: "Then it shows a matrix ... each cell shows the count of Ready, non-retired Knowledge Sources and the count of active published Checklists" and "the cell is tinted amber and also reads 'None'". NEW: add "Each cell reads Ready, Partial or Missing with an icon and tint (Ready: both a Ready Source and an active Checklist; Partial: one of them or all Sources stale; Missing: neither), plus the counts." Add sub-tab order: Graph, Sources, Checklists, Coverage.

Story 3.4. OLD AC "other roles see Checklists read-only, and their write calls return 403". NEW: add the generic denial banner "You do not have permission to edit Checklists. Ask an admin for the right role." (no "Expert role" wording).

New **Story 3.6: Knowledge Graph.** Depends on 3.4, 3.5. As a user whose role can edit Checklists under Story 3.4, or a platform administrator, I want to see Products, Integration Types, Knowledge Sources and Checklists as a graph with coverage status, So that I can see where documentation is thin.
- Given Knowledge, Graph, When it loads, Then `knowledge.public.get_graph` returns nodes and edges from Source and Checklist tags and scopes, computed in Postgres with no graph store (AD-33).
- Given the canvas, Then it is 660px high on `graph-canvas` (always dark), nodes use the DESIGN.md node and status colours with a glyph and a text label, edges are solid for documented links and dashed amber for missing coverage.
- Given search and type filters with counts, Then filtering hides nodes and edges accordingly.
- Given a node, When selected, Then a 372px drawer shows type, owner, last reviewed, Coverage score and status pill, tabs Overview, Connections, Citations, a primary action (Edit checklist, Open source or View coverage) and Mark reviewed (for the owner or an admin, reusing 3.2).
- Given the Coverage score, Then it is a pure domain function with unit tests and boundary tests (FR-66, AD-10).
- Given a user who cannot use the canvas, Then the Sources table and Coverage matrix hold the same facts (NFR-7), nodes are keyboard-focusable and announce type, label and status.
- Given the first slice, Then retrieval statistics ("Used by agents", "Last retrieved", "Cited by") are not shown at all (not zero) until retrieval logging exists.
- Given axe, Then no violations.

#### P13. Epics 5 and 6: Assessments, Findings and Conflicts (APPROVED)

- Story 5.3 AC. OLD: "Findings as list rows with kind, severity, status pill, Evidence chips and a 'Low confidence' label with its basis where applicable". NEW: "a Findings table card with a severity summary ('1 Critical · 3 High · 2 Medium · 0 Low') and columns Severity (icon and label, Critical rows on the blocker tint), Type, Finding (a partial Finding adds 'Partial result · blocks submission until resolved'), Raised by (agent role) and Evidence (count). Finding statuses are Open, Resolved and Overridden; the Challenge, Override and Rerun actions live in the row inspector." Also change severity values `info | minor | major | critical` to `low | medium | high | critical` (as built).
- Story 5.7. OLD: "the right pane shows the activity rail (`]` toggles it)". NEW: "the right pane shows the Activity tab (`]` cycles it)". Add run metrics: tokens, model calls, tool calls and elapsed as KPI tiles, with the correlation ID, and the token bar turning gap-coloured at its limit.
- Story 6.3. OLD: "the resolved Conflict moves to the resolved section and stays readable with all positions". NEW: add "A Conflict resolved against an earlier Assessment version appears under Resolved with the tag 'Superseded by Assessment v2' and is never reopened."

Rationale: keeps the epics' vocabulary equal to the built code and the v2 delta.

#### P14. Epics 7, 10, 11, 13: Reports, Cost and Settings relocations; Actuals; new Story 10.7 (APPROVED)

- Story 7.5. OLD: "**Given** an admin on Admin → Cost". NEW: "Given an admin or the Head of Delivery on Reports → Cost and usage ... KPIs (runs, tokens, GPU seconds, cost) and a per-Agent table (runs, tokens, GPU seconds, failures)". Keep the per-run drill-down, budget alerts, and 403 for other roles. Remove Cost from Admin (UX-DR21).
- Story 10.3. OLD: "Then they see a variance table grouped by Integration Type ..." NEW: prefix "Reports has sub-tabs Estimate vs actual, Pipeline and Cost and usage. On Estimate vs actual they see KPIs (closed Opportunities, total variance, failed Assumptions), a variance table ... with a diverging bar and percent (red above +10%) and a main-cause link". Role line: Reports is visible in the sidebar to the Head of Delivery and platform administrator (the viewers of Pipeline and Cost, as in P3); other roles do not see it.
- Story 10.1. Add AC: "Given the Actuals tab, Then a table per Baseline line shows Line, Estimate h, Actual h (editable), Variance (server-calculated, amber when over, green when under) and Variance cause, with Import from file and Save Actuals; lines with no Actual read '—' and 'Not recorded' and are not counted in variance. Given no Actuals at all, Then the empty-tab card 'No Actuals recorded' with the action Record Actuals."
- **Two variance color rules are kept on purpose.** Actuals shows amber per line when over, because it is an entry screen where any overrun needs the engineer's attention. Reports shows red above +10%, because it is an aggregate view where only a material overrun is a flag. Both rules are written into the stories and `EXPERIENCE.md`.
- New **Story 10.7: Pipeline report.** As the Head of Delivery, I want to see Opportunities by status and which are due soon, So that I can see where the proposal workload sits.
  - Given Reports, Pipeline, When it loads, Then it shows KPIs, 'Opportunities by status' as bars with their counts as text, and a 'Due soon' table, built from `opportunities.public.status_summary` (AD-26, AD-33).
  - Given the status derivation, Then the report reuses the single status query and a test proves both agree.
  - Given roles, Then only the Head of Delivery and platform administrator can open it and others get 403.
  - Given 500 Opportunities, Then the API answers within 500 ms at P95 (NFR-1).
  - Given the PRD non-goal, Then it never reads or writes CRM stages (FR-67).
- Story 11.1 (R2). OLD: "**Given** Settings → Notifications ... a user turns an event type off for a channel". NEW: "[DECISION PENDING: v2 Settings has no notifications control; either add a Notifications section to the Settings card in R2 or make this an admin policy]". Stays pending.
- Story 13.4 (R2). OLD: "**When** I choose **Connect Microsoft 365** in Settings". NEW: "...in Admin → Integrations (R2) or an account section of Settings [DECISION PENDING: location]". Stays pending.

#### P15. Epics 8 and 9: Estimate surface, lifecycle, Overview and Review (APPROVED)

- Story 8.2, empty state. OLD: "it shows 'No Estimate Version yet. Run an assessment to draft one, or start from the template.' with **Run assessment** (primary) and **Start blank**". NEW: "it shows the empty-tab card 'No Estimate yet / Run Assessments to produce Estimate v1 from the confirmed Requirements.' with one primary action". **Start blank is dropped.**
- Story 8.2, edits. OLD: "**Given** a `draft` version **When** I edit a cell inline ... Then a reason is requested ...". NEW: "Given a `draft` version, When I edit a line from the Inspector's **Edit line** section (Engineer effort plus a required reason), Then the draft is changed in place with a `row_version` and a trace event. There is no 'Save as new version'. Version labels are whole numbers. Edit line is hidden on read-only versions."
- Story 8.7. Add AC: "Given the version switcher, Then each segment carries a state pill (Superseded, Baseline, Draft). Given the Estimate tab, Then a Version lifecycle card shows Draft, In review, Approved, Baseline as a read-only stepper with the sentence for the selected version (EXPERIENCE 'Version lifecycle')."
- New **Story 8.9: Overview recomposition.** Depends on 8.6.
  - Given the Overview, Then it shows four KPI tiles (Requirements confirmed with bar, Open Gaps by impact, Open Conflicts, current Estimate with role split); an 8-step read-only Submission pipeline (Sources added, Requirements extracted, Requirements confirmed, Gaps answered, Assessments run, Conflicts resolved, Estimate accepted, Review and Baseline) with states Complete, In progress, Blocked, Pending and a footer such as '2 of 8 steps complete · 3 steps blocked'; Needs you; the Submission Blockers card from `estimates.get_submission_blockers` (AD-27); Recent activity; Latest agent decision; Agent run.
  - Given any pipeline step, Then it links to its tab, updates live over SSE, and uses the same data as the blockers check, never a separate rule.
  - Given the pipeline, Then it is a status tracker, never a forced order.
- Story 9.3. OLD: "**Approve** and **Reject** are visible, while Request evidence, Request alternative and Escalate sit under **More** (Story 9.5 adds Challenge there)." NEW: "**Approve**, **Reject** and **Challenge** are visible, with **Request evidence**, **Request alternative** and **Escalate** as a second row of buttons."
- Story 9.4. Add AC: "Given the author's own Review Request, Then a Review outcomes list shows one row per decision (Approved, Challenged, rerun confirmed, Approved after rerun) with who, what, time and note."
- Story 9.5. New AC replacing the separate Confirm reassessment item: "Given Challenge, Then a single 520px dialog asks for a required reason and shows toggle cards for the suggested Assessments (Suggested pre-ticked, Optional unticked); the owning presales engineer confirms in the same dialog; the primary button reads 'Rerun N Assessments' and is disabled until a reason is typed and one Assessment is ticked." (matches UX-DR17 in P8.)
- Story 9.8. Add AC: "Given a selected trace row, Then the Trace event Inspector opens automatically with Payload (Event, Actor with agent version, Subject, Estimate Version, then Correlation ID and Model for an agent, or Reason and authorising action for a human), a Version comparison for an Estimate line edit, Evidence chips and the append-only note."

Rationale: these stories are unbuilt (except 8.2 and 8.7 partly), so change before build. The in-place edit decision keeps built behaviour of `spec-8-2-edit-estimate-hours.md`.

### 4.4 UX and other artifacts

#### P16. UX spines: consistency and decision log (APPROVED)

Artifacts: `ux-designs/ux-pre-sales-agent-2026-10-01/EXPERIENCE.md` and `DESIGN.md`.

- EXPERIENCE Component Patterns, "Estimate grid" row. OLD (two sentences in one cell): "Inline cell editing on draft versions only, saved on blur." and "Cells are read-only in the grid; a line is edited in the Inspector (see Estimate line edit)." NEW: keep only "Cells are read-only in the grid; a line is edited in the Inspector (see Estimate line edit)."
- EXPERIENCE "Review panel": the "More menu is gone" statement now matches Story 9.3 and UX-DR16 (P8, P15).
- EXPERIENCE Open Questions: record the decisions of this run (single-key default Off with first-run hint, cookie storage, whole-number version labels and in-place draft edits, Edit line hidden on read-only versions, single Challenge dialog owned by the engineer, Finding statuses Open, Resolved, Overridden, both variance colour rules, Graph and Pipeline and Cost viewers, no Start blank, generic checklist denial banner, Confirmation not blocking submission) and **remove the matching `[ASSUMPTION]` tags, including the "v3.1" and "Save as new version" wording**.
- DESIGN.md: add a note that `mockups/` are **superseded** and **stay in place, marked superseded, not archived**. No token changes. Validate the token table once against the Story 17.2 switch default.

Rationale: spines win on conflict, so their own contradictions must be gone before stories cite them.

#### P17. Derived artifacts, tests, docs (APPROVED)

1. **Epic context files.** Regenerate `implementation-artifacts/epic-N-context.md` for Epics 1, 2 and 3 (they restate "Inter 13px, radii 4/6/8, 32px rows") through the compile-epic-context step. Do not hand-edit.
2. **Contrast test.** `web/src/lib/contrast.test.ts`: rewrite against the DESIGN.md pairs (delivered with Story 17.1).
3. **API client.** Run `npm run gen:api` after Stories 2.9, 3.6 and 10.7 add endpoints (CI already regenerates).
4. **Identity bullet.** `epics.md` Additional Requirements. OLD: "Roles and Opportunity membership live in the platform's `identity` module, not Auth0 RBAC." NEW: "Auth0 RBAC manages roles and permissions (AD-15 amended; Story 1.9); Opportunity membership stays in the platform." (Unrelated stale text; fixed in the same pass.)
5. **Deferred work.** Add `deferred-work.md` entries (do not alter done specs): "[post-demo] Refit built screens to the 2026-10-21 redesign (Epic 17)" and "[post-demo] Remove the six `animate-pulse` running dots".

Rationale: prevents stale context files feeding future story drafts.

### 4.5 Sprint status

#### P18. Create `sprint-status.yaml` via bmad-sprint-planning (APPROVED)

No `sprint-status.yaml` exists. After this proposal is applied, run `bmad-sprint-planning`, seeded as:
- `done` for the 43 R1 stories with done specs;
- `backlog` for the 34 unbuilt R1 stories and all of Epics 11-16;
- `backlog` for new Stories 2.9, 3.6, 8.9, 10.7 and 17.1-17.4;
- Epics 1-9 `in-progress` (each has at least one unbuilt story), Epic 10 `backlog`;
- **Epic 17 first** in priority order; 17.1 blocks every new UI story.

Done stories stay done: the refit is new stories, not Story 1.5 moved back to review.

---

## 5. Implementation Handoff

**Scope: Major.** The PRD needs two new FRs, an amended FR and glossary change; the architecture needs a new AD, a data-model change and a new table; a new epic and four feature stories are added; about 67 built files need a refit.

### Sequence

| Step | Role | Work | Success criteria |
| --- | --- | --- | --- |
| 1 | Product manager and architect | Apply PRD edits P1-P4 and architecture edits P5-P7. | PRD has FR-66, FR-67, the FR-6 state rule, amended FR-59, NFR-7 and the confirmed name; architecture has AD-11 `confirmation_status`, AD-33, ownership and capability rows, and the UI preferences and mapping bullets. No [DECISION PENDING] markers remain for P7. FR and AD IDs are cited by the new stories. |
| 2 | Product owner or scrum master | Apply epics edits P8-P15; edit the UX spines (P16); handle derived artifacts (P17); run `bmad-sprint-planning` (P18). | `epics.md` contains no 32px or 28px row, running dot, Linear-style or mockup citation; Epic 17 and Stories 2.9, 3.6, 8.9, 10.7 exist with ACs; spines have no internal contradiction and no matching [ASSUMPTION] tags; epic context files regenerated; `sprint-status.yaml` exists with 43 done, Epic 17 first and the sequencing in section 3. |
| 3 | Developer agent | Start with Story 17.1, then 17.2, then the backlog stories in the section 3 order. | Token layer equals DESIGN.md; rewritten contrast test passes in CI; six pulse dots removed; page titles read the new name; shortcut switch defaults Off with a first-run hint; all existing tests pass with updated selectors; axe clean; API client regenerated after new endpoints. |

Process rule: Graph (3.6) and Pipeline (10.7) do not enter a sprint before 8.6, 9.x and 10.1.

---

## 6. Decisions and open items

### Decisions recorded in this run

| ID | Decision |
| --- | --- |
| All | P1-P18 APPROVED by the user. |
| P1, P5 | Confirmation never blocks submission. The confirmer's own edit keeps a Requirement Confirmed; an edit by someone else, an accepted pending change or an agent flag moves it to Needs review. |
| P2, P12 | Knowledge Graph viewers are the roles that can edit Checklists under Story 3.4, plus platform administrators ("designated experts" and "expert" removed). Retrieval statistics stay out of the first slice. |
| P7 | Preferences stay in the `psa_prefs` cookie, not localStorage. Single-key shortcut switch defaults Off with a first-run hint (Story 17.2 changes the built default of On). Estimate version labels are whole numbers; draft lines are edited in place (row_version and trace event), not as a new version per edit. |
| P8, P15 | Single 520px Challenge dialog (UX-DR17); the owning engineer confirms there. Story 9.5 matches. |
| P9 | New Epic 17, Stories 17.1-17.4. |
| P10 | Wording edits in some done stories (1.7, 1.8, 2.5, 4.3, 5.7 and others); only a superseded note on Story 1.5. |
| P11 | Story 2.9 added. |
| P13 | Finding statuses Open, Resolved, Overridden; actions in the row inspector. |
| P14 | Both variance colour rules kept (Actuals amber per line when over; Reports red above +10%) with the reason stated. Pipeline and Cost viewers: Head of Delivery and platform administrator. |
| P15 | Story 8.2 edits in place from the Inspector's Edit line section (Engineer effort plus required reason); no "Save as new version"; whole-number labels; Edit line hidden on read-only versions; empty Estimate state drops "Start blank". |
| P16 | Decisions recorded in EXPERIENCE.md Open Questions; matching [ASSUMPTION] tags removed ("v3.1" and "Save as new version" wording gone). `mockups/` stays in place, marked superseded, not archived. |
| P17 | All five items approved; epic context files are regenerated, not hand-edited. |
| P18 | `bmad-sprint-planning` runs after approval, seeded as in section 4.5. |
| Sequencing | Direct Adjustment; Graph and Pipeline last in R1; Epic 17 tokens first; 8.6, 9.x and 10.1 ahead of the Graph and Pipeline. |

### Remaining open items

1. **Notifications and Microsoft 365 connection settings location.** R2 Stories 11.1 and 13.4 stay [DECISION PENDING].
2. **Uncovered Requirement as a submission blocker** (AD-27, Stories 8.6 and 8.9). FR-14 and FR-33 would change with it.
3. **Single-organization assumption** behind the organisation switcher. If false, multi-tenancy (architecture "Deferred") reopens.
4. **Graph and Pipeline sequencing within R1.** They are last in R1; confirm at sprint planning whether they ship in R1 or a follow-up.
5. **Story 3.4 "Expert role" banner** is now settled as generic text ("You do not have permission to edit Checklists. Ask an admin for the right role."); listed here only so the redesign wording is not reintroduced.
