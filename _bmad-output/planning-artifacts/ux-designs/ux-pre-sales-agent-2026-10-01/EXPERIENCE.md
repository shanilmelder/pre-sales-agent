---
name: Pre Sales Agent Framework
status: final
created: 2026-10-01
updated: 2026-10-21
sources:
  - ../../prds/prd-pre-sales-agent-2026-10-01/prd.md
  - ../../architecture/architecture-pre-sales-agent-2026-10-01/ARCHITECTURE-SPINE.md
  - ../../briefs/brief-pre-sales-agent-2026-10-01/brief.md
  - imports/presales-agent-design-spec-standalone-v2.html
  - imports/presales-agent-design-spec-standalone-v1.html
---

# Pre Sales Agent Framework: Experience Spine

## Foundation

This is a desktop web application (Chrome and Edge; PRD NFR-8) built with shadcn/ui on Next.js and Tailwind (architecture AD-16). `DESIGN.md` is the visual identity reference. This spine defines behaviour. It is a **roomy, keyboard-capable workspace**, not a step-by-step wizard. The presales engineer can jump to any part of an Opportunity at any time, and the platform always shows what still blocks a submittable Estimate. The product name is **Pre Sales Agent Framework** (user decision, 2026-10-21). It closes the earlier brand question.

The visual and screen design is the 2026-10-21 redesign, adopted wholesale: [`imports/presales-agent-design-spec-standalone-v2.html`](imports/presales-agent-design-spec-standalone-v2.html) (an interactive prototype and component sheet; the first version is kept as `imports/presales-agent-design-spec-standalone-v1.html`, and `new-mockups/` holds the original file). **v2 added the previously missing screens:** Settings, Trace detail, Findings, Actuals entry, the Estimate Version lifecycle, Challenge and review outcomes, the Gap question lifecycle (export, mark sent, answer), the 412 conflict messages, the superseded Conflict list, per-tab empty states and Offline. **The spines win on conflict.** The three mockups in `mockups/` predate the redesign and are superseded visually. They are kept, not deleted, for layout history only.

Every term follows the PRD glossary exactly: Opportunity, Requirement, Gap, Clarification Question, Assessment, Finding, Evidence, Assumption (Condition or Contingency), Unknown, Conflict, Estimate Version, Baseline, Review Request, Challenge, Decision Trace and Actuals. Live updates arrive over SSE (AD-30), so no screen needs a manual refresh except after a concurrent-edit conflict.

**Scope with PRD backing.** The redesign introduced three things that are in scope by user decision. They now have requirements: the Knowledge **Graph** tab (PRD FR-66), the Reports **Pipeline** tab (FR-67) and **Cost and usage** tab (FR-59), and the Requirement **Confirmed / Unconfirmed / Needs review** status (FR-6). Architecture AD-33 holds the derived read models for the Graph, Pipeline and Cost, and AD-11 holds the confirmation state. They are specified below.

## Information Architecture

| Surface | Reached from | Purpose | Release |
| --- | --- | --- | --- |
| Inbox | Sidebar / `g i` | Review Requests assigned to me, Challenges on my work, runs waiting for my input, and mentions. Two panes: list and detail | R1 |
| My Opportunities | Sidebar / `g m` (default landing page) | Opportunities I own or collaborate on. Table with status, owner, proposal date, open items and Estimate. Views: All, Mine, Due in 14 days, Blocked | R1 |
| All Opportunities | Sidebar / `g a` | Every Opportunity I can access, with filters (status, owner, product, date) | R1 |
| New Opportunity | "New Opportunity" button / `c` on a list | Create form with optional import from a file | R1 |
| Opportunity workspace | Any Opportunity row | The working surface. Tabs below | R1 |
| Knowledge | Sidebar / `g k` | Sub-tabs Graph, Sources, Checklists, Coverage (FR-8 to FR-10, FR-65, FR-66). The Graph is for platform administrators and the roles that can edit Checklists | R1 |
| Reports | Sidebar / `g r` | Sub-tabs Estimate vs actual (FR-50), Pipeline (FR-67), Cost and usage (FR-59); Calibration (R4). Reports is visible only to the Head of Delivery and platform administrator | R1 / R4 |
| Admin | Sidebar (admin role) | Sub-tabs Users and roles, Agents, Catalogue, Evals; R2 adds Approval policies and Integrations | R1 / R2 |
| Command palette | `⌘K` / `Ctrl+K` anywhere, or the sidebar Search button | Navigate and run actions | R1 |
| Settings | Avatar button in the sidebar footer, or the command palette ("Open Settings") | A single card with Theme (System, Light, Dark), Density (Comfortable, Compact) and a Single-key shortcuts switch (default Off, with a first-run hint). Saved in this browser (the `psa_prefs` cookie). Notifications and roles are managed by an admin, not here | R1 |

**Shell.** The sidebar is 220px and collapses to 64px (`[` or the "Collapse sidebar" button). Top to bottom: an organisation switcher, a Search button (`⌘K`), the six navigation items (Inbox shows an unread count badge), then a footer with Keyboard shortcuts (`?`), Collapse sidebar (`[`) and the user card (an avatar button that opens Settings, role, theme toggle). Non-Opportunity pages have a header with a title, a one-line subtitle, one primary action and a right-pane toggle. Page header actions: Opportunities, New Opportunity; Inbox, Mark all read; Knowledge, Add source; Reports, Export; Admin, Invite user; Settings has no primary action. The Opportunity header has a breadcrumb (`All Opportunities / title`), the title, the derived status pill, owner and collaborator chips, the proposal date with a day countdown, a **Submit** button (disabled until the Submission Blockers card shows 0 blockers to submit, then primary) and a **Resolve N blockers** primary button that jumps to Overview (hidden when ready).

**Opportunity workspace tabs.** Each is reached with the `1`–`9` keys. Counts show on Sources, Requirements, Gaps and Conflicts, and turn red on Gaps and Conflicts while they block:

| Key | Tab | Shows | Main actions |
| --- | --- | --- | --- |
| 1 | Overview | KPI tiles, Submission pipeline, Needs you, Submission Blockers, Recent activity, Latest agent decision, Agent run | Run assessment, open blocker, Resolve, Cancel run |
| 2 | Sources | Dropzone, Sources list with status, version and adder, source viewer with highlighted passages | Add source, paste text, view passage, download original |
| 3 | Requirements | Requirements grouped by category with Evidence, confidence, origin and confirmation state; pending changes card | Confirm, edit, split, merge, delete, create, accept or reject pending change |
| 4 | Gaps | Gaps and Unknowns ranked by impact; Clarification Questions with status | Edit question, approve, export, mark sent, record answer, convert to Assumption or Risk, dismiss |
| 5 | Assessments | Run header, run metrics, one task card per Specialist Agent, Critic and Red Team, results so far, and a **Findings** table (severity, type, finding, raised by, Evidence count) with a severity summary | Challenge, override (where policy permits), rerun selected, start new run, cancel run |
| 6 | Conflicts | Open Conflicts with side-by-side positions and Evidence, then a **Resolved** list (how it was resolved, and a tag such as "Superseded by Assessment v2") | Choose position, enter other, escalate; accept or reject Negotiation proposal (R3) |
| 7 | Estimate | Version switcher with a state pill per version, the **Version lifecycle** card, Estimate grid, Assumptions Register, Risks, diff view | Edit line (in the Inspector, with a reason, saved to the draft in place), accept Assumption, submit, request review, set Baseline, export |
| 8 | Trace | Append-only Decision Trace timeline filtered by subject; selecting an event opens its detail (payload, version comparison, Evidence) in the Inspector | Filter, select an event, open subject, compare versions |
| 9 | Actuals | A table per Estimate line: estimate hours, actual hours, variance and variance cause; empty lines read "—" and "Not recorded" | Enter Actuals by line, import from file, Save Actuals |

