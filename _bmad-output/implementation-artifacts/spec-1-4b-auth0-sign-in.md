---
title: 'Story 1.4 (Part B): Sign in with Auth0'
type: 'feature'
created: '2026-10-01'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '3f92033073b578a34a05e3f5727971d84bf14982'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Anyone who can reach the platform can use it. Only known people may get in, and the API must know which platform user is calling.

**Approach:** The web app signs users in with `@auth0/nextjs-auth0` 4.31.0 through `proxy.ts` (EU tenant Universal Login, returning to the requested page). It calls the API with an access token for the API audience. The API validates that token with PyJWT `PyJWKClient`, provisions a platform user with no roles on the first valid token, and serves `GET /api/v1/me`. A user with no roles sees only the no-access message. Sign out from the avatar menu ends both the app session and the Auth0 session.

## Boundaries & Constraints

**Always:** Validate RS256 only, against JWKS, checking `iss` = `https://{PSA_AUTH0_DOMAIN}/`, `aud` = `PSA_AUTH0_AUDIENCE` and `exp`. Every auth failure is 401 problem+json with a stable `code` and a `WWW-Authenticate: Bearer` header. Provisioning runs in the request's Unit of Work and appends `identity.user.provisioned` with `opportunity_id = null`. Its payload holds no name or email. Concurrent first requests create exactly one user and one event. Roles are read from `identity` on every request. Logs carry IDs only. JWKS fetches never happen inside an open Unit of Work and never block the event loop. `/healthz` and `/api/v1/health` stay unauthenticated.

**Never:** No Auth0 RBAC, `auth0-api-python` or role-assignment UI or commands (Story 1.6). No app shell, sidebar or design tokens (Story 1.5). No secrets committed. Auth endpoints never return tokens or PII in error bodies.

