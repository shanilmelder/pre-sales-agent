# Epic 1 Context: Secure workspace on the production server

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give the presales team a secure, production-hosted workspace from day one. People sign in with Auth0, administrators assign roles, and presales engineers create Opportunities and share them with collaborators, inside a dense, keyboard-first, Linear-style app shell. The platform runs on the single EU production VPS with CI/CD, deploy-by-digest with rollback, encrypted secrets, backups, monitoring and alerts. This epic also lays the platform core that every later epic depends on: the Unit of Work, the append-only trace, central authorization, optimistic concurrency and one error format.

## Stories

- Story 1.1: Project scaffold and local stack
- Story 1.2: Production deployment to the VPS
- Story 1.3: Backups, monitoring and alerts
- Story 1.4: Sign in with Auth0
- Story 1.5: Linear-style app shell and design tokens
- Story 1.6: Administrator assigns roles
- Story 1.7: Create and share Opportunities
- Story 1.8: Opportunity workspace with tabs and status

## Requirements & Constraints

- A presales engineer creates an Opportunity (customer, products in scope, industry, target proposal date) and adds collaborators. Only the owner, collaborators and roles that policy grants can see it. Anyone else gets a 404-style response that leaks nothing.
- Users with access see the Opportunity's derived status at a glance. In this epic that means status, owner, collaborators and dates; blockers come in a later epic.
- Roles: presales engineer, sales representative, engineering reviewer, PM reviewer, security reviewer, commercial, delivery manager, Head of Delivery, platform administrator. At least one platform administrator must always remain. Role changes apply on the user's next request.
- Security: signing in is required. Authorization is checked on every sensitive operation. Data is encrypted in transit and at rest, and sensitive operations are audited.
- Observability and privacy: every request carries a correlation ID. Logs are structured JSON with IDs only and no customer content, and data stays on the EU server.
- Platform: desktop Chrome and Edge, minimum width 1280px, read-only below 1024px. WCAG 2.1 AA, checked with axe in CI.
- Operations: RPO 24 h and RTO 4 h. Nightly encrypted off-site EU backups kept for 35 days. Email alerts within 5 minutes for a failed healthcheck, disk above 80%, a certificate expiring within 14 days or a failed backup.

## Technical Decisions

- **Modular monolith, hexagonal modules.** One Python backend image runs as `api` (HTTP only) and `worker` (jobs only). Each module has `api/`, `application/`, `domain/` and `adapters/` layers. Other modules call a module only through its `application/public.py`. Tables are prefixed with the owning module's name (`identity_*`, `opportunities_*`, `platform_*`). `identity` owns users, roles and the action catalogue. `opportunities` owns Opportunities and collaborators. `platform` owns trace events. CI architecture tests forbid importing another module's `domain` or `adapters`, and only `orchestration/` may import `langgraph`.
- **Unit of Work (AD-25, AD-3).** `platform.uow` opens one DB transaction per request or job step. `public.py` commands take the UoW as their first argument and join the caller's transaction; they never commit. Commits happen only at the edge (the request handler or the job runner). No external I/O happens inside an open UoW. Every mutation follows one path: authorize, validate domain rules, check `row_version`, write, then `platform.trace.append(uow, …)`, all inside the same UoW.
- **Trace (AD-12).** `platform_trace_events(id, opportunity_id nullable, workflow_run_id?, actor_type user|agent|system, actor_id, event_type, subject_type, subject_id, subject_version?, payload jsonb, occurred_at)`. Rows are written only through `platform.trace.append`. Every `event_type` has one Pydantic payload model in `platform/trace/catalogue.py`. Event names follow `<module>.<entity>.<past_tense_verb>`, for example `identity.user.provisioned`, `identity.user.role_assigned`, `identity.user.role_removed` and `opportunities.opportunity.created`. Events with no Opportunity, such as role changes, use `opportunity_id = null`. The application DB role has no UPDATE or DELETE on this table.
- **Authorization (AD-15).** Every decision goes through `identity.authorize(actor, action, resource)`, called inside commands and queries; the UI never enforces access. Action names follow `<module>.<entity>.<verb>`, match the command name and live in one catalogue, `identity/actions.py`. The Agent Registry uses the same names later.
- **Auth0 decisions.** Auth0 (EU tenant) handles authentication only. Auth0 RBAC is not used, so roles and Opportunity membership live in `identity`. The web app uses `@auth0/nextjs-auth0` 4.31 (v4 `Auth0Client`, Next.js 16 `proxy.ts`), sends unauthenticated visitors to Universal Login and returns them to the page they asked for. It requests access tokens for the API audience. The API validates every token with PyJWT 2.15 `PyJWKClient`, checking RS256, JWKS, `iss`, `aud` and `exp`. The `auth0-api-python` package is avoided because it is in beta. The API maps `sub` to a platform user. The first valid token provisions a user with no roles. Sign out ends both the app session and the Auth0 session.
- **Concurrency (AD-11).** Every mutable row has `row_version`. Writes require `If-Match`, and a mismatch returns 412.
- **API contract (AD-16).** REST JSON under `/api/v1`. Errors are RFC 9457 `application/problem+json` with `{type, title, status, code, detail, instance}` and a stable `code`. Typed domain exceptions are mapped to problem+json in one place, and auth failures return 401 problem+json. The web app uses only the TS client generated from the OpenAPI spec into `web/src/lib/api`. Live updates use SSE only; there are no WebSockets.
- **Conventions.** IDs are UUIDv7 serialised as strings. Times are `timestamptz` in UTC and ISO-8601 with `Z` in the API. Config uses `pydantic-settings` with the `PSA_` prefix, read only in `platform.config`. Tests use `pytest`: domain tests run without a DB, commands get Postgres integration tests.
- **Derived status (AD-26).** Opportunity lifecycle status is computed by a query and never stored.
- **Deployment (AD-19, AD-32).** One `compose.yaml` defines `proxy` (Caddy 2.11.4), `web`, `api`, `worker`, `postgres` (pgvector 0.8.6 on PG 18.6), `ollama`, `otel-collector` and a one-shot `migrate` that runs Alembic expand/contract migrations before `api` and `worker` start. Only `proxy` publishes ports 80 and 443, with automatic TLS. Every service has a healthcheck and `restart: unless-stopped`. GitHub Actions pushes images to GHCR with immutable tags. `ops/deploy` takes a `pg_dump` and then deploys by digest, and rollback redeploys the previous digest. Secrets are stored sops/age-encrypted in the repo and decrypted at deploy time into a root-only env file. OpenTelemetry goes to the local collector, which writes files with 30-day retention; nothing goes to a SaaS tracer. Pinned stack: Python 3.13, FastAPI 0.142.2, Pydantic 2.13.5, SQLAlchemy 2.1.1, Alembic 1.20.0, psycopg 3.3.6, Next.js 16.3.8, React 19.3.0, Tailwind 4.3.3, shadcn CLI 4.21.0, Node 24 LTS, Ubuntu 24.04.

