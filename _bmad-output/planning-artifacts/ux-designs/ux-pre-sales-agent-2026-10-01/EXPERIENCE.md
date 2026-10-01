---
name: Agentic AI Presales Platform
status: final
created: 2026-10-01
updated: 2026-10-01
sources:
  - ../../prds/prd-pre-sales-agent-2026-10-01/prd.md
  - ../../architecture/architecture-pre-sales-agent-2026-10-01/ARCHITECTURE-SPINE.md
  - ../../briefs/brief-pre-sales-agent-2026-10-01/brief.md
---

# Agentic AI Presales Platform: Experience Spine

## Foundation

This is a desktop web application (Chrome and Edge; PRD NFR-8) built with shadcn/ui on Next.js and Tailwind (architecture AD-16). `DESIGN.md` is the visual identity reference. This spine defines behaviour. It is a **dense, keyboard-first workspace modelled on Linear**, not a step-by-step wizard. The presales engineer can jump to any part of an Opportunity at any time, and the platform always shows what still blocks a submittable Estimate.

Every term follows the PRD glossary exactly: Opportunity, Requirement, Gap, Clarification Question, Assessment, Finding, Evidence, Assumption (Condition or Contingency), Unknown, Conflict, Estimate Version, Baseline, Review Request, Challenge, Decision Trace and Actuals. Live updates arrive over SSE (AD-30), so no screen needs a manual refresh except after a concurrent-edit conflict.

## Information Architecture

| Surface | Reached from | Purpose | Release |
| --- | --- | --- | --- |
| Inbox | Sidebar / `g i` | Review Requests assigned to me, Challenges on my work, runs waiting for my input, and mentions | R1 |
| My Opportunities | Sidebar / `g m` (default landing page) | Opportunities I own or collaborate on, with status, blocker count and next proposal date | R1 |
| All Opportunities | Sidebar / `g a` | Every Opportunity I can access, with filters (status, owner, product, date) | R1 |
| Opportunity workspace | Any Opportunity row | The working surface. Tabs below | R1 |
| Knowledge | Sidebar / `g k` | Knowledge Sources, Checklists, catalogue and the coverage view (FR-8 to FR-10, FR-65) | R1 |
| Reports | Sidebar / `g r` | Estimate-vs-actual variance and drill-down (FR-50); Calibration (R4) | R1 / R4 |
| Admin | Sidebar (admin role) | Agent Registry, approval policies (R2), users and roles, integrations (R2), cost and observability, evals | R1 / R2 |
| Command palette | `⌘K` / `Ctrl+K` anywhere | Navigate, search Opportunities and Requirements, run actions | R1 |
| Settings | Avatar menu | Theme, density, keyboard shortcuts, notifications | R1 |

**Opportunity workspace tabs.** Each is reached with the `1`–`9` keys and shows a blocker or gap count badge where relevant:

| Key | Tab | Shows | Main actions |
| --- | --- | --- | --- |
| 1 | Overview | Submission Blockers list, current Estimate Version summary, live run status, recent activity | Run assessment, open blocker |
| 2 | Sources | Opportunity Sources, upload or paste area, source viewer with highlighted passages | Add source, view passage |
| 3 | Requirements | Requirement list grouped by classification, with citations, origin (extracted or human) and lock state; pending changes queue | Edit, split, merge, confirm, accept or reject pending change |
| 4 | Gaps | Gaps and Unknowns ranked by impact; Clarification Questions with status | Edit question, approve, export, mark sent, record answer, convert to Assumption or Risk |
| 5 | Assessments | One section per Specialist Agent, plus Critic and Red Team. Findings with Evidence chips, confidence and status | Challenge, override (where policy permits), rerun selected |
| 6 | Conflicts | Open and resolved Conflicts, side-by-side positions with Evidence | Choose position, enter other, escalate; accept or reject Negotiation proposal (R3) |
| 7 | Estimate | Estimate grid (lines by Work Package and Integration Type), Assumptions Register, Risks, version switcher, diff view | Edit line, accept Assumption, submit, request review, set Baseline, export |
| 8 | Trace | Decision Trace timeline filtered by subject; jump from any line or Assumption | Filter, open subject, compare versions |
| 9 | Actuals | Actuals per Estimate line with variance cause (after delivery) | Record or import Actuals |

