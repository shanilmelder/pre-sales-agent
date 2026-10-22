# Redesign v2 delta: what the added screens are

Compared: `imports/presales-agent-design-spec-standalone-v1.html` (625 KB) against `imports/presales-agent-design-spec-standalone-v2.html` (660 KB). Method: the bundle manifest (React, runtime, fonts) is byte-identical apart from asset UUIDs; the only real change is the app template (212 KB to 245 KB, +58 lines). The template was decoded and diffed line by line; no blobs were dumped. Demo personas are given by role here (organisation rule). The extract's section 5 "Gaps" list is now answered almost completely. Everything below is new or changed in v2; anything not listed is unchanged.

Not changed: Inbox base layout, Knowledge, Reports, Admin, Overview, Assessments tab body, Sources, Requirements, dialogs for Baseline and Cancel, Command palette, the colour tokens (no CSS custom property added or changed), the type scale, the keyboard-shortcut sheet content (still lists nine entries; `c` is not added to it even though v2 binds `c`).

## 1. New tokens

No new CSS custom properties. v2 reuses `--red/-t`, `--amber/-t`, `--green/-t`, `--neutral-t`, `--primary-t/-x`, `--border2`. New literal values:

| Value | Where | Notes |
| --- | --- | --- |
| `rgba(10,12,20,.55)` | Challenge dialog scrim | Dialog shadow `0 16px 40px rgba(0,0,0,.3)` reused. Scrim now specified. |
| `#fff` ink on `var(--green)` | Version lifecycle "done" node check mark | Passes in light, **fails in dark** (see section 6). |
| Dialog width 520px | Challenge dialog | Other dialogs unchanged. |
| Settings card max-width 760px | Settings | New layout width. |
| Switch 44 x 26, knob 20, radius 13 | Single-key shortcuts | Track `var(--border2)` off, `var(--primary)` on, knob `#fff`. Off track fails 3:1 (see section 6). |
| Disabled controls | Save, Rerun, Save answer | Opacity .4 and `not-allowed` (spine said .5). Disabled is contrast-exempt. |

New icons: wifi-off glyph (offline banner). Reused: alert, triangle, clock, check-circle, quote, loader.

## 2. New and changed screens

### 2.1 Settings (new screen)

- **Reached from:** the footer avatar ("AP", now a button, `aria-label="Open settings"`), and the command palette command "Open Settings" (group Navigate). Page header: title "Settings", subtitle "Saved in this browser.", **no primary action** (button hidden). Right-pane toggle remains.
- **Layout:** one card, max-width 760, three 24px sections separated by 1px borders, then a footer strip on `surface2`.
- **Theme:** radiogroup of three cards (System, Light, Dark), 10px radius, 16px dot radio, selected = primary border and `primary-t` fill. Help: "System follows your operating system's light or dark setting." System resolves through `prefers-color-scheme`. Persisted in localStorage `pa.tp`.
- **Density:** radiogroup Comfortable ("32px rows") and Compact ("28px rows"), help "Row height in lists and tables." Persisted in `pa.density`. The row figures in the labels disagree with the CSS: `--rowpad` is 12px comfortable and 6px compact, which is what the spine already says (rows about 56 to 72px). The labels read as stale text. Spine rule kept.
- **Single-key shortcuts:** switch (`role="switch"`, "On"/"Off" label), help: "Shortcuts such as c to create and j or k to move. ⌘K or Ctrl+K works either way." **Default is Off** (`sk:false`; `pa.sk`). When Off the key handler returns before every non-modified key except `Esc` and `⌘K`: `c`, `?`, `[`, `]`, `j`, `k`, `x` are all disabled. This is the WCAG 2.1.4 control.
- **Footer:** "Saved in this browser. Roles and notifications are managed by an admin." So notifications are **not** a Settings control (spine listed them).
- **Conflicts with spines:** (a) default-off vs a keyboard-first spine; (b) notifications removed from Settings; (c) Theme toggle in sidebar footer and the Settings radio now both exist (toggle theme maps to Light/Dark and updates the saved preference). `g` chords and `1`-`9` are still absent from v2's handler (restored by user decision; they must obey the same switch).

