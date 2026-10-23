---
title: 'Redesign the Admin pages to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '8d1443233b2290e575b4eb285a1fec12021caa46'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-redesign-overview-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Admin pages (Users & roles, Catalogue, Evals) don't match the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`, Admin). Each page has its own h1, an underline sub-nav, raw unstyled tables and section headings. There is also no Agents page, even though the registry API exists.

**Approach:** One "Admin" header (subtitle `PAGE_SUBTITLES.admin`) above a segmented sub-tab bar (Users and roles | Agents | Catalogue | Evals). Each tab's body is rebuilt as the mockup's card tables. The tabs stay separate routes, so `/admin/agents` is added. Everything comes from reads the web app can already make. No backend change.

## Boundaries & Constraints

**Always:**
- **Header:** title "Admin" on every Admin route, with the subtitle `PAGE_SUBTITLES.admin`. The primary action (decision: Auth0 link) is a primary-styled external link, "Invite user", to `auth0UsersUrl(...)`. It opens in a new tab (`rel="noreferrer"`), with an external-link icon and an accessible name that says it opens Auth0.
- **Sub-tab bar:** Links in a segmented control. Copy `OpportunityViews`: `bg-surface-alt`, `rounded-[9px]`, `p-[3px]`, 7px-radius items, and an active item with a surface background and `aria-current="page"`. Order: Users and roles, Agents, Catalogue, Evals.
- **Card tables:** `ui/card` (surface, border, 12px radius, shadow, overflow hidden). The header row is 12px/500 secondary text on `surface-alt`, `px-5 py-2.5`. Body rows have a top border, 20px side padding and the same column grid. All columns are left-aligned. Status pills use `ui/pill` with an icon. Footnotes are 12px secondary text below the card.
- **Users and roles:**
  - Grid `minmax(0,1fr) 190px`, columns User | Role.
  - User cell: a 32px circle avatar with initials (primary tint), the name in 500 weight and the email in 12px secondary text.
  - Role cell: one outlined chip per role (`border2`, 6px radius), or "No roles yet".
  - Keep the inspector, the j/k roving focus, focus return, pagination and the "Manage roles in Auth0" link.
  - Footnote: "First sign-in creates a user with no roles. Roles are managed in Auth0, and Opportunity access is set on each Opportunity."
- **Agents** (new, read-only):
  - Read: `GET /api/v1/registry/agents`.
  - Grid `minmax(0,1fr) 90px 170px 120px minmax(0,1.2fr)`, columns Agent | Version | Model | Status | Tool permissions.
  - Cells: Version is `current_config.semver`. Model is `model_profile` in mono 12px. Tool permissions are joined with ", " in secondary text, or "None".
  - Status pill: `active` → green "Enabled" with a check icon. `disabled` → neutral "Disabled" with a ban icon. `eval_only` → neutral "Eval only" with a flask icon.
  - Footnote: "No agent can send customer communication or approve. Disabled agents receive no tasks."
  - Empty text: "No agents registered yet."
  - Same access, 403 and unreachable handling as the other Admin pages.
- **Catalogue:**
  - One card. Header: h2 "Integration Type and Work Package catalogue" (16/600), the sub-line "Used by Checklists, Assessment lines, Estimate lines and Actuals", and a secondary-styled "New entry" button on the right (`c` shortcut kept).
  - Grid `120px minmax(0,1fr) 180px 120px`, columns Code | Name | Kind | Status.
  - Code is 12px/600 secondary text. Integration Types are listed first, then Work Packages. Retired entries show a neutral "Retired" pill.
  - Keep the inspector, create, edit, retire, reactivate and j/k.
- **Evals:**
  - Card 1, summary: a large result pill ("Passed · accepted" in green, otherwise the existing result label and tone), then "Run {date} · reference set {short} · {n} Opportunity · {n} evidence pairs pending review", then a right-aligned line with the token, GPU seconds and cost totals in bold.
  - Card 2, "Release bars": grid `minmax(0,1fr) 110px 110px 120px`, columns Bar (name plus the FR id in 12px secondary text) | Value (600 weight) | Threshold | Status. Pills: Pass green with circle-check, Fail red with circle-alert, Not measured neutral.
  - Decision (keep below): the Per Agent, Change from the previous result and History sections, plus the failure list, stay below the two mockup cards. Each is restyled as a card with a 16/600 header, and their behaviour is unchanged (selecting a History entry switches every card).
- Use existing tokens and the `ui/*` primitives. Light and dark themes both work. Every colour cue also has an icon or text.

**Never:** Show data the API lacks. That rules out Last active, user Status (Active/Invited), "Used in N Estimates", a catalogue-wide version, run numbers and `gpt-oss` model names. Also never add backend or API changes, agent enable/disable controls, or a working invite flow, and never touch other pages, the shell, tokens or `ui/*`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No agents | registry returns `[]` | Agents card shows "No agents registered yet." | N/A |
| Agent disabled | `status: disabled` | Neutral "Disabled" pill with a ban icon | N/A |
| User without roles | `roles: []` | Role cell "No roles yet" | N/A |
| Failed eval | `passed: false` | Summary pill red, failing bars red "Fail" | N/A |
| Non-admin | no `identity.user.list` | Existing "No access" page, `/admin/agents` included | N/A |
| API down / 403 | read throws | Existing unreachable / no-access message per page | Per page |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/admin/admin-nav.tsx`: rewrite as a segmented control (copy `components/opportunities/opportunity-views.tsx:23-40`). Add the Agents section and rename the label to "Users and roles". Keep `aria-label="Admin sections"`.
- `components/shell/page-header.tsx`: `PageHeader`, `PageContent`, `PAGE_SUBTITLES.admin`. Reuse it unchanged.
- `app/admin/users/page.tsx`: header becomes "Admin". Move the Auth0 link and the as-of note to the users body or footnote. Keep pagination at `:142-168` and the redirect at `:188-191`.
- `components/admin/users-table.tsx`, `users-admin.tsx`, `user-inspector.tsx`: restyle onto card rows. Keep the roving tabindex, `onOpen` and `data-user-id` focus return. Add an initials helper to `lib/admin.ts`, or reuse one if it exists (`actorInitials` in `lib/overview.ts`).
- `app/admin/agents/page.tsx` (new): copy the gating and error handling of `app/admin/evals/page.tsx`. Read `/api/v1/registry/agents` with `createServerApiClient()`. New component `components/admin/agents-table.tsx`. Types `RegistryAgent` and `AgentStatus` come from `lib/api/schema.d.ts:4534, 2136`.
- `app/admin/catalogue/page.tsx`, `components/admin/catalogue-admin.tsx`, `catalogue-table.tsx`: one card with a Kind column instead of two sections. Keep `StatusPill` (imported by `ui/pill-migration.test.tsx`), the inspector, the create form and `actions.ts` behaviour.
- `app/admin/evals/page.tsx`, `components/admin/evals-view.tsx`: Summary card and Release bars card. Reuse `lib/evals.ts` (`percent`, `thresholdLabel`, `signedPoints`, `agentName`) and keep `EvalStatusPill` exported.
- `lib/navigation.ts`: no change. Admin stays gated on `identity.user.list`.
- Tests:
  - `app/admin/{users,catalogue,evals}/page.test.tsx`: h1 is now "Admin", sub-nav `aria-current`, Release bars table name.
  - New `app/admin/agents/page.test.tsx`.
  - `components/admin/*.test.tsx`: the catalogue "Integration Types" heading becomes a Kind cell.

## Tasks & Acceptance

**Execution:**
- [x] `components/admin/admin-nav.tsx`: segmented control plus the Agents section.
- [x] `lib/admin.ts`: the initials helper and footnote copy.
- [x] Users: `app/admin/users/page.tsx`, `components/admin/users-table.tsx`, `users-admin.tsx`. Card table, "Admin" header, footnote.
- [x] Agents: `app/admin/agents/page.tsx`, `components/admin/agents-table.tsx`. New read-only tab.
- [x] Catalogue: `app/admin/catalogue/page.tsx`, `components/admin/catalogue-admin.tsx`, `catalogue-table.tsx`. Single card with a Kind column.
- [x] Evals: `app/admin/evals/page.tsx`, `components/admin/evals-view.tsx`. Summary and Release bars cards, plus the decision on the extra sections.
- [x] Tests: update the admin page and component tests, add the Agents page test with one case per matrix row, and keep the axe checks.

**Acceptance Criteria:**
- Given an admin on any Admin route, when the page renders at 1440px, then the header, sub-tab bar and card match the mockup in light and dark.
- Given the sub-tab bar, when a tab is activated, then it navigates to that route and marks it `aria-current="page"`.
- Given the users or catalogue table, when using j/k and Enter, then the inspector opens as before.
- Given lint, typecheck, tests and build, when run in `web/`, then all pass.

## Implementation Notes

- Card tables are ARIA tables (`role="table"`/`row`/`columnheader`/`cell`) laid out with CSS grid, in a new shared `components/admin/card-table.tsx` (`CardTable`, `HEAD_ROW`, `BODY_ROW`, `FOOTNOTE`). Native `<table>` cannot share one grid template per row.
- The header is a new `components/admin/admin-header.tsx` (`AdminHeader`), used on all four routes. The accessible name of "Invite user" is "Invite user, opens Auth0 in a new tab".
- Initials reuse `actorInitials` from `lib/overview.ts`. New copy and labels are in `lib/admin.ts` (`USERS_FOOTNOTE`, `NO_ROLES_YET`, `AGENTS_FOOTNOTE`, `NO_AGENTS`, `agentStatusLabel`, `toolPermissionsLabel`) and `lib/evals.ts` (`runSummary`).
- Users: "Roles are shown as of each person's last sign-in" and the "Manage roles in Auth0" link now sit in the footnote, below the pagination. Rows (users and catalogue) use the full-row hit area, and the selected row is `bg-primary-tint`.
- Catalogue: the Version column and the per-kind headings are gone. Rows are ordered by `groupByKind`, and "New entry" is the outline button.
- Evals: the summary drops "Critic: not available" and the draft-annotation count, and the date uses the existing `formatWhen` ("2026-10-13 21:37 UTC"). Release bars drop the "Change vs accepted" column; the change is still shown in the "Change from the previous result" card. An sr-only h2 ("Latest result"/"Selected result") marks which result is shown. The Fail icon is now circle-alert. The extra cards come in this order: Failures (only when there are any), Per Agent, Change from the previous result, History.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Release bars dropped `bar.delta` / `regressed`, so a bar failing only by regression vs the last accepted result shows Fail with no reason (blind, edge, verification) | medium | patch | `judge_bar` (`backend/app/modules/registry/domain/evals.py:92`) sets Fail when regressed against the last accepted result, while `diffRows` compares with the previous result. Fix: a "vs accepted (regressed)" line in the Bar cell. |
| Fixed grid tracks clipped by `overflow-hidden` Cards on narrow viewports; `ScrollTable`'s scroll was lost (blind, edge ×3) | medium | patch | Agents fixed tracks (380px) plus gaps exceed the content width at tablet sizes. Cards clip and there is no scroll. |
| Users/Catalogue name cells are `cell`, not `rowheader` (blind) | low | patch | Direct role change. Agents and Evals already use `rowheader`. |
| Users footnote sentence hard-coded outside `lib/admin.ts` (blind) | low | patch | Moved into a constant. |
| Catalogue code uses `text-eyebrow` letter-spacing (blind) | low | patch | `--text-eyebrow--letter-spacing: 0.04em` is not in the spec's 12px/600. |
| `runSummary` singular forms untested (verification) | low | patch | Pre-verified: only the plural fixture is asserted. |
| Failures card never rendered by a test (verification) | low | patch | Pre-verified: fixture `failures: []` in every case. |
| Summary dropped draft count and "Critic: not available" (blind) | low | rejected | The frozen block lists the summary card's contents exactly. |
| Selected row shown by tint only; avatar blends into the selected tint (blind) | low | rejected | Same pattern as before (`bg-muted`), with `aria-current` and the open inspector. A fix needs a per-state branch. |
| "Invite user" shown beside a 403 message (blind) | low | rejected | Needs a permission-vs-role mismatch, which is rare. Fixing it adds a branch to every page. |
| `AdminHeader` resolves the Auth0 URL separately from the users page (blind) | false | rejected | Both call `auth0UsersUrl(process.env.AUTH0_DOMAIN)` (`users/page.tsx:107`), so they cannot drift. |
| Agents footnote is a fixed claim (blind) | false | rejected | The copy is required verbatim by the frozen block. |
| Catalogue no longer says "None yet." for an empty kind (blind) | low | rejected | The frozen block asks for one table. The Kind column shows what exists. |
| Unknown `AgentStatus` crashes the table (edge ×2) | low | rejected | The status is a typed API enum. A new value needs `gen:api` plus code changes anyway, and guarding it adds branches. |
| `vi.stubEnv` cleanup inside the test body (blind) | low | rejected | Same pattern as the existing test at `users/page.test.tsx:171`. It leaks only if the page throws. |
| Spec verification relies on scratchpad renders; review sections empty (blind) | false | rejected | The fix would edit this build's spec. The logs are filled by this step. |
| `cn` with one argument, `text-control` outside `cn`, redundant History `aria-label` (blind) | false | rejected | Same idiom as `opportunity-views.tsx`. No user or developer harm named. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`): all pass.

**Manual checks:**
- Screenshot each Admin tab at 1440px in light and dark and compare it with the mockup renders in the scratchpad (`render/admin-*.png`).
