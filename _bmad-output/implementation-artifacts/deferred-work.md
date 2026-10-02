# Deferred Work

- source_spec: none
  summary: Story 1.4 Part B — Auth0 sign-in (proxy.ts redirect to EU Universal Login, API RS256/JWKS token validation with 401 problem+json, first-login user provisioning with no roles and `identity.user.provisioned` trace event, no-access screen, sign-out of app and Auth0 sessions).
  evidence: Split from Story 1.4 at user request; independently shippable from the platform-core primitives (Part A) and depends on Part A's `platform.uow` and `platform.trace.append`.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-4b-auth0-sign-in.md`
  summary: Add a web test runner and unit tests for the access gate (`hasAccess`, `AccessGate`, `getMe` result mapping) and `proxy.ts` (public paths, `/auth/*` pass-through, `returnTo`).
  evidence: Review finding #9. `web/` has no test runner (Story 1.1 chose lint, typecheck and build only), so turning `roles.length > 0` into `>= 0` would pass CI. Natural home is Story 1.5 (app shell, axe accessibility checks in CI).