### 2.2 Estimate Version lifecycle (Estimate tab)

- **Version switcher:** every version now carries a state pill, replacing the single "Baseline" pill: v1 **Superseded** (neutral), v2 **Baseline** (green), v3 **Draft** (primary tint). 11px label, `2px 7px` padding, full radius.
- **Version lifecycle card (new):** below the switcher. Eyebrow "Version lifecycle", then a four-step stepper **Draft, In review, Approved, Baseline** with 18px round nodes joined by 24 x 2 lines. Done step: green node with check, green label, green line. Current: primary ring, `primary-t` fill, `primary-x` label weight 600. Future: `border2` ring, grey label. v1 = all four done (index 4), v2 = three done and Baseline current, v3 = Draft current. A note line below:
  - v1: "v1 is superseded by v2 and is read only. Compare it with a later version using the diff toggle."
  - v2: "v2 is the Baseline. A Baseline is replaced only by a newer approved version, and editing it creates a new version."
  - v3: "v3 is a draft built from Assessments run 2. Each edit needs a reason and creates a new Estimate Version."
- **Edit line (Inspector, new section under an Estimate line):** eyebrow "Edit line", field "Engineer effort (h)" (prefilled 70.4), field "Reason for the change (required)" (2-row textarea), primary **Save as new version** (disabled until the reason is non-empty, `aria-disabled`), helper "Creates v3.1. Earlier versions stay readable."
- **412 on a line:** red-tint `role="alert"` block above the fields: "Not saved: this line changed (412)" / "[Collaborator] saved [line ID] at 09:52. Reload to get the latest, or view the diff before you re-apply your change." Buttons **Reload**, **View diff** (secondary).
- **Conflicts with spines:** (a) spine said inline cell edit on draft, saved on blur; v2 edits through the Inspector, one reason per edit, every edit makes a new version. (b) v2 numbers a line edit "v3.1", the spine used whole numbers (v4). (c) The Edit line section is drawn for any selected version including read-only v1/v2.
- **Ties to Estimate Version statuses:** the pills reuse Draft, Baseline, Superseded. "In review" and "Approved" appear only as lifecycle steps (no version in the demo is in those states).

### 2.3 Trace detail (Trace tab and Inspector)

- Trace rows are now selectable (click, `tabindex=0`, selected row on `primary-t`); the right pane auto-opens the Inspector for Trace (`trace` added to the screens that open the pane). Row grid unchanged: When 130, Who 190, Event, Subject 190.
- **Inspector, Trace event:** header "Trace event · [time]", the event name at 16/600, an actor chip (22px avatar: 6px radius for an agent, circle for a human, initials) plus actor and "· Agent" or "· Human". Sections with eyebrow headings:
  - **Payload:** two-column key-value grid (120px keys): Event, Actor (agents show `role@1.3.0`), Subject, Estimate Version, then for an agent Correlation ID (`run-2a9f41c7`) and Model ("gpt-oss:20b (pinned digest)"), for a human Reason ("Recorded by the author at the time of the change") and Authorised by (`estimate.line.edit`).
  - **Version comparison · v2 to v3** (only for "Estimate line edited"): three rows with a sign marker, on tints: `−` on red-t, `+` on green-t.
  - **Evidence:** chips with the quote icon (agent events cite a Source and a Requirement; human events cite "Reason recorded").
  - Footer note: "Trace rows are append-only. Model reasoning is not stored, only decisions and Evidence."
- **Conflict with DESIGN.md:** the spine's Diff view rule says changed values sit on `primary-tint`, never semantic red or green. The Trace comparison uses red and green tints with `+`/`−` markers.

### 2.4 Findings (Assessments tab)

- New section "Findings" under the run content: header with a summary "1 Critical · 3 High · 2 Medium · 0 Low", and a table in a card: columns Severity 110, Type 110, Finding (flexible), Raised by 150, Evidence 60 (right-aligned count).
- Severity cell: icon plus label. Critical: alert icon, red text, **whole row on red-t**. High: triangle, amber. Medium: alert icon, text2. Low: clock icon, text2.
- Finding cell: title at weight 500; when partial, a second line in amber: "Partial result · blocks submission until resolved".
- Demo rows (six): one Critical Risk (undocumented legacy interfaces, partial), three High (two Dependency, one Risk), two Medium. Raised by is an agent role (Red Team, Engineering Agent, Security Agent, PM Agent). Types seen: Risk, Dependency.
- **No row actions** (Challenge, Override, status Open/Resolved/Overridden) are drawn, and there is no status column. The spine's Finding actions and statuses remain the carried-over rules.

