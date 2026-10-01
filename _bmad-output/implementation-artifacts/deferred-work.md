# Deferred Work

- source_spec: none
  summary: Story 1.4 Part B — Auth0 sign-in (proxy.ts redirect to EU Universal Login, API RS256/JWKS token validation with 401 problem+json, first-login user provisioning with no roles and `identity.user.provisioned` trace event, no-access screen, sign-out of app and Auth0 sessions).
  evidence: Split from Story 1.4 at user request; independently shippable from the platform-core primitives (Part A) and depends on Part A's `platform.uow` and `platform.trace.append`.