**Decisions:**
- **Profile claims:** name and email come from namespaced access-token claims `https://pre-sales-agent/name` and `https://pre-sales-agent/email`, added by an Auth0 Post-Login Action. The README carries the Action code and the setup steps. A token that is otherwise valid but lacks the email claim gets 401 `token_invalid`; the `detail` says profile claims are missing. If the name claim is missing, the email is used as the name.
- **Verification:** sign-in is verified end to end against the user's real EU tenant, using values the user puts in their local `.env`. That manual check is the human's, after automated verification. The full spec scope (about 2,000 tokens) is kept by the user's choice.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Unauthenticated page | No session, `GET /some/page?x=1` | 307 to `/auth/login?returnTo=/some/page?x=1`; back on that page after login | N/A |
| Health | No session, `/healthz` | 200, no redirect | N/A |
| First valid token | Unknown `sub` | User created (name, email, no roles); one trace event; `/me` 200 `roles: []` | N/A |
| Returning user | Known `sub` | No new user or event | N/A |
| Concurrent first calls | Two requests, same new `sub` | One user, one event, both 200 | Unique `auth0_sub` + `ON CONFLICT DO NOTHING` |
| Missing token | No `Authorization` | 401 | `code: token_missing` |
| Expired token | `exp` in the past | 401 | `code: token_expired` |
| Wrong token | Bad signature, `alg` ≠ RS256, wrong `iss`/`aud`, unknown `kid`, malformed | 401 | `code: token_invalid` |
| JWKS unreachable | Auth0 down | 503 | `code: auth_unavailable` |
| No roles | User with no roles opens any page | Only "You're signed in, but you don't have access yet. Ask an administrator to assign a role." plus the avatar menu | N/A |
| Sign out | Avatar menu → Sign out | App session cleared, Auth0 logout, then the login page on the next visit | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/platform/uow.py` -- `UoW` dependency (`scope="function"`), `UnitOfWork.session`; provisioning joins it.
- `backend/app/platform/trace/catalogue.py` -- `IdentityUserProvisioned` already registered (no fields); keep it empty.
- `backend/app/platform/errors.py` -- `ProblemError`; `problem_response(..., headers=)` supports `WWW-Authenticate`; add the 401/503 auth errors here.
- `backend/app/platform/config.py` -- add `auth0_domain`, `auth0_audience` (and the JWKS cache lifespan).
- `backend/app/modules/identity/application/public.py` -- re-exports `Principal`, `Role`, `authorize`; add `CurrentPrincipal` and the read-model for `/me`.
- `backend/app/modules/identity/domain/policy.py` -- `Principal(actor, roles)`; `actor = Actor("user", str(user.id))`.
- `backend/app/main_api.py` -- `create_app` mounts routers under `API_PREFIX`; include identity's router.
- `backend/migrations/versions/20261001_0002_platform_trace.py` -- default privileges already give `psa_app` DML on new tables.
- `backend/tests/conftest.py` -- `db_app`, `sync_engine`, `make_client`, `run_async`.
- `web/src/app/layout.tsx`, `web/src/app/page.tsx` (placeholder home), `web/src/lib/api/client.ts` (`createApiClient`, `PSA_API_URL`), `web/scripts/gen-api.mjs`, `web/src/components/ui/button.tsx` (shadcn base-nova). Web deps are exact (`.npmrc` save-exact). There is no web test runner; keep it that way.
- `compose.yaml` web service (env `PSA_API_URL` only), `.env.example`, `.github/workflows/ci.yml` compose job (builds web from `.env.example`, curls `/healthz`).

## Tasks & Acceptance

**Execution:**
- [x] `backend/pyproject.toml`, `backend/uv.lock` -- add `pyjwt[crypto]==2.15.1`
- [x] `backend/migrations/versions/20261001_0003_identity_users.py`, `backend/app/modules/identity/adapters/{models,repository}.py` -- `identity_users(id uuid7 pk, auth0_sub text unique, name text, email text, row_version, created_at)`, `identity_user_roles(user_id fk, role text, pk(user_id, role))`; repository: get by sub, insert-if-absent, load roles
- [x] `backend/app/modules/identity/application/{authentication,provisioning}.py`, `backend/app/modules/identity/api/routes.py` -- token validation (`PyJWKClient` in a thread, `algorithms=["RS256"]`, required claims); `CurrentPrincipal` dependency (validate → UoW → provision or load → `Principal`); `GET /api/v1/me` → `{id, name, email, roles}`
- [x] `backend/app/platform/errors.py`, `backend/app/platform/config.py` -- auth errors (`token_missing`, `token_expired`, `token_invalid`, `auth_unavailable`), settings
- [x] `backend/tests/test_auth.py`, `backend/tests/test_provisioning.py` -- every API row of the matrix, using a generated RSA key and a stubbed JWKS client; the concurrency row uses two UoWs on a real DB
- [x] `web/package.json`, `web/src/lib/auth0.ts`, `web/src/proxy.ts` -- `Auth0Client` (audience `AUTH0_AUDIENCE`); proxy mounts `/auth/*`, lets `/healthz` and static assets through, and redirects other paths without a session to `/auth/login?returnTo=<path+query>`
- [x] `web/src/lib/api/server.ts`, `web/src/lib/api/schema.d.ts` -- server-only helper that gets the access token and calls the API with `Authorization: Bearer`; regenerate the schema for `/me`
- [x] `web/src/app/page.tsx`, `web/src/components/avatar-menu.tsx` -- fetch `/me`; no roles → the exact no-access sentence; otherwise "Signed in as {name}"; avatar menu (initials, name, email, Sign out → `/auth/logout`)
- [x] `compose.yaml`, `.env.example`, `.github/workflows/ci.yml`, `README.md` -- `PSA_AUTH0_DOMAIN`, `PSA_AUTH0_AUDIENCE` for the api; `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`, `AUTH0_AUDIENCE`, `APP_BASE_URL` for the web, with placeholders so the CI build and `/healthz` work without a tenant; the README documents the tenant setup (EU region, regular web app callback and logout URLs, API identifier, and the Post-Login Action code that sets the two namespaced claims on the access token)

**Acceptance Criteria:**
- Given a valid token for a new `sub`, when `/me` is called twice, then exactly one `identity_users` row and one `identity.user.provisioned` trace row (actor `user`, `opportunity_id = null`, payload `{}`) exist.
- Given a user with a role in `identity_user_roles`, when `/me` is called, then that role is returned.
- Given CI, when it runs, then backend checks and tests, the web lint, typecheck and build, and the compose health checks all pass with placeholder Auth0 values.

## Implementation Notes

- `migrations/env.py` bug fixed: the `SELECT current_user` guard autobegan a transaction, so Alembic's `begin_transaction()` joined it and never committed; every migration silently rolled back. The guard now ends that transaction before migrating.
- The no-roles gate lives in each page (`page.tsx`, `not-found.tsx`, via `components/access-gate.tsx`), not in the root layout: Next.js renders the page alongside the layout, so a layout gate still shipped the page's content in the RSC payload.
- `CurrentPrincipal` resolves the token (and any JWKS fetch, in a thread) before the UoW dependency, so no network I/O happens inside an open UoW; a test asserts the order.
- `/api/v1/me` declares `HTTPBearer` security in OpenAPI. CI's compose job also checks `/` returns 307 to `/auth/login?returnTo=%2F` and `/api/v1/me` without a token returns 401 `token_missing`.
- Unknown role strings in `identity_user_roles` are ignored (logged with the user id) rather than failing the request.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, ECH | A token refreshed in a Server Component is never saved | medium | `getMe` → `auth0.getAccessToken()` runs in `page.tsx`/`not-found.tsx`, which can't write cookies (an SDK v4 limitation). After access-token expiry every request refreshes again, or fails once rotation is on. Fix: the SDK's documented `getAccessToken(request, response)` in `proxy.ts` | patch |
| 2 | BH, ECH | Any 401 from `/me` shows "session ended", so a misconfigured Action loops forever | medium | `server.ts` maps `status === 401` to `signed-out`, including `token_invalid` for a missing email claim. Signing in again yields the same token. Also no log on failures | patch |
| 3 | VG, BH | Production `from_settings` wiring (audience, JWKS lifespan, timeout) untested; issuer test asserts a test constant | medium | All token tests swap in a hand-built validator, so `audience=settings.auth0_domain` would pass every test | patch |
| 4 | VG | `returnTo` keeping path and query untested | low | The CI curl checks only `/`; dropping `+ search` stays green; adding one curl is direct | patch |
| 5 | ECH | Matcher gates future `public/` files and metadata routes | low | The matcher excludes only `_next/*`, favicon, sitemap and robots; a direct regex correction | patch |
| 6 | BH | RS384-labelled token and empty-string `sub` cases missing | low | The explicit `alg` check and the `_identity` empty-sub branch never run; adding parameters is direct | patch |
| 7 | BH | README Action can set an undefined name claim | low | `setCustomClaim(name, name \|\| email)` runs without an email; moving it inside the email check is direct | patch |
| 8 | ECH | `initials()` splits surrogate pairs | low | `words[0][0]` indexes UTF-16 units; `Array.from` is direct | patch |
| 9 | VG, BH | Web gate (`hasAccess`, `AccessGate`, `getMe`) and proxy have no automated tests | medium | Real. The root cause is pre-existing: `web/` has no test runner (Story 1.1 decided lint, typecheck and build only). Covered for now by the human manual checks | defer |
| 10 | BH, ECH | Name and email never updated after first sign-in | low | Real, but names and emails rarely change and the intent asks only for creation; syncing adds an update path | reject |
| 11 | BH, ECH | Empty Auth0 settings start the API without failing fast | low | Compose requires them (`:?`). Only a host run is affected; the fix adds validation and changes many tests | reject |
| 12 | BH, ECH | `proxy` drops `authResponse` cookies on the redirect | low | No session means no rolling-session cookie to keep; a stale-cookie clear is unlikely; the fix adds header copying | reject |
| 13 | ECH | Expired session during RSC navigation or prefetch | maybe-false | Next falls back to a full navigation when an RSC fetch fails; would be low | reject |
| 14 | ECH | JWKS without signing keys gives 401, and `PyJWKError` is uncaught | low | Non-JSON → `ValueError` and empty set → `PyJWKSetError` already give 503; only a JWKS of non-signing keys is left, a tenant misconfiguration | reject |
| 15 | ECH | Empty `kid` passes the guard | low | It leads to an unknown-kid 401 after one rate-limited refetch; harmless | reject |
| 16 | BH | No `Retry-After` on 503 | low | Optional header; no client retries yet | reject |
| 17 | BH | Rotation test uses cooldown 0; refetch cooldown not configurable | low | PyJWT's default cooldown applies in production; no named harm | reject |
| 18 | BH | No CHECK on `identity_user_roles.role`; no role index | low | Retired roles are deliberately tolerated (unknown roles are ignored and logged); admin queries arrive in Story 1.6 | reject |
| 19 | BH | README omits Allowed Web Origins | false | A regular web app exchanges codes server-side; web origins apply only to SPA or cross-origin auth | reject |
| 20 | ECH | "Sign in again" loses the current page | low | The fix needs the request path in a server component (headers plumbing); rare (mid-session expiry with a valid cookie) | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check` -- expected: clean
- `cd backend && PSA_DATABASE_URL=<psa_app url> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm run build` -- expected: success
- `docker compose --profile local up --build --wait -d` -- expected: all healthy; `curl localhost:3000/healthz` 200; `curl -I localhost:3000/` 307 to `/auth/login?returnTo=%2F`

**Manual checks (human, real EU tenant values in `.env`, after the README tenant setup including the Post-Login Action):**
- Open `http://localhost:3000/some/page`. Expected: Auth0 Universal Login, then back on `/some/page`.
- As a new user. Expected: only the no-access sentence and the avatar menu; one `identity_users` row and one `identity.user.provisioned` event.
- Avatar menu → Sign out, then reopen the app. Expected: the login page again, with no silent re-login.