### 2.5 Conflicts: Resolved section

- New card under the open Conflicts: "Resolved" with count (5). Rows: green check-circle, title, a "how" line, and a right-aligned neutral tag.
- Demo: four rows tagged "Superseded by Assessment v2" (how: "Chose PM position 24.0 h · reason recorded 20 Oct", "Chose Engineering position · reason recorded", "Chose customer figure from S1 · reason recorded", "Escalated to [reviewer] · resolved 19 Oct") and one tagged "Resolved" ("Chose SAML 2.0"). This is the Conflict **superseded** state: a Conflict resolved against an earlier Assessment version stays listed, tagged, never reopened.

### 2.6 Actuals (Actuals tab)

- When Actuals exist (default now): header "Actuals", subtitle "Hours per Estimate line with a variance cause. Estimate v3 · import from file or enter by line.", secondary **Import from file**, primary **Save Actuals**.
- Table: Line, Estimate h (right, 90), Actual h (right, 100, bordered input look), Variance (right, 130, 600), Variance cause (220, select-like bordered cell). Five demo lines (WMS interface, CRM data migration, goods-to-person picking, SSO, availability and failover). Only one line has data: estimate 36.0, actual 41.0, variance "+5.0 h (13.9%)" in **amber**, cause "Volumes larger than assumed". Empty lines show "—", variance "—", cause "Not recorded" in text2.
- Footnote: "One sample entry is shown. Empty lines are not counted in variance. Each change is added to the Trace."
- The old "No Actuals recorded" card now appears only in the `empty` demo state (see 2.8), with the action **Record Actuals**; **Import from file** exists only in the populated header.
- **Conflict:** Reports colours variance red above +10%; Actuals paints +13.9% amber. The spine's rule (red above +10%) applied to Reports only.

### 2.7 Gap Clarification Question lifecycle (Gaps tab and Inspector)

- Gap-list bulk bar: new secondary **Export questions** next to "Approve N selected".
- Inspector primary button now follows the question state, with a flow hint under it:

| Question state | Primary | Flow hint |
| --- | --- | --- |
| Draft | Approve question | "Draft, then Approved, Sent and Answered." |
| Approved | Mark as sent | "Approved. Export it, send it to the customer, then mark it sent." |
| Sent | Save answer (disabled until an answer is typed) | "Sent. Record the customer answer to close this Gap." |
| Answered | Reopen | "Answered. Related Requirements have proposed updates." |
| Dismissed | Reopen | "Dismissed with a reason." |

- When Sent: a **Customer answer** textarea (3 rows), placeholder "Paste or type the answer. Or add it as a new Source." Saving moves to Answered and clears the field. Reopen from Answered or Dismissed returns to Draft. The list row and pill update live.
- 412 on a question: "Not saved: this question changed (412)" / "[Collaborator] edited it at 09:52. Reload or view the diff." with **Reload** and **View diff**, above the question textarea.
- The earlier spine already listed Export, Mark sent and Record answer as actions; v2 supplies the interaction.

### 2.8 Empty states per tab

New `empty` demo state applies to Sources, Requirements, Gaps, Conflicts, Estimate, Actuals, Trace (Overview, Assessments not covered). Pattern: card, 64px/24px padding, centred, title 16/600, one sentence (max 440px), one primary button that jumps to the tab that fixes it.