R2 adds a **Proposal** tab. R3 adds a **Scenarios** switcher in the Estimate tab header.

**Overview composition (top to bottom).** (1) Four KPI tiles: Requirements confirmed (n of total with a bar), Open Gaps (by impact), Open Conflicts, and the current Estimate (hours, role split, source run). (2) The **Submission pipeline**, an 8-step read-only progress view: Sources added, Requirements extracted, Requirements confirmed, Gaps answered, Assessments run, Conflicts resolved, Estimate accepted, Review and Baseline. Each step shows a state (Complete, In progress, Blocked, Pending) and a one-line reason, with a footer such as "2 of 8 steps complete · 3 steps blocked". (3) **Needs you**, the items waiting on the user with a count. (4) **Submission Blockers**. (5) **Recent activity** with an Open Trace link. (6) **Latest agent decision**: headline, Reasoning bullets, Evidence chips, proposed next steps, priority and confidence, with Approve question and Open Gap. (7) **Agent run**: the task table with Cancel run. Needs you overlaps the Inbox by design; it shows only items for this Opportunity.

→ Visual reference: [`imports/presales-agent-design-spec-standalone-v2.html`](imports/presales-agent-design-spec-standalone-v2.html) for every surface above, including the v2 additions. The older layout mockups remain at `mockups/opportunity-overview.html`, `mockups/gaps.html` and `mockups/estimate.html`. They illustrate the earlier information layout only and are superseded visually by the redesign.

**Right pane.** One 420px pane with **Inspector | Activity** tabs. It is closed by default. Selecting any row (Requirement, Gap, Finding, Assumption, Estimate line, Source, Conflict, trace event) opens the **Inspector** (on the Trace tab the pane opens by itself when an event is selected) with its full detail, Evidence and history. `Esc` closes it. **Activity** is a live feed of agent task progress and trace events. `]` cycles closed, then open, then closed. The right pane is empty-state text when nothing is selected: "Select a gap or estimate line to see its details."

Dialogs stack one level deep at most. Destructive or irreversible actions (submit, set Baseline, override, cancel run) use a confirm dialog. Everything else is inline.

## Voice and Tone

The voice is plain, specific and engineering-literate. Microcopy uses glossary terms and counts, and never reassures without cause.

| Do | Don't |
| --- | --- |
| "3 blockers before you can submit" | "Almost there! 🎉" |
| "Red Team: ERP custom fields — no evidence the connector supports them" | "Potential issue detected" |
| "Engineering Agent failed: model timeout after 3 retries. Retry or skip." | "Something went wrong" |
| "Answered by customer, 12 Oct" | "Gap resolved successfully ✓" |
| "This Estimate Version is submitted and can't be edited. Create a new version?" | "You can't do that" |
| "Low confidence — 2 of 5 integrations lack documentation" | "AI is unsure" |
| Agents are named by role ("PM Agent"), never personified | "Hi, I'm your PM assistant!" |

Agents have a sparkles icon and role initials as their identity. They have no first names, no chat voice and no first-person copy.

## Component Patterns

These are behavioural rules. Visual specs are in `DESIGN.md.Components`.