R2 adds a **Proposal** tab. R3 adds a **Scenarios** switcher in the Estimate tab header.

→ Visual reference: `mockups/opportunity-overview.html` (Overview, blockers, activity rail), `mockups/gaps.html` (Gaps tab with inspector and Convert form), `mockups/estimate.html` (Estimate grid, Assumptions Register, diff). The mockups illustrate the layout. Where a mockup and this spine disagree, the spine wins (including the colours updated after rendering).

**Right pane.** Selecting any row (Requirement, Gap, Finding, Assumption, Estimate line, trace event) opens the **inspector** with its full detail, Evidence and history. `Esc` closes it. When nothing is selected, the right pane shows the **activity rail**, a live feed of agent task progress and trace events. `]` toggles the rail.

Dialogs stack one level deep at most. Destructive or irreversible actions (submit, set Baseline, override) use a confirm dialog. Everything else is inline.

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

## Component Patterns

These are behavioural rules. Visual specs are in `DESIGN.md.Components`.

| Component | Use | Behavioural rules |
| --- | --- | --- |
| List row | All lists | `j`/`k` move selection, `Enter` opens the inspector, `x` multi-selects, and row actions appear on hover or focus. Lists are paginated or virtualised; there is no infinite scroll. |
| Submission Blockers list | Overview | Derived from the platform's single blocker check (AD-27). It shows one of two gates, depending on the current Estimate Version. **Draft version, "Blockers to submit":** open Gaps and Unknowns, unaccepted Assumptions, open Conflicts, and critical Findings without an override. **Submitted version, "Blockers to Baseline":** Review Requests that are pending, rejected or challenged. Each item names its type, links straight to the subject, and disappears live when resolved. When the list is empty, that gate's action becomes primary: **Submit** or **Set Baseline**. |
| Inspector | Right pane | Shows the subject's fields, Evidence chips, version history and actions. Edits save on blur with `If-Match`. Has a "Open in tab" link. |
| Evidence chip | Findings, Requirements, Assumptions, Proposal claims | Clicking it opens the cited passage in the inspector, with the span highlighted inside the source text. Shows the version. A broken or superseded reference is shown struck through with a "superseded" label. |
| Agent run panel | Overview, activity rail | One row per task: agent, status pill, elapsed time, a running dot while active. A failed task shows its reason with **Retry** and **Skip** buttons. A waiting-for-human task shows a **Resolve** button that jumps to the decision. Cancelling a run asks for confirmation. |
| Gap card | Gaps tab (row), inspector (detail) | Shows why it matters (the affected estimate area), the trigger (Checklist item or Knowledge Source), and the Clarification Question draft, editable inline. The status pill follows the question lifecycle. **Convert** opens a small form with a segmented Condition/Contingency control, with an amount for a Contingency and the accepting person defaulting to me. |
| Conflict view | Conflicts tab | Two or more positions side by side, each with Evidence and its source Assessment version. Resolving requires a reason. In R3, the Negotiation proposal sits above the positions with its conditions and the dissenting agents. |
| Estimate grid | Estimate tab | Inline cell editing on draft versions only. Totals are computed by the server, never in the browser. A Contingency cell links to its Assumption. Version switcher: a segmented control for the two most recent versions plus a list (`v`), `d` toggles a diff against the previous version. Submitted versions are read-only, with a **New version** action. |
| Assumptions Register | Estimate tab | Grouped by Condition (clipboard-check icon) and Contingency (shield-plus icon). Every row shows its origin (Gap, Unknown or Finding), who accepted it, and the proposal wording or amount. Unaccepted rows are flagged as blockers. |
| Review panel | Inspector, for a Review Request | The target with its Evidence, plus actions: Approve, Reject, Challenge, Request evidence, Request alternative, Escalate. Every action except Approve requires a reason. Approve is disabled if you authored the target. |
| Challenge form | Any Finding or Assessment | The challenger (reviewer or presales engineer) enters a required reason and submits. The presales engineer who owns the Opportunity then gets a **Confirm reassessment** item listing the suggested affected Assessments, each with a checkbox (FR-38, R1). Confirming starts a run, and progress appears in the activity rail. From R3, reassessment starts automatically. |
| Review outcome (author side) | Inbox, Estimate tab | Each reviewer decision creates an Inbox item for the presales engineer, carrying the reviewer's reason. **Rejected:** the version becomes `rejected`, and the author creates a new version. **Evidence requested:** the request stays open; the author attaches Evidence or a new Source, then presses **Reply**. **Alternative requested:** the author creates a new version or Scenario (R3) and links it in the reply. **Escalated:** the request moves to the named reviewer, and the author sees the new assignee. **Challenged:** see Challenge form. |
| Gap impact indicator | Gaps tab | High, Medium or Low label with a neutral 3-segment bar. The list sorts by impact by default. |
| Gap dismissal | Gaps tab | **Dismiss** requires a reason. The Gap becomes `dismissed_with_reason`, is greyed out at the bottom of the list, and can be reopened. Gaps from mandatory Checklist items can't be dismissed; they can only be answered or converted. |
| Set Baseline | Estimate tab, Overview | Enabled only when the "Blockers to Baseline" gate is empty. A confirm dialog lists the approvers and states that the action can't be undone. After that, the version shows the Baseline marker everywhere, and the previous Baseline loses it. |
| Knowledge views | Knowledge | Three sub-tabs. **Sources:** list with product, Integration Type, version, owner and last-reviewed date, flagged as stale after 12 months. **Checklists:** list with an item editor; mandatory items are marked. **Coverage:** a matrix of products by Integration Types showing documentation and Checklist counts, with empty cells tinted amber. |
| Admin views | Admin | Sub-tabs. **Agents:** list → config version history, model profile, prompt version and permissions; edits create a new config version. **Users & roles.** **Catalogue:** Integration Types and Work Packages. **Cost:** cost and tokens per Opportunity and per agent. **Evals:** latest eval results per agent against the FR-60 thresholds. R2 adds **Approval policies** and **Integrations**. |
| Diff view | Estimate versions, pending Requirement changes | Side-by-side or inline. Changed values are marked with a tint plus `+`/`−` text markers. |
| Command palette | Global | Fuzzy search across Opportunities, Requirements, Gaps and commands. Context-aware commands are offered first in the current tab. `Enter` runs the command and `Esc` closes. |
| Toast | Global | Used only for asynchronous confirmations and recoverable errors. Never used for blocking information. |