| Tab | Title | Text | Action (target) |
| --- | --- | --- | --- |
| Sources | No Sources yet | "Add an email, transcript or document. Requirements and Gaps are extracted from Sources." | Choose files |
| Requirements | No Requirements yet | "Requirements appear after the first Source is parsed." | Add a Source (Sources) |
| Gaps | No Gaps | "Gaps appear after Requirements are checked against Checklists." | Open Requirements |
| Conflicts | No Conflicts detected | "Conflicts appear when Assessments or Sources disagree." | Open Assessments |
| Estimate | No Estimate yet | "Run Assessments to produce Estimate v1 from the confirmed Requirements." | Open Assessments |
| Actuals | No Actuals recorded | "Record hours per Estimate line with a variance cause once delivery starts." | Record Actuals |
| Trace | No trace events | "Decisions and Evidence are recorded here as work happens." | Open Overview |

Conflict with the spine's No-Estimate copy ("Run an assessment to draft one, or start from the template", actions Run assessment and Start blank): v2 offers one action and no Start blank.

### 2.9 Offline

- New demo state `offline` (cycle: normal, loading, empty, conflict, denied, offline). A full-width strip at the top of the main pane: wifi-off icon, "You are offline. You can read this Opportunity. Edits, uploads and runs are disabled until the connection returns." and a **Retry** secondary button. Treatment: `role="alert"`, `neutral-t` fill, ink text, 1px bottom border, `10px 32px` padding, 13/500.
- The earlier "Reconnecting" strip (Sources/global) is unchanged. Offline is the second stage after the spine's 60 s.

### 2.10 Review outcomes and Challenge (Inbox)

