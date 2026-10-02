---
title: 'Story 1.5 (Part A): Design tokens and Settings'
type: 'feature'
created: '2026-10-02'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '3efb247423c4f5891803d0ffffd796d4780784c3'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-pre-sales-agent-2026-10-01/DESIGN.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The web app still uses shadcn's default neutral theme and the Geist font, and has no way to choose a theme or density. Every later screen needs the DESIGN.md token layer and these user preferences.

**Approach:** Apply the DESIGN.md tokens as Tailwind and shadcn theme tokens. Store theme, density and single-key-shortcut preferences in a cookie read on the server, and add a Settings page reached from the avatar menu. Add a web test runner (Vitest) with contrast, preference and axe tests. The app shell itself is Story 1.5 Part B (see deferred-work.md).

## Boundaries & Constraints

**Always:**
- **Colours:** use the exact DESIGN.md light/dark hex pairs: primary and primary-foreground; blocker, gap, resolved and agent; diff-tint and blocker-tint; the sidebar and inspector surfaces. The shadcn neutrals stay for background, foreground, card, popover, muted, border, input, ring and destructive.
- **Type and shape:** Inter for all text, and JetBrains Mono only for IDs, versions and excerpts. The type roles are body, body-strong, label, meta, title, section and numeric (`tabular-nums`). Radii are 4/6/8, plus full for pills and avatars.
- **Size tokens:** rows 32, compact rows 28, sidebar 220, inspector 420, rail 300, gutter 16.
- **Theme:** System, Light or Dark, defaulting to System. System follows `prefers-color-scheme` with no flash.
- **Density:** comfortable 32px or compact 28px, applied through one CSS variable.
- **Single-key shortcuts:** on or off, defaulting to on. The value is stored for Part B to use.
- **Preferences:** stored per browser in one cookie, validated on read. Invalid or missing values fall back to the defaults. The cookie is read on the server so `<html>` renders the right classes on first paint.
- **Settings:** a gated page using the Story 1.4 per-page `getMe`/`hasAccess`/`AccessGate` pattern, reached from a Settings item in the avatar menu above Sign out.

**Decisions:** Contrast beats keeping the shadcn neutral. In light mode, `--muted-foreground` is darkened to the smallest change that reaches 4.5:1 on background, card, both surfaces and both tints. Dark mode is changed only if it fails too. Blocker red is never used as text on the blocker tint; there it is a bar or icon colour only, and is checked at 3:1. The contrast test covers every muted pair with no exclusions. (The user decided this when the conflict appeared during implementation.)

**Never:** No sidebar, right pane, command palette, keyboard handling, responsive tiers or placeholder nav pages (Part B). No backend or server-side preference storage. No Playwright, and no auth bypass.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default | No cookie, OS dark | Dark tokens on first paint | N/A |
| Override | Choose Light, reload | Light on first paint, OS ignored | N/A |
| Back to System | Choose System while OS is light | Light; follows OS changes live | N/A |
| Density | Choose Compact, reload | Row token 28px | N/A |
| Shortcuts | Turn off, reload | The setting shows Off; the cookie holds it | N/A |
| Bad cookie | Malformed or unknown values | Defaults (System, 32px, On) | Ignored, no error |
| No roles | User with no roles opens `/settings` | Only the Story 1.4 no-access message | N/A |
| Contrast | Every text/surface token pair, light and dark | ≥ 4.5:1 for text, ≥ 3:1 for UI and large text | A test fails and names the pair |

</frozen-after-approval>

## Code Map