## State Patterns

| State | Surface | Treatment |
| --- | --- | --- |
| First load | Lists, tabs | shadcn Skeleton rows matching the layout, shown for at least 150 ms to avoid flicker. |
| New Opportunity, no Sources | Overview | One sentence ("Add the customer's emails, call notes or transcripts to start") plus the upload or paste area inline. |
| Extraction running | Requirements | Requirements appear as they arrive. A header shows "Extracting — 2 of 3 sources" with a running dot. |
| Run waiting for human | Overview, Inbox, activity rail | An amber **Waiting for you** pill naming the decision needed, with a Resolve link. It also appears in the Inbox. |
| Task failed | Agent run panel | A red pill with the reason, plus Retry and Skip. Partial results stay visible and are labelled "partial". |
| Budget limit reached | Overview banner | "Run stopped: token budget reached. Results so far are kept." Actions: increase budget (admin) or rerun selected tasks. |
| No Estimate yet | Estimate | "No Estimate Version yet. Run an assessment to draft one, or start from the template." Actions: Run assessment (primary) and Start blank. |
| Run queued | Overview, activity rail | A neutral **Queued** pill with "Position 2 in queue — the model server is busy". It switches to Running without a refresh. |
| Upload rejected | Sources | An inline message on the file row, for example "Rejected: .exe files aren't allowed" or "Rejected: larger than 50 MB". Nothing is stored. |
| Source parse failed | Sources | A red **Parse failed** pill with the reason, plus **Retry** and **Paste text instead**. Other Sources keep processing. |
| Submitted version | Estimate | Read-only grid, a "Submitted v3, 14 Oct" banner, and a New version action. |
| In review / approved / rejected version | Estimate, version list | The version's status pill (see Status Vocabulary). Approved versions show the approvers. Rejected versions show the reason and a New version action. |
| Baseline version | Estimate, Overview, Reports | The Baseline marker next to the version number. The version switcher lists the Baseline first. |
| Superseded Review | Inbox, review panel | Greyed out, with a "Superseded by v4" link and no actions. |
| Concurrent edit (412) | Inspector, grid | An inline message: "Changed by [user] since you opened it." Actions: Reload (discards mine) or view the diff, then reapply. Nothing is overwritten silently. |
| Pending Requirement change | Requirements | An amber marker on the locked Requirement opens the diff with Accept and Reject. |
| Live connection lost | Global (status bar) | A small "Reconnecting…" indicator. On reconnect, missed events replay and the UI catches up with no toast. After 60 s offline: "Offline — edits disabled". |
| Weak knowledge coverage | Gaps, Assessments | An info banner: "No documentation for 2 integration types in scope — Gap detection may be incomplete", with a link to Knowledge coverage. |
| Low confidence Finding | Assessments | A "Low confidence" label with its basis. It's never hidden. |
| Permission denied | Any | Actions the user can't take are hidden. Direct URL access shows "You don't have access to this Opportunity", with no details leaked. |
| Empty Inbox | Inbox | "Nothing waiting for you." No illustration. |