- Review panel action row: **Approve**, **Reject** (red text), **Challenge** (replaces the "More" button; opens the dialog). A second row of secondary buttons: **Request evidence**, **Request alternative**, **Escalate**. The author lock message ("You are the author, so you cannot approve.") is unchanged.
- **Review outcomes** (new section, only for the author's Review request): eyebrow "Review outcomes", list of icon rows (icon colour by result), "[reviewer] · [what]", time, optional note. Demo sequence: Approved (green check), Challenged line L1 with the reason "Contingency looks low against the 160–400 h range." (amber triangle), "[Owner] · Confirmed rerun of Engineering Agent" with "New version v3 shows L1 +14.0 h." (indigo loader), Approved after the rerun with "Delta accepted after the rerun." (green check). The request body now narrates the sequence: the first reviewer approved, the second challenged line L1, an Engineering Agent rerun followed, and the second reviewer then approved.
- **Challenge dialog (new):** title "Challenge Estimate v3" (20/600), 520px, 24px padding, scrim. Field "Reason (required)" with placeholder "State what looks wrong and why." Eyebrow "Assessments to rerun", two toggle cards (`aria-pressed`, 18px checkbox): **Engineering Agent**, why "L1 effort and contingency are the subject of the challenge", tag "Suggested" (pre-ticked); **PM Agent**, "Phasing depends on the L1 estimate", tag "Optional" (unticked). Helper: "A rerun creates a new Estimate Version and shows the delta. Conflict detection, Critic and Red Team run again." Buttons **Cancel** and **Rerun N Assessment(s)**; the primary is disabled until the reason is non-empty and at least one Assessment is ticked.
- **Conflicts with the spine:** (a) the spine had the challenger submit a reason and the owner confirm the reassessment (FR-38); v2 puts the Assessment checklist in the challenge dialog itself and labels the primary "Rerun". (b) Spine: Request evidence, Request alternative, Escalate in a More menu; v2 draws them as buttons. (c) The dialog opens from a Review request the user authored, so who sees the dialog is ambiguous. (d) The Estimate-tab Review/Challenge path is not drawn.

### 2.11 Accessibility and skip link (new, applies everywhere)

- **Skip to main content** link: first tab stop, hidden at `top:-48px`, revealed on focus at `top:8px`, white on primary. `main` has `id="main-content"` and `tabindex=-1`.
- **Polite live region** (`role="status"`, visually hidden) announces the screen name, the demo state and, on Gaps, the selected Gap.
- **Accessibility behaviours card** (new, in the component sheet, WCAG 2.1 AA), nine items: Keyboard first, Focus (2px indigo ring, 2px offset, dialogs trap and return focus), Skip link, Live announcements (polite status; alerts use `role="alert"`), No colour-only meaning, Contrast ("Text meets 4.5:1 in both themes. Tints sit behind full-strength ink, not muted text."), Motion (120ms, off under reduced motion), Targets and zoom ("Controls are at least 28px with spacing. Layout works at 200% zoom down to 1280px wide."), Tables and forms (header cells; "Required fields say Required. Errors say what to do.").
- Conflicts: v2 says tints sit behind full-strength ink. Existing semantic pills use semantic-colour text on tint (all pass 5.06 to 7.71), so the spine pairing stays; the Trace inspector and 412 body copy use ink on tint, which is v2's rule.

### 2.12 Other small changes

- Page header primary action hidden on Settings.
- Command palette: new command "Open Settings".
- Persistence: theme, density and shortcut switch persist in localStorage (try/catch guarded) as `pa.tp`, `pa.density`, `pa.sk`.
- Harness toggle list: added `offline` to the State cycle.

## 3. Contrast results for new pairs (WCAG relative luminance; AA is 4.5:1 text, 3:1 UI)

| Pair | Ratio | Verdict |
| --- | --- | --- |
| Amber `#8F5200` on surface / background / surface-alt (light): High finding, actual variance up | 6.22 / 5.82 / 5.57 | pass |
| Amber `#F3BA5C` on surface-dark / surface-alt-dark | 9.50 / 8.50 | pass |
| Green `#17753F` on surface / surface-alt (light): variance down, resolved row check | 5.75 / 5.14 | pass |
| Green `#78D6A0` on surface-dark | 9.45 | pass |
| Ink `#171A26` on neutral-tint (offline banner) / blocker-tint / resolved-tint, light | 15.20 / 15.15 / 15.24 | pass |
| Ink `#E9EBF3` on neutral-tint / blocker-tint / resolved-tint, dark | 12.00 / 12.42 / 12.07 | pass |
| Ink on primary-tint (selected Trace row) light / dark | 15.02 / 11.38 | pass |
| Text-secondary on primary-tint (light / dark) | 5.82 / 5.85 | pass |
| White check on resolved `#17753F` (lifecycle done node, light) | 5.75 | pass |
| **White check on `#78D6A0` (lifecycle done node, dark)** | **1.76** | **fail** |
| Dark ink `#14161D` on `#78D6A0` (fix) | 10.26 | pass |
| **Switch off-track `var(--border2)` `#CDD1E0` on surface (light)** | **1.52** | **fail (3:1 UI)** |
| **Switch off-track `#3A4054` on surface-dark** | **1.62** | **fail** |
| Switch off-track fixed to `border-strong` `#80869D` / `#737A94` on surface / surface-dark | 3.61 / 3.92 | pass |
| White knob on `border-strong` light / dark | 3.61 / 4.25 | pass |
| Switch on-track `#4F5BD5` on surface-dark | 3.00 | pass (at the limit; knob and the "On" label carry state) |
| Lifecycle inactive ring and connector, Challenge unticked box, textarea outline: v2 uses `border2` (1.52 / 1.62) | fail | fix with `border-strong` |
| Selected Challenge card border `#4F5BD5` on primary-tint-dark `#262B52` | 2.45 | below 3:1, state also carried by the checked box and `aria-pressed`; fix with `ring-dark` `#B3BAFF` (7.35) |
| `border-strong` on neutral-tint light / dark (offline banner rule) | 3.17 / 3.36 | pass |
| White on primary (skip link, Save buttons, checked box) | 5.54 | pass |

## 4. Resolved or touched spine items

- Resolves: EXPERIENCE `[ASSUMPTION]` that Finding rows follow the earlier spine is now partly answered (table drawn, no actions); Settings (was one line); Actuals populated view; Trace detail; Gap lifecycle copy; Conflict superseded; Estimate version states and lifecycle; offline; per-tab empty states; a11y floor concrete items.
- New open items: default of single-key shortcuts; version number scheme (v3.1 vs v4); who sees the Challenge dialog and whether it replaces Confirm reassessment; Estimate line edit surface (Inspector with reason vs inline); Edit line on read-only versions; variance colour for Actuals; Findings row actions and status in v2; Trace comparison colour.
- Still absent in v2: Findings actions and statuses, Estimate "In review/Approved/Rejected" version views, submitted-version banner, upload-rejected, parse-failed, queued, token-limit and other states already in the spine (kept).