- `web/src/app/globals.css` -- class-based dark (`@custom-variant dark (&:is(.dark *))`), `@theme inline` maps `--color-*`, `:root`/`.dark` hold neutral oklch values, `--radius: 0.625rem`. Replace the primary values, add the semantic, tint, surface, size and type tokens, and set the radius scale to 4/6/8. Keep the shadcn variable names so `button.tsx` keeps working.
- `web/src/app/layout.tsx:5-13,20-28` -- `Geist`/`Geist_Mono` via `next/font/google`, fonts on `<html>`. Switch to Inter and JetBrains Mono, and add the theme and density classes from the cookie.
- `web/src/components/access-gate.tsx` -- `hasAccess`, `AccessGate`, `SignedInHeader`; reuse them for `/settings`. Its doc comment explains why gating isn't in the layout.
- `web/src/components/avatar-menu.tsx` -- `@base-ui/react/menu`, `Menu.LinkItem href="/auth/logout"`. Add a Settings `LinkItem` before it.
- `web/src/app/page.tsx` -- placeholder home; unchanged in this part.
- `web/src/lib/api/server.ts` -- `getMe()` returns `MeResult`.
- `web/src/proxy.ts` -- unchanged; `/settings` is already gated by its matcher.
- `web/components.json` -- shadcn `base-nova` (Base UI primitives). Add a radio-group or toggle-group and a switch through the CLI if needed.
- `web/package.json` -- exact versions (`.npmrc` save-exact); no test runner yet. `.github/workflows/ci.yml` web job: lint, typecheck, build.
- Toggling `System` live requires a small client script, because the server cannot know the OS theme. Use an inline `<script>` in `<head>` that sets `.dark` from `matchMedia` before paint when the theme is System, plus a listener.

## Tasks & Acceptance

**Execution:**
- [x] `web/src/lib/preferences.ts` -- `Preferences {theme, density, singleKeyShortcuts}`, `parsePreferences(raw)`, `serializePreferences`, cookie name and defaults; server reader `getPreferences()`
- [x] `web/src/app/globals.css` -- the token layer per Boundaries, light and dark
- [x] `web/src/app/layout.tsx`, `web/src/components/theme-script.tsx` -- fonts; `<html>` classes from `getPreferences()`; the no-flash System script
- [x] `web/src/app/settings/{page.tsx,actions.ts}`, `web/src/components/settings-form.tsx` -- gated page; three controls with visible labels; a server action validates and writes the cookie, then the page re-renders
- [x] `web/src/components/avatar-menu.tsx` -- Settings item
- [x] `web/package.json`, `web/vitest.config.ts`, `web/src/test/setup.ts` -- Vitest, jsdom, @testing-library/react and axe-core at exact versions; an `npm test` script
- [x] `web/src/lib/preferences.test.ts`, `web/src/lib/contrast.test.ts`, `web/src/components/settings-form.test.tsx`, `web/src/components/access-gate.test.tsx` -- cover every matrix row. The contrast test parses the hex pairs from `globals.css` and applies the WCAG formula. axe finds no WCAG 2.1 AA violations on the settings form and the gate states. `hasAccess` gets unit tests.
- [x] `.github/workflows/ci.yml` -- the web job runs `npm test` before the build

**Acceptance Criteria:**
- Given any page, when it renders, then body text is Inter 13px and numeric cells can use `tabular-nums`, with no Geist left in the build.
- Given the Settings page, when the user uses only the keyboard, then every control is reachable, labelled, and changes the preference.
- Given CI, when it runs, then lint, typecheck, tests and build pass, along with the existing compose checks.

## Implementation Notes