## Status Vocabulary

Pill labels for the architecture's state machines. Each pill pairs an icon and a label with a colour token from `DESIGN.md`. "Neutral" means shadcn `muted-foreground`.

| Entity | Status → label (icon, colour) |
| --- | --- |
| Opportunity (derived, never stored) | `intake` Intake · `gaps_open` Gaps open (`{colors.gap}`) · `assessing` Assessing (`{colors.agent}`) · `estimating` Estimating · `in_review` In review · `baselined` Baselined (anchor, `{colors.resolved}`) · `delivered` Delivered · `closed` Closed (neutral) |
| Workflow Run | `queued` Queued (clock, neutral) · `running` Running (dot, `{colors.agent}`) · `waiting_for_human` Waiting for you (hand, `{colors.gap}`) · `completed` Completed (check, `{colors.resolved}`) · `failed` Failed (x-circle, `{colors.blocker}`) · `cancelled` Cancelled (slash, neutral) |
| Task | `queued` Queued · `running` Running · `completed` Done · `failed` Failed · `timed_out` Timed out (`{colors.blocker}`) · `skipped` Skipped (neutral) |
| Gap / Unknown | `open` Open (circle-help, `{colors.gap}`) · `answered` Answered (check, `{colors.resolved}`) · `converted` Converted (arrow-right, neutral) · `dismissed_with_reason` Dismissed (minus, neutral) |
| Clarification Question | `drafted` Draft · `approved` Approved · `sent` Sent (send, neutral) · `answered` Answered (`{colors.resolved}`) · `unanswered` No answer (`{colors.gap}`) |
| Conflict | `open` Open (`{colors.blocker}`) · `negotiating` Negotiating (`{colors.agent}`) · `resolved` Resolved (`{colors.resolved}`) · `escalated` Escalated (arrow-up, `{colors.gap}`) |
| Finding | `open` Open (`{colors.blocker}` if critical, otherwise neutral) · `resolved` Resolved · `overridden` Overridden (shield, neutral) |
| Estimate Version | `draft` Draft · `submitted` Submitted · `in_review` In review (eye, `{colors.agent}`) · `approved` Approved (`{colors.resolved}`) · `rejected` Rejected (`{colors.blocker}`) · `superseded` Superseded (neutral, struck-through label) |
| Review Request | `pending` Pending (`{colors.gap}`) · `approved` Approved · `rejected` Rejected · `challenged` Challenged (message, `{colors.gap}`) · `superseded` Superseded · `cancelled` Cancelled |

## Interaction Primitives

**Keyboard first, mouse complete.** Every action is reachable by mouse. Power users never need to reach for it.

- `⌘K` / `Ctrl+K`: command palette
- `g i` / `g m` / `g a` / `g k` / `g r`: go to Inbox, My Opportunities, All Opportunities, Knowledge, Reports
- `1`–`9`: switch Opportunity tab
- `j` / `k`: move selection; `Enter`: open in inspector; `Esc`: close the topmost layer
- `x`: multi-select; `e`: edit the selected item; `c`: create in context (Requirement, Source, Gap question)
- `]`: toggle activity rail; `v`: version list; `d`: diff toggle (Estimate)
- `?`: shortcut cheat sheet