| Component | Use | Behavioural rules |
| --- | --- | --- |
| List row | All lists | `j`/`k` move selection, `Enter` opens the inspector, `x` multi-selects, and row actions appear on hover or focus. Lists are paginated or virtualised; there is no infinite scroll. The Gaps footer hint reads "j / k move · x select · e edit question · ] inspector". |
| Opportunity list | My / All Opportunities | Columns: Opportunity (title and customer), Status pill, Owner, Proposal date, Open items ("3 gaps · 2 conflicts", amber or red when non-zero), Estimate (hours and version, "v4 Baseline", or "No estimate"). Views All, Mine, Due in 14 days, Blocked, and filter dropdowns. Loading shows a 4-row skeleton. Empty reads "No Opportunities yet. Create an Opportunity from a customer email, transcript or RFP. The first file becomes its first Source." |
| New Opportunity form | New Opportunity | "Import from file" fills empty fields and the file becomes the first Source. Fields: Customer name, Title (optional, defaults to the customer name), Products in scope (one per line, up to 20), Industry, Target proposal date. Create Opportunity and Cancel. |
| KPI tile | Overview, Reports | A label, a number, a sub-line, and a link to the filtered tab where relevant. |
| Submission pipeline | Overview | A status tracker, not a forced flow. Every step links to its tab. State comes from the same data as the blockers check (AD-27) and updates live. |
| Submission Blockers card | Overview | Derived from the platform's single blocker check (AD-27). It always shows two groups. **Blockers to submit:** open Gaps and Unknowns, unaccepted Assumptions, open Conflicts, uncovered Requirements, and critical Findings without an override. Each row names its type, links straight to the subject with an action (Open Gaps, Resolve, Add line, Open Estimate), and disappears live when resolved. **Blockers to Baseline:** Review Requests that are pending, rejected or challenged on a submitted version, plus any open Conflicts and uncovered Requirements carried forward from the draft, shown as information with no action. When the submit group is empty, **Submit** becomes primary. When the Baseline group is empty, **Set Baseline** becomes primary. When both are empty the card reads "0 blockers — ready to submit" with a green check. `[ASSUMPTION]` whether uncovered Requirements are a blocker type in AD-27 and whether the Baseline group repeats draft items. |
| Needs you | Overview | Lists items waiting on this user: a task paused for a decision, Conflicts needing a decision, unconfirmed Requirements, and Review Requests. Each has a state pill and an action. A footer shows the count in the queue and the number resolved today. |
| Inspector | Right pane | Shows the subject's fields, Evidence chips, version history and actions. Edits save on blur with `If-Match`. Has an "Open in tab" link. Focus moves into it when it opens. |
| Evidence chip | Findings, Requirements, Assumptions, Proposal claims, Gaps | Label such as `S2 · file name` or a Checklist item ID. Clicking it opens the cited passage in the Inspector with the span highlighted, and a note naming which Requirements cite the passage. Shows the version. A broken or superseded reference is shown struck through with a "superseded" label. The kind (requirement, source, knowledge, research, actual) is named in the chip label. |
| Agent content | Overview, Gaps, Assessments, Estimate Basis | Agent output sits on an indigo tint with a sparkles icon and a role label including confidence. Human content stays on the plain surface. Every agent output is a proposal with Evidence. |
| Agent decision card | Overview | Shows the headline, the Reasoning, Evidence, proposed next steps, priority and confidence. Actions open the related Gap or approve the drafted question. Nothing is applied automatically. |
| Agent run table | Overview, Activity, Assessments | One row per task: agent avatar, role, status pill, elapsed time, a one-line detail. A running task shows the loader icon. A failed task shows its reason with **Retry** and **Skip**; partial results are kept and labelled "partial". A waiting-for-human task shows **Resolve** and **Open Gap**. A queued task shows its position. Cancelling a run asks for confirmation. |
| Assessments tab | Assessments | Run header ("run 2", started time, inputs: Sources, Requirements and agent config versions), counters, run metrics (tokens, model calls, tool calls, elapsed, correlation ID, cost), a task card per agent with a model chip and "Local" or "Hosted" label, and Results so far per agent with version, verdict pill (for example Proceed with conditions, Blocked on input, Partial), confidence and Evidence chips. **Findings table:** a card under the run with the summary "1 Critical · 3 High · 2 Medium · 0 Low" and columns Severity (icon and label), Type (Risk, Dependency), Finding, Raised by (an agent role) and Evidence (count). Critical rows sit on the blocker tint, and a partial Finding adds "Partial result · blocks submission until resolved". Finding statuses are Open, Resolved and Overridden. The table has no row-action column: **Challenge**, **Override** (where policy permits, with confirm) and **Rerun selected** live in the row's Inspector, which also shows the status. |
| Requirement row | Requirements | ID, text, Evidence chips, confidence (High, Medium, Low with icon), origin ("Extracted by Clarification Agent", "Edited by owner"), a confirmation pill (see Status Vocabulary) and a **Confirm** button. Low-confidence unconfirmed rows get an amber edge. Human-edited Requirements are locked against agent changes. The selected row offers Edit, Split, Merge and Delete. Create (`c`) opens an inline row. Each is a confirm dialog or inline form with a reason where it changes meaning. Group headers show "n · m confirmed". |
| Pending Requirement change | Requirements | A card at the top: "N pending changes from incremental intake", the source, and a diff using `+`/`−` text markers. Actions **Accept both** and **Reject**, or per change. An amber marker on the locked Requirement opens the same diff. Nothing human-edited is overwritten. |
| Gap row and Inspector | Gaps tab, Inspector | The row shows an impact indicator (3 coloured bars plus High, Medium or Low), the title, affected area, trigger (a Checklist item or Knowledge Source, with the agent's sparkles icon) and a "Blocks submit" tag when it does. The question status pill follows the question lifecycle. The Inspector shows Why it matters, the trigger and confidence, Related Requirements with Evidence, and the Clarification Question draft editable inline ("Edits are traced"; `e` edits). The primary button follows the question state, with a hint under it: Draft **Approve question** ("Draft, then Approved, Sent and Answered."), Approved **Mark as sent** ("Approved. Export it, send it to the customer, then mark it sent."), Sent **Save answer** ("Sent. Record the customer answer to close this Gap."; disabled until an answer is typed, via a **Customer answer** field with the placeholder "Paste or type the answer. Or add it as a new Source."), Answered **Reopen** ("Answered. Related Requirements have proposed updates.") and Dismissed **Reopen** ("Dismissed with a reason."). Reopening returns the question to Draft. Also **Convert** and **Dismiss**. Bulk **Approve N selected** and **Export questions** apply to multi-selected rows. A concurrent edit shows "Not saved: this question changed (412)" with **Reload** and **View diff** above the question. |
| Gap convert | Gap Inspector | A segmented Condition/Contingency control with help text. Condition: "The estimate states the wording as a Condition the customer must meet. Someone must accept it before submission." Contingency: an amount field and a named person must accept it. The accepting person defaults to me. The button reads "Convert to Condition" or "Convert to Contingency". |
| Gap dismissal | Gap Inspector | **Dismiss** requires a reason, and the button stays disabled until one is typed. The Gap becomes `dismissed_with_reason`, is greyed out at the bottom of the list, and can be reopened. Gaps from mandatory Checklist items can't be dismissed; they can only be answered or converted. |
| Conflict view | Conflicts tab | Two or more selectable position cards, each with the agent, its source Assessment version, the value, basis and Evidence. A note states when a mandatory constraint can't be overridden. Below the open Conflicts a **Resolved** card lists closed ones, each with a green check, the chosen position and the recorded reason, and a tag: "Resolved", or "Superseded by Assessment v2" when a later Assessment replaced the basis (a superseded Conflict stays listed and is never reopened). Resolving requires choosing a position or entering another value, plus a required reason; **Resolve** stays disabled until both exist. **Escalate** is also offered. In R3 the Negotiation proposal sits above the positions with its conditions and the dissenting agents. |
| Estimate grid | Estimate tab | Lines are grouped by category (Integration, Functional, Security, Non-functional) with subtotals and a grand total. Columns: Line, Covers (Requirement IDs), Role mix (Engineer, PM, QA bar with text), Effort h, Cont. h, Total h. Line tags: "Open Conflict", "Edited, carried from v2", "Contingency linked to A2". Totals are computed by the server, never in the browser. Cells are read-only in the grid; a line is edited in the Inspector (see Estimate line edit). A Contingency cell links to its Assumption. Submitted, Baseline and Superseded versions are read-only, and a submitted version offers a **New version** action (an explicit new draft with a reason). Each line carries a Work Package and an Integration Type, shown in the Inspector `[ASSUMPTION]`. The grid is hours-only; cost columns are Open Question 4. Selecting a line opens the Inspector with Basis, Role mix and Covered Requirements. |
| Estimate line edit | Inspector, Estimate tab | An "Edit line" section with **Engineer effort (h)** and a required **Reason for the change**. The primary button **Save change** stays disabled until the reason is typed, and saves the change to the draft in place. The hint reads "Recorded in the Decision Trace. Earlier versions are unchanged." An edit does not create a new Estimate Version, and version labels are whole numbers (v1, v2, v3). A concurrent edit shows "Not saved: this line changed (412)" with **Reload** and **View diff**. The Edit line section is hidden on read-only versions (submitted, Baseline and superseded). |
| Estimate toolbar and versions | Estimate tab | A segmented version switcher (v1, v2, v3) with a state pill in each segment (v1 Superseded, v2 Baseline, v3 Draft), "From Assessments (run 2)", a **Diff vs previous** toggle (`d`), a version list (`v`), **Export** and **Set Baseline**. The version list shows the Baseline first. |
| Version lifecycle | Estimate tab | A card under the toolbar with a four-step progress view, **Draft, In review, Approved, Baseline**, and a sentence for the selected version. Done steps are green checks, the current step is indigo, the rest are grey. v1: "v1 is superseded by v2 and is read only. Compare it with a later version using the diff toggle." v2: "v2 is the Baseline. A Baseline is replaced only by a newer approved version, and it cannot be edited." v3: "v3 is a draft built from Assessments run 2. Each edit needs a reason and is recorded in the Decision Trace." It is a status view, not a control. |
| Uncovered Requirement alert | Estimate tab | "1 Requirement not covered: R7 has no Estimate line." with **Add line**. |
| Assumptions Register | Estimate tab | Grouped by Condition (clipboard-check icon) and Contingency (shield-plus icon), with the amount for a Contingency. Every row shows its origin (Gap, Unknown or Finding), the accepting person and date, and the proposal wording. Unaccepted rows use the blocker row treatment with an **Accept** button, and the header reads "N not accepted block submit". |
| Review panel | Inspector, for a Review Request | The target with its Evidence, plus actions: Approve, Reject, **Challenge**, then a second row of **Request evidence**, **Request alternative** and **Escalate** (v2 draws them as buttons; the earlier More menu is gone). Every action except Approve requires a reason. Approve is disabled for the author with the message "You are the author, so you cannot approve." A **Review outcomes** list (below) appears for the author's own request. When all requested reviews are approved the panel reads "All requested reviews approved. Baseline can be set." with **Set Baseline**. |
| Challenge dialog | Review panel (Challenge), any Finding or Assessment | A 520px dialog titled "Challenge Estimate v3" (or the subject). **Reason (required)** with the placeholder "State what looks wrong and why." Under the eyebrow "Assessments to rerun", one toggle card per Assessment (`aria-pressed`), each with the agent, why it is affected, and a tag: **Engineering Agent** "Suggested" (pre-ticked) and **PM Agent** "Optional". Helper: "A rerun creates a new Estimate Version and shows the delta. Conflict detection, Critic and Red Team run again." One dialog serves both roles (Story 9.5). **Reviewer raising:** the toggle cards show the suggestions for information only and the primary button reads **Raise Challenge**, disabled until a reason is typed. The presales engineer who owns the Opportunity then gets an Inbox item that opens the same dialog with the reviewer's reason shown read-only. **Owner confirming:** the cards are editable and the primary button reads **Rerun N Assessments**, disabled until a reason exists and at least one Assessment is ticked; **Decline** needs a reason. **Owner raising their own Challenge:** one submit raises and confirms it, with both trace events recorded. Progress appears in Activity (FR-38, R1). From R3, reassessment starts automatically. |
| Review outcome (author side) | Inbox, Estimate tab | The author's Review request shows a **Review outcomes** list (eyebrow heading) under the actions: one row per event with an icon (green check for Approved, amber triangle for Challenged, indigo loader for "Confirmed rerun of Engineering Agent"), who, what, the time and the reason or result note, for example "New version v3 shows L1 +14.0 h." Each reviewer decision creates an Inbox item for the presales engineer, carrying the reviewer's reason. **Rejected:** the version becomes `rejected`, and the author creates a new version. **Evidence requested:** the request stays open; the author attaches Evidence or a new Source, then presses **Reply**. **Alternative requested:** the author creates a new version or Scenario (R3) and links it in the reply. **Escalated:** the request moves to the named reviewer, and the author sees the new assignee. **Challenged:** see Challenge dialog. |
| Inbox | Inbox | Two panes. The list has an unread dot, a bold title, meta and a kind pill (Review, Update). The detail pane shows the review panel for Review items, or the update. Empty, loading and superseded rules are in State Patterns. |
| Set Baseline | Estimate tab, Overview, Inbox | Enabled only when the "Blockers to Baseline" group is empty. A confirm dialog lists the approvers with role and approval date and states "This cannot be undone. A Baseline is replaced only by a newer approved version." After that, the version shows the Baseline marker everywhere, and the previous Baseline loses it. |
| Knowledge views | Knowledge | Four sub-tabs. **Graph:** a force-directed graph of Products, Integration Types, Knowledge Sources and Checklists, with search, type filters with counts, a legend (solid is documented or linked, dashed is missing coverage, dashed ring is stale, failed or missing) and dashed amber edges for missing coverage. Selecting a node opens a drawer with type, owner and last reviewed, a Coverage score (0 to 100) with a status pill, tabs Overview, Connections and Citations, stats (connections, cited by, last retrieved, stale in), "Used by agents" shares, a primary action (Edit checklist, Open source or View coverage) and **Mark reviewed**. **Sources:** table with Knowledge Source, product, Integration Type, tags, owner, last reviewed and status (Ready, Stale, Embedding, Embedding failed); stale after 12 months. **Checklists:** an item editor with Mandatory and Optional items ("mandatory items always create a Gap when unanswered"); users whose role cannot edit Checklists see "You do not have permission to edit Checklists. Ask an admin for the right role." **Coverage:** a matrix of products by Integration Types with cells Ready, Partial or Missing, each with an icon and tint; empty cells are tinted amber. The Graph (FR-66) is shown to platform administrators and the roles that can edit Checklists, and its keyboard alternative is the Coverage matrix and Sources table. Retrieval statistics (cited by, last retrieved, "Used by agents") are not shown at all, not even as zero, until agent retrieval is logged. |
| Reports views | Reports | **Estimate vs actual:** KPIs (closed Opportunities, total variance, failed Assumptions), a table by Integration Type with Estimate h, Actual h, a variance bar with percent (red above +10%) and a main-cause link that drills into the Opportunity's Actuals. A Calibration note: "Calibration is not available yet. Suggestions need at least 5 closed projects per Integration Type." (R4). **Pipeline:** KPIs, Opportunities by status as bars, and a Due soon table. **Cost and usage:** KPIs (runs, tokens, GPU seconds, cost) and a per-agent table (runs, tokens, GPU seconds, failures). Reports is visible only to the Head of Delivery and platform administrator; others do not see it. Charts are bars only, always with their values as text. |
| Admin views | Admin | **Users and roles:** user, role (Presales engineer, Delivery manager, Head of Delivery, Sales representative, or none), last active, status (Active, Invited). First sign-in creates a user with no roles. Opportunity access is set on each Opportunity. **Agents:** list with version, model, Enabled or Disabled and tool permissions, then a config version history, model profile and prompt version; edits create a new config version. No agent can send customer communication or approve, and disabled agents receive no tasks. **Catalogue:** Integration Types and Work Packages with a catalogue version. **Evals:** latest result per agent against the FR-60 release bars (Extraction recall, Citation validity, Gap recall, Irrelevant Gaps, Mandatory-item Gaps, Evidence support). R2 adds **Approval policies** and **Integrations**. Cost moved to Reports. |
| Trace | Trace tab | An append-only list (timestamp, actor, event, subject link) with filters by subject, actor and event. Rows can't be edited. Any line or Assumption jumps here, filtered. Selecting a row (click or `Enter`) highlights it and opens the **Trace event inspector** in the right pane: the event, time and actor (agent or human) at the top, then **Payload** (Event, Actor with agent version, Subject, Estimate Version, and for an agent a Correlation ID and the pinned Model, or for a human the Reason and the permission that authorised it), a **Version comparison · v2 to v3** with `+`/`−` rows when the event is an Estimate line edit, and **Evidence** chips. A note reads "Trace rows are append-only. Model reasoning is not stored, only decisions and Evidence." |
| Actuals | Actuals tab | Header "Actuals" with "Hours per Estimate line with a variance cause. Estimate v3 · import from file or enter by line.", **Import from file** and **Save Actuals**. A per-line table: Line, Estimate h, Actual h (editable), Variance ("+5.0 h (13.9%)", amber when over, green when under) and Variance cause. Lines with no Actual read "—" and "Not recorded" and are not counted in variance. Footnote: "Empty lines are not counted in variance. Each change is added to the Trace." Sortable by variance. With no Actuals at all the tab shows the Empty tab card (see State Patterns). Two variance colour rules are kept on purpose: Actuals is an entry screen, so any overrun is amber per line (green when under); Reports is an aggregate view, so only a material overrun above +10% is red. |
| Settings | Avatar button, command palette | One card, max 760px, with three sections. **Theme:** radio cards System (follows the operating system's light or dark setting), Light, Dark. **Density:** Comfortable or Compact ("Row height in lists and tables"; the row padding stays 12px or 6px, the "32px / 28px rows" captions in v2 are stale). **Single-key shortcuts:** a switch with a visible On/Off label, default **Off**, "Shortcuts such as c to create and j or k to move. ⌘K or Ctrl+K works either way." A first-run hint explains how to turn shortcuts on. Footer: "Saved in this browser. Roles and notifications are managed by an admin." Choices persist in the `psa_prefs` cookie, which the root layout reads so the right theme paints on the server. |
| Diff view | Estimate versions, pending Requirement changes | Side-by-side or inline. Changed values are marked with a tint plus `+`/`−` text markers. A delta column shows "+x h", "−x h" or "no change". |
| Command palette | Global | A search field with an `Esc` hint, and commands grouped by Navigate, the Opportunity, Action, View and Help, with the group label at the right. Context-aware commands are offered first in the current tab. `Enter` runs a command and `Esc` closes. Empty result: "No matching commands." `[ASSUMPTION]` the redesign searches commands only; searching Opportunities, Requirements and Gaps is carried from the earlier spine. |
| Banner and alert | Global, tabs | A full-width strip with an icon, a lead sentence, detail and actions. Informational: `role="status"`. Blocking: `role="alert"`. The **Offline** strip sits at the top of the main pane (see State Patterns). |
| Empty tab card | Sources, Requirements, Gaps, Conflicts, Estimate, Actuals, Trace | A centred card with a title, one sentence and one primary button that jumps to the tab that fixes the emptiness. Copy is in State Patterns. |
| Toast | Global | Used only for asynchronous confirmations and recoverable errors. Never used for blocking information. |

## State Patterns

| State | Surface | Treatment |
| --- | --- | --- |
| First load | Lists, tabs | shadcn Skeleton rows matching the layout (6 columns in lists), shown for at least 150 ms to avoid flicker. |
| Empty list | Opportunities, Inbox | A plain sentence and, where it helps, one action. Inbox: "Inbox is empty. Review requests and notifications for your Opportunities appear here." No illustration. |
| Empty tab | Opportunity tabs | A centred card with a title, one sentence and one action. **Sources:** "No Sources yet" / "Add an email, transcript or document. Requirements and Gaps are extracted from Sources." / Choose files. **Requirements:** "No Requirements yet" / "Requirements appear after the first Source is parsed." / Add a Source. **Gaps:** "No Gaps" / "Gaps appear after Requirements are checked against Checklists." / Open Requirements. **Conflicts:** "No Conflicts detected" / "Conflicts appear when Assessments or Sources disagree." / Open Assessments. **Estimate:** see No Estimate yet. **Actuals:** "No Actuals recorded" / "Record hours per Estimate line with a variance cause once delivery starts." / Record Actuals. **Trace:** "No trace events" / "Decisions and Evidence are recorded here as work happens." / Open Overview. Overview and Assessments have no empty card. |
| New Opportunity, no Sources | Overview | One sentence ("Add the customer's emails, call notes or transcripts to start") plus the dropzone inline. |
| Extraction running | Requirements | Requirements appear as they arrive. A header shows "Extracting — 2 of 3 sources" with the loader icon. |
| Run waiting for human | Overview, Inbox, Activity | An amber **Waiting for you** pill naming the decision needed, with a Resolve link. It also appears in the Inbox. |
| Task failed | Agent run table | A red pill with the reason, plus Retry and Skip. A timeout shows "Timed out after 2:00 · partial results kept (2 findings)". Partial results stay visible and are labelled "partial". |
| Budget limit reached | Overview and Assessments banner | "Run stopped at the token limit: 50,000 of 50,000. Completed results are kept. Tasks that did not run are named. Partial results are labelled as such." Actions: increase budget (admin) or rerun selected tasks. The tokens bar turns amber at its limit. |
| No Estimate yet | Estimate | "No Estimate yet" / "Run Assessments to produce Estimate v1 from the confirmed Requirements." with one primary action, **Run assessment**. There is no Start blank and no template. |
| Run queued | Overview, Activity | A neutral **Queued** pill with "Position 2 of 2 in queue — the model server is busy". It switches to Running without a refresh. |
| Upload rejected | Sources | A dismissible `role="alert"` banner naming the file and the reason: "Upload rejected: file.mp4. .mp4 is not a supported type. Add .eml, .msg, .docx, .pdf, .vtt or text, up to 50 MB." Nothing is stored. A file over 50 MB gets "Rejected: larger than 50 MB". |
| Source parsing | Sources | An agent-tint **Parsing** pill with progress ("62% · extracting text"). |
| Source parse failed | Sources | A red **Parse failed** pill with the reason ("No text layer found. The PDF is a scan.") plus **Retry** and **Paste text instead**. Other Sources keep processing. |
| Submitted version | Estimate | Read-only grid, a "Submitted v3, 14 Oct" banner, and a New version action. |
| In review / approved / rejected version | Estimate, version list | The version's status pill (see Status Vocabulary). Approved versions show the approvers. Rejected versions show the reason and a New version action. |
| Baseline version | Estimate, Overview, Reports, Opportunity list | The Baseline marker next to the version number. The version switcher lists the Baseline first. |
| Superseded Review | Inbox, review panel | Greyed out, with a "Superseded by v4" link and no actions. |
| Superseded version | Estimate | v1 shows a neutral **Superseded** pill, a lifecycle card with every step done, the note "v1 is superseded by v2 and is read only. Compare it with a later version using the diff toggle." and no editing. |
| Superseded Conflict | Conflicts | Listed under Resolved with a neutral tag "Superseded by Assessment v2" and its recorded reason. Never reopened. |
| Concurrent edit (412) | Inspector, grid, Gap question, Estimate banner | A red-tint `role="alert"` block above the field: lead "Not saved: this line changed (412)" (or "this question changed"), detail "[Collaborator] saved L2 at 09:52. Reload to get the latest, or view the diff before you re-apply your change.", and actions **Reload** (discards mine) and **View diff**. On the Estimate it is a banner with the same actions. Nothing is overwritten silently. |
| Pending Requirement change | Requirements | An amber marker on the locked Requirement opens the diff with Accept and Reject. |
| Live connection lost | Global, Sources banner | A `role="status"` "Reconnecting… Live status is paused. Showing the last update from 09:48." with **Retry now**. On reconnect, missed events replay and the UI catches up with no toast. After 60 s offline the **Offline** strip appears (below). |
| Offline | Global, top of the main pane | A full-width `role="alert"` strip on a neutral tint with a wifi-off icon: "You are offline. You can read this Opportunity. Edits, uploads and runs are disabled until the connection returns." and a **Retry** button. Reading stays available; every edit, upload and run control is disabled with its reason. On reconnect the strip clears and missed events replay. |
| Weak knowledge coverage | Gaps, Assessments | An info banner: "No documentation for 2 integration types in scope — Gap detection may be incomplete", with a link to Knowledge coverage. |
| Low confidence | Requirements, Assessments, Estimate Basis | A "Low confidence" label with its basis, with an amber edge on unconfirmed Requirements. It's never hidden. |
| Permission denied | Any | Actions the user can't take are hidden, or replaced by a short denial banner where the surface is otherwise visible (for example Checklists). Direct URL access shows "You don't have access to this Opportunity", with no details leaked. |
| Knowledge Source embedding | Knowledge Sources | **Embedding** (agent tint) while indexing, **Ready** when searchable, **Embedding failed** (red) with a Retry. |

## Status Vocabulary

Pill labels for the architecture's state machines. Each pill pairs an icon and a label with a semantic tint from `DESIGN.md`: the semantic colour as text on its `-tint` fill. "Neutral" means `{colors.neutral}` on `{colors.neutral-tint}`.

| Entity | Status → label (icon, colour) |
| --- | --- |
| Opportunity (derived, never stored) | `intake` Intake (loader, `{colors.agent}`) · `gaps_open` Gaps open (`{colors.gap}`) · `assessing` Assessing (`{colors.agent}`) · `estimating` Estimating (neutral) · `in_review` In review (clock, `{colors.gap}`) · `baselined` Baselined (check-circle, `{colors.resolved}`) · `delivered` Delivered (neutral) · `closed` Closed (neutral) |
| Source | `parsing` Parsing (loader, `{colors.agent}`, with percent) · `parsed` Parsed (check, `{colors.resolved}`) · `parse_failed` Parse failed (alert, `{colors.blocker}`) |
| Knowledge Source | `embedding` Embedding (loader, `{colors.agent}`) · `ready` Ready (check, `{colors.resolved}`) · `stale` Stale (triangle, `{colors.gap}`) · `embedding_failed` Embedding failed (alert, `{colors.blocker}`) |
| Requirement (confirmation) | `unconfirmed` Unconfirmed (neutral, or `{colors.gap}` edge when Low confidence) · `confirmed` Confirmed (check, `{colors.resolved}`) · `needs_review` Needs review (triangle, `{colors.gap}`) |
| Workflow Run | `queued` Queued (clock, neutral) · `running` Running (sparkles or loader, `{colors.agent}`) · `waiting_for_human` Waiting for you (clock, `{colors.gap}`) · `completed` Completed (check, `{colors.resolved}`) · `failed` Failed (alert, `{colors.blocker}`) · `cancelled` Cancelled (ban, neutral) · token-limit stop shown as a **Stopped at token limit** pill (`{colors.gap}`) |
| Task | `queued` Queued · `running` Running · `completed` Completed (`{colors.resolved}`) · `failed` Failed (`{colors.blocker}`) · `timed_out` Timed out (`{colors.blocker}`) · `skipped` Skipped (neutral) · waiting for you (`{colors.gap}`) |
| Gap / Unknown | `open` Open (impact-coloured, with High `{colors.blocker}`, Medium `{colors.gap}`, Low neutral) · `answered` Answered (check, `{colors.resolved}`) · `converted` Converted (arrow-right, neutral) · `dismissed_with_reason` Dismissed (ban, neutral) |
| Clarification Question | `drafted` Draft (pencil, neutral) · `approved` Approved (check-circle, `{colors.resolved}`) · `sent` Sent (send, `{colors.agent}`) · `answered` Answered (`{colors.resolved}`) · `unanswered` No answer (`{colors.gap}`) |
| Conflict | `open` Open (alert, `{colors.blocker}`) · `negotiating` Negotiating (`{colors.agent}`) · `resolved` Resolved (check, `{colors.resolved}`) · `escalated` Escalated (arrow-up, `{colors.gap}`) · resolved against an older Assessment: tag "Superseded by Assessment v2" (neutral) |
| Finding | `open` Open (`{colors.blocker}` if critical, otherwise neutral) · `resolved` Resolved · `overridden` Overridden (shield, neutral) |
| Estimate Version | `draft` Draft (pencil, neutral) · `submitted` Submitted (neutral) · `in_review` In review (`{colors.gap}`) · `approved` Approved (`{colors.resolved}`) · `rejected` Rejected (`{colors.blocker}`) · `superseded` Superseded (neutral, struck-through label). The Baseline marker is separate (anchor). The version switcher shows Superseded, Baseline or Draft on each segment, and the Version lifecycle card reads Draft, In review, Approved, Baseline. |
| Review Request | `pending` Pending (`{colors.gap}`) · `approved` Approved (`{colors.resolved}`) · `rejected` Rejected (`{colors.blocker}`) · `challenged` Challenged (message, `{colors.gap}`) · `superseded` Superseded · `cancelled` Cancelled |
| Assumption | Accepted by [person] · date (`{colors.resolved}`) · Not accepted (`{colors.blocker}` row) |
| Inbox item kind | Review (`{colors.agent}`) · Update (neutral) |
| Confidence | High (`{colors.resolved}`) · Medium (neutral) · Low (triangle, `{colors.gap}`) |
| Report variance | Above +10% (`{colors.blocker}`), within range (neutral), under (`{colors.resolved}`) `[ASSUMPTION]` for the under-range colour |

**Reconciling Requirement status.** Earlier the spine described a Requirement only by its origin (extracted or human), lock state and pending change. Those stay. The redesign adds a separate **confirmation** state. Unconfirmed is the initial state of an extracted Requirement. **Confirmed** is set when a person presses Confirm (and automatically for a Requirement a person created). **Needs review** is set when an accepted pending change, an edit by someone other than the confirmer, or an agent flag changes a Confirmed Requirement; an edit by the confirmer keeps it Confirmed. A Requirement can be human-edited and locked while Unconfirmed. The confirmation state counts toward the "Requirements confirmed" step of the pipeline and never blocks submission (PRD FR-6, architecture AD-11).

## Interaction Primitives

**Keyboard first, mouse complete.** Every action is reachable by mouse. Power users never need to reach for it.

- `⌘K` / `Ctrl+K`: command palette (always on)
- `g i` / `g m` / `g a` / `g k` / `g r`: go to Inbox, My Opportunities, All Opportunities, Knowledge, Reports
- `1`–`9`: switch Opportunity tab
- `j` / `k`: move selection; `Enter`: open in inspector; `Esc`: close the topmost layer
- `x`: multi-select; `e`: edit the selected item; `c`: create in context (Requirement, Source, Gap question, Opportunity on a list)
- `[`: collapse or expand the sidebar; `]`: cycle the right pane (closed, open, closed)
- `v`: version list; `d`: diff toggle (Estimate)
- `?`: shortcut cheat sheet

**Single-key shortcuts are governed by the Settings switch** (WCAG 2.1.4). Everything on this list except `⌘K` / `Ctrl+K` and `Esc` is a single-key shortcut: the `g` chords, `1`–`9`, `j`/`k`, `Enter` in a list, `x`, `e`, `c`, `v`, `d`, `[`, `]` and `?`. The redesign defaults the switch to **Off**, and the control equivalents (sidebar buttons, the palette, tab clicks) always work. A first-run hint explains how to turn shortcuts on, and the choice is stored in the `psa_prefs` cookie. A shortcut typed inside an input or textarea is never captured.

The cheat sheet (opened with `?`, or the sidebar Keyboard shortcuts button) lists every shortcut above. The redesign's own sheet listed only ⌘K, j/k, x, e, Enter, `]`, `[`, `?` and Esc; the `g` chords, `1`–`9`, `c`, `v` and `d` are restored by user decision. v2 binds `c` (create) but did not add it to its sheet.

**Rules:**
- Saves are optimistic on blur, with server confirmation.
- Any save the server rejects rolls back with an inline reason.
- Drag-and-drop is used only for file upload. Rows are not reordered by dragging.
- Hover-only affordances always have a focus equivalent.
- Undo (`⌘Z`) is available for the last inline edit on draft items only. Submissions, approvals and Baselines can't be undone, which is why they ask for confirmation.
- Disabled primary actions (Submit, Resolve, Set Baseline) are `aria-disabled` and state their reason in adjacent text.
- Motion is limited to short colour transitions and the sidebar width. All of it is off under `prefers-reduced-motion`. Running is a static loader icon, not a pulse.

## Accessibility Floor

This section covers behaviour. Visual contrast comes from `DESIGN.md` (ratios recorded there).

- WCAG 2.1 AA (PRD NFR-7), with axe checks in CI. Redesign v2 states the same floor in its "Accessibility behaviours" card (keyboard first, focus, skip link, live announcements, no colour-only meaning, contrast, motion, targets and zoom, tables and forms).
- A **Skip to main content** link is the first tab stop on every screen. It becomes visible on focus and moves focus to the main pane (`id="main-content"`, `tabindex="-1"`).
- Controls are at least 28px with spacing, and the layout works at 200% zoom down to 1280px wide. Required fields say "Required", and error messages say what to do.
- Every shortcut has a visible control equivalent. Single-key shortcuts can be turned off in Settings (WCAG 2.1.4).
- Tab order follows reading order: sidebar → tab strip → main → right pane.
- Focus moves into the inspector when it opens and returns to the originating row when it closes. Dialogs trap focus and return it to their trigger.
- Live updates are announced through a polite `aria-live` region (`role="status"`): the screen name on navigation ("Gaps screen. Selected gap: …"), run status changes, saves, blocker count changes, and "waiting for you". Errors, conflicts and the Offline strip use `role="alert"`. Bursts of agent progress are throttled to one announcement every 5 s.
- Status is never conveyed by colour alone (an icon and a label always accompany it). Impact bars, row edges and role-mix segments always come with text.
- Estimate grid cells are navigable with arrow keys, and screen readers announce row and column headers.
- Tabs use `role="tab"`; selectable position cards and toggles use `aria-pressed`; banners use `role="status"` or `role="alert"`; dialogs use `role="dialog"` and `aria-modal`.
- The Knowledge Graph is not the only route to its data: Sources and Coverage hold the same facts as tables.
- Focus is a 2px ring with a 2px offset in `{colors.ring}`, and a lighter indigo in dark.

## Responsive & Platform

| Width | Behaviour |
| --- | --- |
| ≥ 1440px | All panes docked: sidebar, main, and the right pane. |
| 1280–1439px | The right pane overlays the main pane. The sidebar can be collapsed (`[`). |
| 1024–1279px | The sidebar collapses to icons. Overlays as above. A best-effort tier. |
| < 1024px | A read-only notice: "The workbench needs a wider screen. You can view Opportunities here, but editing is disabled." |

The redesign was drawn at a fixed 1440 x 900 frame with no breakpoint behaviour. The table above is restored by user decision. The minimum supported width is 1280px. Light and dark themes follow the system preference, with a manual override in Settings and a theme toggle in the sidebar footer. Comfortable or compact density is a Settings choice (row padding 12px or 6px) and is remembered in the browser.

## Inspiration & Anti-patterns

- **Taken from the redesign:** white cards on a pale canvas, KPI tiles, tint-filled pills, agent reasoning shown inline, the Submission pipeline as a progress view, and role-based Reports.
- **Taken from Linear:** keyboard-first navigation (`g` shortcuts, `j`/`k`, `⌘K`), a list with an inspector peek, and instant optimistic interactions. The earlier dense density is not kept.
- **Taken from code-review tools:** diffs between Estimate Versions, Challenges as review comments with a required reason, and "superseded" states.
- **Taken from spreadsheets:** the Estimate grid feels like Excel for navigation and inline editing, but totals are server-calculated and locked.
- **Reversed from the earlier spine:** the 8-step Submission pipeline, the sparkles icon and agent initials avatars were previously rejected and are now adopted (user decision). The pipeline is a status tracker, never a forced step order. Agents stay named by role.
- **Rejected: wizard or forced-order flow.** The engineer jumps where the work is. The pipeline and the Submission Blockers card give guidance without locking the order.
- **Rejected: chat-first "talk to your AI" interface.** Agents produce structured Findings with Evidence. A chat window would hide traceability.
- **Rejected: personified agents.** No names, faces, first-person copy or chat bubbles.
- **Rejected: auto-applied AI changes.** Every agent output is a proposal shown with its Evidence. Human edits are never overwritten (pending changes instead).

## Key Flows

Protagonists follow the PRD user journeys. They are named by role.

### Flow 1: The presales engineer turns a messy discovery call into an estimate they can defend (UJ-1)

1. The presales engineer presses `c` on My Opportunities, imports the first email, and lands on Overview.
2. They drag in a call transcript and two emails. The Requirements count rises as extraction streams in. Activity shows "Intake: extracting 3 sources".
3. They press `3` and confirm the extracted Requirements, then press `4`. Nine Gaps are ranked by impact, each with a drafted Clarification Question. They edit two inline, multi-select seven with `x`, approve them, and export them for the sales representative, then mark them sent.
4. Two days later the answers arrive as a new Source. They record the answers. The answered Gaps turn green and two locked Requirements show pending changes, which they accept. They press **Run assessment** on Overview.
5. Agent run shows the Engineering, PM and Security Agents running in parallel, then Critic and Red Team. A red Red Team Finding appears: "ERP custom fields — no evidence the connector supports them."
6. They open the Finding, read the Evidence chip, and convert the related Unknown into a priced Contingency.
7. **Climax:** they press `1`. The Submission pipeline advances and the Blockers card empties item by item as they accept the last two Assumptions, then reads **"0 blockers — ready to submit"**. In the Estimate tab, every Contingency line links to its Assumption, and every Assumption links to the Gap or Finding it came from. They submit and request review from engineering.

**Failure:** the Security Agent times out. Its row shows a red "Timed out · partial results kept" pill with **Retry** while the other results stay in place. They retry and the run completes.

### Flow 2: The engineering reviewer challenges an integration effort they don't believe (UJ-2)

1. The reviewer sees "Review request: Estimate v2" in the Inbox and presses `Enter`.
2. The review panel shows the integration line, its Engineering Assessment and the Evidence. They click the Evidence chip and see that the connector document is for an older version.
3. They press **Challenge**, write "Connector needs v5 upgrade; doc cited is v4," and press **Raise Challenge** in the Challenge dialog. The suggested Assessments are shown for information only.
4. The presales engineer gets an Inbox item for the Challenge. It opens the same Challenge dialog with the reviewer's reason shown read-only and the suggested Assessments editable (the Engineering Agent pre-ticked, the PM Agent optional). They press **Rerun 1 Assessment**. Activity shows the reassessment run, followed by the Critic and Red Team rerunning. The reviewer's own request lists these steps under **Review outcomes**. (When the presales engineer raises a Challenge themself, one submit raises and confirms it.)
5. **Climax:** the presales engineer gets an Inbox item: "v3 created from the Challenge (+3 weeks on ERP integration)". They open the diff. The old v2 review request shows "Superseded by v3". The reviewer approves v3, and the Challenge and the delta sit in the Trace tab. The Overview gate now reads "0 blockers to Baseline". The presales engineer presses **Set Baseline** and confirms, and v3 now carries the Baseline marker.

**Failure:** the reviewer tries to approve while the author is editing the same version. They get an inline 412 message, open the diff, see the change, and approve the new state.

### Flow 3: The presales engineer resolves a conflict between agents (UJ-3)

1. The Conflicts count shows 1 on the tab. They press `6`.
2. Two positions sit side by side: the Engineering Agent says 4 weeks, the PM Agent says 7 weeks because of customer UAT cycles, each with Evidence.
3. **Climax:** they choose the PM position, type "Customer confirmed two UAT rounds," and press Resolve. The Conflict closes, the Estimate line updates in the background, and the blocker count drops by one. Both positions remain in the Trace.

R3 variant: a Negotiation proposal sits on top ("6 weeks if UAT environment is ready by Week 2"). They accept it, which adds a Condition to the Assumptions Register.

### Flow 4: The presales engineer tests whether a phased rollout de-risks the deal (UJ-4, R3)

1. In the Estimate tab, they open the Scenarios switcher and press **New Scenario from Baseline**.
2. In the inspector they change the constraints: phase 2 integrations deferred, and a budget cap set. The Scenario appears as "Scenario A (draft)".
3. Only the affected agents rerun. Activity shows the Engineering and PM Agents, then the Critic and Red Team.
4. With the Baseline and Scenario A selected, they press `d`. The diff shows effort, timeline, cost, Risks and Assumptions side by side.
5. **Climax:** they request commercial approval on Scenario A. Once it's approved, **Promote to Baseline** becomes available. Promoting moves the Baseline marker to the Scenario's version. The original Baseline stays in the version list, unchanged.

**Failure:** a Scenario rerun hits its token budget. The Scenario shows the "Run stopped at the token limit" banner and keeps its partial results. The Baseline is untouched.

### Flow 5: The Head of Delivery finds out why a project overran (UJ-5)

1. They open Reports. The Estimate vs actual table groups projects by Integration Type, with one project at +35% shown with a red variance bar.
2. They click the main-cause link, land on the Opportunity's Actuals tab, and sort by variance. The overrun sits on the ERP integration line.
3. **Climax:** they click the line's Assumption, "Customer provides API access by Week 1 (Condition)", and the inspector shows who accepted it, when, and the Evidence behind it. In the Trace tab, filtered to this Assumption, they see the full chain from Gap to Clarification Question to the customer's answer to the Condition, without asking anyone.

## Open Questions

1. **Single organisation.** The redesign's organisation switcher implies multiple organisations. `[ASSUMPTION: single organisation, the switcher shows the current one]`. If false, multi-tenancy (architecture "Deferred") reopens.
2. **Default landing page.** My Opportunities for presales engineers. Should reviewers land on Inbox instead `[ASSUMPTION: role-based default]`?
3. **Blocker types.** Does the architecture's blocker check (AD-27) include uncovered Requirements, and does the "Blockers to Baseline" group repeat unresolved draft items as the redesign shows `[ASSUMPTION]`? FR-14 and FR-33 would change with it.
4. **Estimate dimensions and cost.** The redesign's grid is hours-only, grouped by category with a role mix. The earlier spine used Work Package by Integration Type and showed cost. Which is the canonical line model, and are cost columns in R1?
5. **Local models.** The redesign shows model chips and "Local · Ollama" labels and a cost of 0.00 for local models. Is surfacing the model and token budget to every user intended, or admin only?
6. **Notifications and Microsoft 365 connection.** v2's Settings says notifications are managed by an admin and offers no personal control, so Story 11.1 (notification preferences) stays pending. Where does "Connect Microsoft 365" live (Admin, Integrations or an account section of Settings; Story 13.4)?

## Decisions

Recorded 2026-10-21 (Sprint Change Proposal; also in `.memlog.md`). They replace the earlier Open Questions on these topics and their `[ASSUMPTION]` tags.

- **Single-key shortcuts** default to Off, with a first-run hint. Preferences (theme, density, shortcut switch) live in the `psa_prefs` cookie, not localStorage.
- **Estimate Versions** have whole-number labels. A draft line is edited in place from the Inspector (Engineer effort and a required reason, button **Save change**) and recorded in the Decision Trace. New versions come from assessment reruns, Challenges or an explicit new draft. Edit line is hidden on read-only versions.
- **Challenge** is one 520px dialog: the reviewer raises it, the owning presales engineer confirms in the same dialog from the Inbox item, and an owner raising their own Challenge raises and confirms in one submit (Story 9.5).
- **Finding statuses** are Open, Resolved and Overridden, with Challenge, Override and Rerun in the row's Inspector.
- **Variance colours:** both rules are kept. Actuals shows amber per line when over; Reports shows red above +10%.
- **Estimate empty state** has no Start blank and no template.
- **Knowledge Graph viewers** are platform administrators and the roles that can edit Checklists (PRD FR-66).
- **Reports** (Pipeline, Cost and usage, Estimate vs actual) is visible only to the Head of Delivery and platform administrator (FR-67, FR-59).
- **Requirement confirmation** never blocks submission, and a confirmer's own edit keeps the Requirement Confirmed (FR-6, AD-11).