- Cookie `psa_prefs` holds JSON `{theme, density, singleKeyShortcuts}` (httpOnly, SameSite=Lax, one year, Secure in production). Reads are lenient per field; writes (`savePreferences`) reject anything that is not a complete valid object.
- `<html>` gets `data-theme`, `data-density` and `.dark` (explicit Dark only) from the cookie. The inline script in `theme-script.tsx` adds `.dark` for System before paint, listens for OS changes, and uses a MutationObserver to re-apply it when React re-renders `<html>` after a save (React resets `className` to the server value).
- Density is the one variable `--row-height` (32px, or 28px under `[data-density="compact"]`), exposed as `h-row`. Size tokens: `h-row-compact`, `w-sidebar`, `w-inspector`, `w-rail`, `p-gutter`. Type roles: `text-body`, `text-body-strong`, `text-label`, `text-meta`, `text-title`, `text-section`, `text-mono`, and `text-numeric` (includes `tabular-nums`). Radii sm/md/lg = 4/6/8; larger steps are capped at 8px.
- shadcn `--sidebar` and `--sidebar-primary*` point at `--surface-sidebar` and `--primary`.
- Settings controls are native radios and a `role="switch"` checkbox (no new shadcn components needed).
- Vitest 5 + Vite 8 (oxc JSX, no React plugin: `@vitejs/plugin-react` 6 has an unresolvable optional Babel peer). jsdom pinned to 29.1.1 because 30.x requires Node >= 24.15 and the local toolchain is 24.14.
- **Contrast (per Decisions):** light `--muted-foreground` darkened from oklch(0.556 0 0) to oklch(0.537 0 0), the smallest 0.001 step reaching 4.5:1 on every surface and tint (lowest: 4.52:1 on `--diff-tint`). Dark (oklch 0.708) already passes (lowest 6.01:1) and is unchanged. `--blocker` on `--blocker-tint` (4.41:1 light) is checked at 3:1 only: blocker red is a bar or icon colour there, never text.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | ECH, VG | System → Light with the OS dark leaves the page dark until reload | medium | The server `className` is `""` for both System and Light, so React doesn't patch `class`. `apply()` returns early for non-System, so `.dark` added by the script stays | patch |
| 2 | VG | `savePreferences` action untested (validation, cookie path) | medium | Every test mocks the module. Dropping the `isPreferences` guard or `path: "/"` stays green | patch |
| 3 | VG | Root layout wiring (`data-theme`, `data-density`, `.dark`, `ThemeScript`) untested | medium | No test renders `RootLayout`; removing the attribute spread stays green | patch |
| 4 | BH | Focus indicator is `ring-ring/50`, far below 3:1 | medium | `--ring` oklch 0.708 at 50% alpha on white. DESIGN names primary as the keyboard focus accent, and the custom radios and switch rely on it | patch |
| 5 | ECH, BH, VG | A rejected save goes unhandled and no failure is announced | medium | `await savePreferences` inside the transition has no try/catch, so React 19 rethrows to the error boundary | patch |
| 6 | ECH, BH | A failed save leaves the form showing an unsaved choice | low | `setPreferences(next)` is never reverted on `ok: false`; reverting is direct | patch |
| 7 | ECH, BH | The `destructive` error text pair isn't checked for contrast | low | The save-error message uses `text-destructive`; adding the pair is direct and covers the matrix "every text pair" row | patch |
| 8 | ECH, BH | Hard-coded switch `id` and a double label | low | Other ids use `useId`; direct correction | patch |
| 9 | BH | The tests read `globals.css` via `process.cwd()` | low | Fails from the repo root or an IDE runner; `import.meta.url` is direct | patch |
| 10 | BH | The published-ratio test omits `resolved` | low | Its own comment lists 5.0/4.7; two asserts | patch |
| 11 | BH | Fast toggles can save out of order | maybe-false | Next.js queues a client's server actions in order; would be low | reject |
| 12 | ECH, BH | Safari before 14 lacks `addEventListener` on `MediaQueryList` | false | Supported browsers are desktop Chrome and Edge (NFR-8) | reject |
| 13 | ECH | Secure cookie dropped over plain HTTP in a production build | low | `localhost` counts as a secure context; only HTTP-by-IP is affected, which is not a supported setup | reject |
| 14 | ECH | Spec names `vitest.config.ts`, the file is `.mts` | low | The fix edits this build's spec | reject |
| 15 | BH | Unselected radio and switch track lack 3:1 boundaries | false | The native radio dot identifies each option; the switch track (`muted-foreground`, `primary`) is already at ≥4.5:1 | reject |
| 16 | BH | The cookie read in the root layout makes every route dynamic | low | Every page is already per-request (`getMe` reads the session) | reject |
| 17 | BH | `savePreferences` has no auth check | false | It only writes the caller's own cookie; there is no cross-user effect | reject |
| 18 | BH | The missing-`matchMedia` test proves only that the error is swallowed | low | No named harm | reject |
| 19 | BH | `text-numeric` duplicates values; `.dark` repeats sidebar vars; radii above 8px aliased | low | Drift risk only; the radius cap is intended (DESIGN max 8) | reject |
| 20 | BH | `/settings` signed-out and unavailable states and the avatar Settings link untested | low | Same gate code, tested via `AccessGate`; the link is static markup | reject |
| 21 | BH | Patch omits the lockfile and the docs deletion | false | The lockfile is deliberately excluded from the review diff; the docs deletion is the user's own unrelated change | reject |

## Verification

**Commands:**
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
- `docker compose --profile local up --build --wait -d` -- expected: healthy; `curl -I localhost:3000/settings` gives 307 to `/auth/login?returnTo=%2Fsettings`

**Manual checks (human, signed in with a role):**
- Avatar menu → Settings. Switching theme and density and reloading keeps the choice with no flash; System follows an OS theme change live.