**Rules:**
- Saves are optimistic on blur, with server confirmation.
- Any save the server rejects rolls back with an inline reason.
- Drag-and-drop is used only for file upload. Rows are not reordered by dragging.
- Hover-only affordances always have a focus equivalent.
- Undo (`⌘Z`) is available for the last inline edit on draft items only. Submissions, approvals and Baselines can't be undone, which is why they ask for confirmation.

## Accessibility Floor

This section covers behaviour. Visual contrast comes from `DESIGN.md` and the shadcn defaults.

- WCAG 2.1 AA (PRD NFR-7), with axe checks in CI.
- Every shortcut has a visible control equivalent. Single-key shortcuts can be turned off in Settings (WCAG 2.1.4).
- Tab order follows reading order: sidebar → tab strip → main → right pane.
- Focus moves into the inspector when it opens and returns to the originating row when it closes.
- Live updates are announced through a polite `aria-live` region: run status changes, blocker count changes, and "waiting for you". Bursts of agent progress are throttled to one announcement every 5 s.
- The running dot respects `prefers-reduced-motion`.
- Status is never conveyed by colour alone (an icon and a label always accompany it).
- Estimate grid cells are navigable with arrow keys, and screen readers announce row and column headers.

## Responsive & Platform

| Width | Behaviour |
| --- | --- |
| ≥ 1440px | All three panes docked: sidebar, main, and inspector or activity rail. |
| 1280–1439px | The inspector and rail overlay the main pane. The sidebar can be collapsed (`[`). |
| 1024–1279px | The sidebar collapses to icons. Overlays as above. A best-effort tier. |
| < 1024px | A read-only notice: "The workbench needs a wider screen. You can view Opportunities here, but editing is disabled." |

Light and dark themes follow the system preference, with a manual override in Settings. Comfortable or compact density is a setting (32px or 28px rows).

## Inspiration & Anti-patterns

- **Taken from Linear:**
  - Keyboard-first navigation (`g` shortcuts, `j`/`k`, `⌘K`).
  - A dense list with an inspector peek.
  - A status-pill vocabulary.
  - Quiet neutral surfaces where colour means state.
  - Instant, optimistic interactions.
- **Taken from code-review tools:** diffs between Estimate Versions, Challenges as review comments with a required reason, and "superseded" states.
- **Taken from spreadsheets:** the Estimate grid feels like Excel for navigation and inline editing, but totals are server-calculated and locked.
- **Rejected: wizard or stepper flow.** The engineer jumps where the work is. The Overview's Submission Blockers list provides the guidance a wizard would.
- **Rejected: chat-first "talk to your AI" interface.** Agents produce structured Findings with Evidence. A chat window would hide traceability.
- **Rejected: personified agents, avatars and AI sparkle icons.** Agents are named by role, and output is judged on Evidence.
- **Rejected: auto-applied AI changes.** Every agent output is a proposal shown with its Evidence. Human edits are never overwritten (pending changes instead).

## Key Flows

Protagonists follow the PRD user journeys.

### Flow 1: Ravi turns a messy discovery call into an estimate he can defend (UJ-1)

1. Ravi (presales engineer) presses `c` on My Opportunities, names the Opportunity, and lands on Overview.
2. He drags in a Teams transcript and two emails. The Requirements badge counts up as extraction streams in. The activity rail shows "Intake: extracting 3 sources".
3. He presses `4`. Nine Gaps are ranked by impact, each with a drafted Clarification Question. He edits two inline, multi-selects seven with `x`, approves them, and exports them for the sales rep.
4. Two days later the answers arrive as a new Source. The answered Gaps turn green and two locked Requirements show pending changes, which he accepts. He presses **Run assessment** on Overview.
5. The activity rail shows the Engineering, PM and Security Agents running in parallel, then Critic and Red Team. A red Red Team Finding appears: "ERP custom fields — no evidence the connector supports them."
6. He opens the Finding, reads the Evidence chip, and converts the related Unknown into a priced Contingency.
7. **Climax:** he presses `1`. The Submission Blockers list empties item by item as he accepts the last two Assumptions, then reads **"0 blockers — ready to submit"**. In the Estimate tab, every Contingency line links to its Assumption, and every Assumption links to the Gap or Finding it came from. He submits and requests review from engineering.

