# Deferred Work

- source_spec: none
  summary: Story 1.4 Part B — Auth0 sign-in (proxy.ts redirect to EU Universal Login, API RS256/JWKS token validation with 401 problem+json, first-login user provisioning with no roles and `identity.user.provisioned` trace event, no-access screen, sign-out of app and Auth0 sessions).
  evidence: Split from Story 1.4 at user request; independently shippable from the platform-core primitives (Part A) and depends on Part A's `platform.uow` and `platform.trace.append`.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-4b-auth0-sign-in.md`
  summary: Add a web test runner and unit tests for the access gate (`hasAccess`, `AccessGate`, `getMe` result mapping) and `proxy.ts` (public paths, `/auth/*` pass-through, `returnTo`).
  evidence: Review finding #9. `web/` has no test runner (Story 1.1 chose lint, typecheck and build only), so turning `roles.length > 0` into `>= 0` would pass CI. Natural home is Story 1.5 (app shell, axe accessibility checks in CI).
- source_spec: `_bmad-output/implementation-artifacts/spec-1-5a-design-tokens-and-settings.md`
  summary: Story 1.5 Part B — app shell: sidebar (Inbox, My Opportunities, All Opportunities, Knowledge, Reports, Admin for platform_administrator only), right-pane container toggled with `]`, `⌘K` palette, `g`+letter navigation, `?` cheat sheet, `Esc` layering, single-key toggle honoured, EXPERIENCE.md responsive tiers and the <1024px read-only notice, placeholder pages, landmarks/tab order/polite live region, and axe checks in CI.
  evidence: Split from Story 1.5 at user request because the full spec was about 2,200 tokens. Decided already: landing — presales_engineer → My Opportunities, everyone else (all reviewer and other roles) → Inbox; axe runs component-level with Vitest + jsdom + axe-core (the runner arrives in Part A), not Playwright with an auth bypass.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-7a-create-and-share-opportunities.md`
  summary: Story 1.7 Part B — All Opportunities filters (status, owner, product, target-proposal-date range) on the list API and the All Opportunities page.
  evidence: Split from Story 1.7 at user request because the full story was well over the size target; Part A ships create, access, collaborators and the two unfiltered lists.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-8a-opportunity-workspace.md`
  summary: Story 1.8 Part B — owner edits the title and target proposal date inline in the workspace header (PATCH `/api/v1/opportunities/{id}` with `If-Match`, new owner-only action `opportunities.opportunity.update`, `opportunities.opportunity.updated` trace event naming changed fields only, create's field rules with blank title → customer name and past date checked only when the date changes, no-op writes nothing; web saves on blur/Enter, Esc reverts, optimistic with 422 rollback, 412 "Changed by X since you opened it." with Reload).
  evidence: Split from Story 1.8 at user request because the full spec was about 2,400 tokens; Part A ships the workspace header, tabs, keys, Overview and status pill colours.