## UX & Interaction Patterns

- Shell: a sidebar with Inbox, My Opportunities, All Opportunities, Knowledge, Reports and Admin (Admin shown only to admins), a main pane, and a right pane for the inspector or activity rail, toggled with `]`. Presales engineers land on My Opportunities and reviewers on Inbox.
- Tokens: the DESIGN.md colours (primary; the semantic blocker, gap, agent and resolved colours; surfaces; tints) in light and dark pairs, Inter at 13px with tabular figures, radii 4/6/8, and 32px or 28px row density. The theme follows the system and can be overridden.
- Keyboard: `⌘K`/`Ctrl+K` opens the palette, `g`+letter navigates, `?` opens the cheat sheet, `Esc` closes the top layer, `c` creates, `j`/`k` plus Enter move through and open list rows, and `1`–`9` switch workspace tabs. Single-key shortcuts can be turned off.
- Lists use 32px rows, are paginated (no infinite scroll) and show skeleton rows for at least 150 ms. The empty state is plain text, for example "No Opportunities yet. Press c to create one."
- The workspace has nine tabs (Overview, Sources, Requirements, Gaps, Assessments, Conflicts, Estimate, Trace, Actuals). Tabs that aren't built yet show "Not available yet" rather than being hidden. Layout follows `mockups/opportunity-overview.html`, and the UX spines win where they disagree with it.
- The status pill always shows an icon and a label, never colour alone. Opportunity statuses: Intake, Gaps open, Assessing, Estimating, In review, Baselined, Delivered, Closed.
- Inline edits save on blur with `If-Match`. A 412 shows an inline "changed since you opened it" message with Reload, and nothing is overwritten silently.
- Permission states: actions a user can't take are hidden. Direct URL access shows "You don't have access to this Opportunity". A user with no roles sees only "You're signed in, but you don't have access yet. Ask an administrator to assign a role."
- Below 1024px the app shows a read-only notice. Tab order goes sidebar, then main, then right pane, and a polite `aria-live` region is mounted. Copy uses glossary terms, with no emoji or celebration copy.

## Cross-Story Dependencies

- 1.1 comes before everything else. 1.2 depends on 1.1. 1.3 builds on 1.2's production stack, and later epics reuse its alert channel (dead jobs are added in Epic 2).
- 1.4 delivers the platform core (UoW, trace catalogue, `authorize`, `row_version`/412, problem+json) plus authentication. Stories 1.6–1.8 and all later epics depend on it.
- 1.5 depends on 1.4, because the shell needs a signed-in user and roles.
- 1.6 depends on 1.4 and 1.5. Users have no access until an admin assigns a role.
- 1.7 depends on 1.4–1.6. 1.8 depends on 1.7. The Overview's blockers arrive in Epic 8.