**Failure:** the Security Agent times out. Its row shows a red "failed: model timeout" pill with **Retry** while the other results stay in place. Ravi retries and the run completes.

### Flow 2: Lena challenges an integration effort she doesn't believe (UJ-2)

1. Lena (engineering reviewer) sees "Review: Ravi's Estimate v2" in her Inbox and presses `Enter`.
2. The review panel shows the integration line, its Engineering Assessment and the Evidence. She clicks the Evidence chip and sees that the connector document is for an older version.
3. She presses **Challenge**, writes "Connector needs v5 upgrade; doc cited is v4," and submits.
4. Ravi gets a **Confirm reassessment** item suggesting two affected Assessments, both pre-ticked. He confirms. The activity rail shows the reassessment run, followed by the Critic and Red Team rerunning.
5. **Climax:** Ravi gets an Inbox item: "v3 created from Lena's Challenge (+3 weeks on ERP integration)". He opens the diff. The old v2 review request shows "Superseded by v3". Lena approves v3, and her Challenge and the delta sit in the Trace tab. The Overview gate now reads "0 blockers to Baseline". Ravi presses **Set Baseline** and confirms, and v3 now carries the Baseline marker.

**Failure:** Lena tries to approve while Ravi is editing the same version. She gets an inline 412 message, opens the diff, sees his change, and approves the new state.

### Flow 3: Ravi resolves a conflict between agents (UJ-3)

1. The Conflicts badge shows 1. Ravi presses `6`.
2. Two positions sit side by side: the Engineering Agent says 4 weeks, the PM Agent says 7 weeks because of customer UAT cycles, each with Evidence.
3. **Climax:** he chooses the PM position, types "Customer confirmed two UAT rounds," and confirms. The Conflict closes, the Estimate line updates in the background, and the blocker count drops by one. Both positions remain in the Trace.

R3 variant: a Negotiation proposal sits on top ("6 weeks if UAT environment is ready by Week 2"). Ravi accepts it, which adds a Condition to the Assumptions Register.

### Flow 4: Ravi tests whether a phased rollout de-risks the deal (UJ-4, R3)

1. In the Estimate tab, Ravi opens the Scenarios switcher and presses **New Scenario from Baseline**.
2. In the inspector he changes the constraints: phase 2 integrations deferred, and a budget cap set. The Scenario appears as "Scenario A (draft)".
3. Only the affected agents rerun. The activity rail shows the Engineering and PM Agents, then the Critic and Red Team.
4. With the Baseline and Scenario A selected, he presses `d`. The diff shows effort, timeline, cost, Risks and Assumptions side by side.
5. **Climax:** he requests commercial approval on Scenario A. Once it's approved, **Promote to Baseline** becomes available. Promoting moves the Baseline marker to the Scenario's version. The original Baseline stays in the version list, unchanged.

**Failure:** a Scenario rerun hits its token budget. The Scenario shows the "Run stopped" banner and keeps its partial results. The Baseline is untouched.

### Flow 5: Sam finds out why a project overran (UJ-5)

1. Sam (Head of Delivery) opens Reports. A variance table groups projects by integration type, with one project at +35%.
2. Sam clicks the row, lands on the Opportunity's Actuals tab, and sorts by variance. The overrun sits on the ERP integration line.
3. **Climax:** Sam clicks the line's Assumption, "Customer provides API access by Week 1 (Condition)", and the inspector shows who accepted it, when, and the Evidence behind it. In the Trace tab, filtered to this Assumption, Sam sees the full chain from Gap to Clarification Question to the customer's answer to the Condition, without asking anyone.

## Open Questions

1. **Brand.** Is there a company brand or logo the tool must follow? This draft uses its own restrained identity `[ASSUMPTION]`.
2. **Default landing page.** My Opportunities for presales engineers. Should reviewers land on Inbox instead `[ASSUMPTION: role-based default]`?
3. **Reports scope for R1.** Is the variance table and drill-down enough for the Head of Delivery, or are charts needed?
