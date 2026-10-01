# Epic 1 Context: Secure workspace on the production server

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Stand up the platform foundation that every later epic builds on. That means a scaffolded monorepo with pinned versions, production deployment to a single EU Ubuntu GPU VPS from day one (CI/CD, backups, monitoring, alerts), and the shared platform layer: Unit of Work, authorization, append-only trace, error mapping and optimistic concurrency. On top of that the epic delivers Auth0 sign-in with roles managed in the app, the Linear-style app shell with design tokens, and the first business feature: creating and sharing Opportunities inside a tabbed workspace with a derived status. When it is done, the team can sign in, create Opportunities, share them only with collaborators, and work in a dense, keyboard-first UI on the real server.

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

- **Opportunities:** a presales engineer creates an Opportunity (customer, products in scope, industry, target proposal date) and becomes its owner. They add or remove collaborators. Only the owner, collaborators and policy-granted roles can see it. Everyone else gets a 404-equivalent response with no details leaked.
- **Basic at-a-glance status:** status, owner, collaborators and created date. Blockers, Gaps and Conflicts come in later epics.
- **Sign-in and roles:** Auth0 sign-in is mandatory. Roles: presales engineer, sales representative, engineering reviewer, PM reviewer, security reviewer, commercial, delivery manager, Head of Delivery, platform administrator. A user's first login provisions a user with no roles, who sees only an "ask an administrator" message. At least one platform administrator must always remain. Role changes take effect on the user's next request.
- **Security:** authorization is checked on every sensitive operation, and the UI is never the enforcement point. Data is encrypted in transit (automatic TLS) and at rest (full-disk encryption, or encrypted volumes for postgres and storage). Secrets are never in plaintext in the repo, image layers or logs.
- **Observability and privacy:** a correlation ID on every request. Logs are structured JSON with IDs only and never contain customer content. All data stays on the EU server. Nothing is sent to a SaaS tracer.
- **Reliability and operations:** nightly encrypted off-site EU backups (pg_dump, storage volume, Caddy data, sops key escrow) kept for 35 days. RPO 24 h, RTO 4 h. A tested restore runbook. Email alerts within 5 minutes on a failed healthcheck, disk above 80%, a certificate expiring within 14 days, or a failed backup. The alert channel must be reusable (dead jobs are added in Epic 2).
- **Platform target:** desktop Chrome and Edge, minimum width 1280px, read-only below 1024px. WCAG 2.1 AA, checked by axe in CI.
- **CI gate:** backend lint, type check and pytest, plus web lint, type check and build, block merges. An architecture test fails if anything outside `orchestration/` imports `langgraph`, or if any module imports another module's `domain` or `adapters` package.

## Technical Decisions

- **Shape:** a modular monolith. One Python backend package and image, run as `api` (HTTP only) and `worker` (jobs only), plus a Next.js web app. Each module under `backend/app/modules/<m>/` has four layers: `api/`, `application/` (with `public.py`), `domain/` and `adapters/`. Source tree: `backend/app/{modules,orchestration,agents,platform}`, `main_api.py`, `main_worker.py`, `migrations/`, `tests/`, plus `evals/`, `web/` (generated client in `src/lib/api`) and `ops/`.
- **Table ownership:** each table is owned by one module and prefixed with it (`opportunities_*`, `identity_*`; `platform_*` for platform). Only the owner's adapters touch a table. Cross-module access goes only through `public.py` commands and queries that return Pydantic DTOs.
- **Mutation path:** command → `identity.authorize(actor, action, resource)` → domain rules → `row_version` check → write → `platform.trace.append(uow, event)`, all inside one `platform.uow` transaction.
  - `public.py` commands take the Unit of Work as their first argument and join the caller's transaction.
  - Commits happen only at the edge (request handler or job runner).
  - External I/O never happens inside an open Unit of Work.
- **Trace:** `platform_trace_events` (`id, opportunity_id nullable, workflow_run_id?, actor_type user|agent|system, actor_id, event_type, subject_type, subject_id, subject_version?, payload jsonb, occurred_at`).
  - Every event type has one Pydantic payload model in `platform/trace/catalogue.py`.
  - The application DB role has no UPDATE or DELETE on this table.
  - Admin events (role changes, user provisioning) use `opportunity_id = null`.
- **Identity:** Auth0 EU tenant, used for identity only (no Auth0 RBAC).
  - Web: `@auth0/nextjs-auth0` v4 `Auth0Client` with Next.js 16 `proxy.ts`, requesting access tokens for the API audience. Sign out ends both the app session and the Auth0 session.
  - API: PyJWT `PyJWKClient` checks RS256, JWKS, `iss`, `aud` and `exp`, then maps `sub` to a platform user.
  - Roles and Opportunity membership live in `identity`. The action catalogue (`identity/actions.py`) names actions `<module>.<entity>.<verb>`.
- **API contract:**
  - REST JSON under `/api/v1`. The health check is `GET /api/v1/health`, which returns the build version.
  - Errors are problem+json `{type, title, status, code, detail, instance}`, with domain exceptions mapped in one place. Missing or bad tokens return 401 with a stable `code`, and non-admins get 403 on admin endpoints.
  - Mutable rows require `If-Match` and return 412 on mismatch.
  - The web app uses only the TS client generated from the OpenAPI spec. SSE only, no WebSockets.
- **Conventions:**
  - UUIDv7 IDs. `timestamptz` in UTC, ISO-8601 with `Z`. `snake_case` everywhere.
  - Trace events are named `<module>.<entity>.<past_tense_verb>` (e.g. `opportunities.opportunity.created`, `identity.user.provisioned`, `identity.user.role_assigned`).
  - Config uses `pydantic-settings` with the `PSA_` prefix, read only in `platform.config`.
  - Tests use pytest, with domain tests running without a DB.
- **Opportunity status** is derived by a query and never stored. Values: intake, gaps_open, assessing, estimating, in_review, baselined, delivered, closed.
- **Deployment:**
  - One `compose.yaml` defines `proxy` (Caddy), `web`, `api`, `worker`, `postgres` (`pgvector/pgvector:0.8.6-pg18-trixie`), `ollama` (GPU via NVIDIA Container Toolkit), `otel-collector` and a one-shot `migrate` (Alembic, expand/contract only).
  - Only `proxy` publishes ports 80 and 443. Every service has a healthcheck and `restart: unless-stopped`.
  - Environments are `local` (same compose file) and `prod`.
- **Build, deploy and secrets:**
  - GitHub Actions builds images and pushes them to GHCR with immutable tags.
  - `ops/deploy` deploys by digest after taking a `pg_dump`. `--rollback` redeploys the previous digest. A failed migration aborts the deploy and leaves the old version running.
  - Secrets are a sops/age-encrypted file in the repo, decrypted at deploy into a root-only env file.
  - `unattended-upgrades` is enabled, and the monthly patching procedure is documented in `ops/runbooks/patching.md`.
- **Telemetry:** OpenTelemetry exports to the local `otel-collector`, which writes files with 30-day retention.
- **Pinned stack:**

  | Area | Versions |
  | --- | --- |
  | Backend | Python 3.13, FastAPI 0.142.2, Pydantic 2.13.5, SQLAlchemy 2.1.1, Alembic 1.20.0, psycopg 3.3.6, PyJWT 2.15.1, opentelemetry-sdk 1.45.0 |
  | Database | PostgreSQL 18.6, pgvector 0.8.6 |
  | Web | Node 24 LTS, Next.js 16.3.8, React 19.3.0, Tailwind 4.3.3, shadcn/ui CLI 4.21.0, @auth0/nextjs-auth0 4.31.0 |
  | Infrastructure | Caddy 2.11.4, Ubuntu 24.04 LTS |

## UX & Interaction Patterns

- **Tokens:** add the DESIGN.md deltas on top of shadcn/ui's neutral base, with light and dark pairs.
  - Primary Indigo `#4F5BD5` (dark `#7C86E8`): one primary action per view.
  - Semantic colours: blocker, gap, agent, resolved. Blocker Red is only for items that block submission or Baseline.
  - Inter at 13px body text with tabular figures. Radii 4/6/8.
  - Density: 32px or 28px rows, sidebar 220px, inspector 420px, activity rail 300px.
  - Contrast must meet AA: 4.5:1 for text, 3:1 for icons. Any new colour token must state its ratio.
- **Shell:**
  - Sidebar: Inbox, My Opportunities, All Opportunities, Knowledge, Reports, Admin (Admin only for admins).
  - Main pane, plus a right pane (inspector or activity rail) toggled with `]`.
  - Default landing page: My Opportunities for presales engineers, Inbox for reviewers.
  - Theme follows the system with an override in Settings, and density can be switched.
- **Keyboard:**
  - `⌘K`/`Ctrl+K` opens the command palette. `g`+letter navigates, `?` opens the cheat sheet, and `Esc` closes the top layer.
  - `1`–`9` switch tabs. `j`/`k` and Enter move through and open list rows, and `c` creates.
  - Single-key shortcuts can be turned off.
- **Responsive tiers:**

  | Width | Behaviour |
  | --- | --- |
  | ≥1440px | All three panes docked |
  | 1280–1439px | Right pane overlays the main pane; sidebar collapsible with `[` |
  | 1024–1279px | Sidebar collapses to icons |
  | <1024px | Read-only notice |

- **Lists:** 32px rows. Hover and focus show row actions. The selected row gets a 2px primary left bar. Lists are paginated, with no infinite scroll. Skeletons show for at least 150 ms on first load. Empty state: "No Opportunities yet. Press c to create one."
- **Workspace:** a header with title, status pill, owner, collaborators and target date. A nine-tab strip: Overview, Sources, Requirements, Gaps, Assessments, Conflicts, Estimate, Trace, Actuals. Tabs whose features don't exist yet show "Not available yet" rather than being hidden. Follow `mockups/opportunity-overview.html`, but the UX specs win where they differ.
- **Status pill:** always an icon plus a label plus a colour token, never colour alone.
- **States:**
  - Concurrent edit (412): an inline "Changed by [user]…" message with Reload or view diff. Nothing is overwritten silently.
  - Permission denied: hide actions the user can't take. Direct URL access shows "You don't have access to this Opportunity".
  - Inline edits save on blur with `If-Match`.
- **Accessibility:** tab order runs sidebar → main → right pane. A polite `aria-live` region is mounted for later announcements.
- **Voice:** use glossary terms exactly. Give specific failure reasons. No emoji or celebration copy.

## Cross-Story Dependencies

- 1.1 comes first: everything depends on the scaffold, compose stack and CI. 1.2 (deploy) and 1.3 (backups, alerts, OTel) build on 1.1.
- 1.4 delivers the platform core (UoW, trace, authorize, row_version/412, problem+json) as well as authentication. Stories 1.6–1.8 and all later module commands depend on it.
- 1.5 (shell and tokens) is needed before 1.6–1.8. 1.6 (roles) gates role-based access in 1.7. 1.7 (Opportunities) comes before 1.8 (workspace).
- **Later epics depend on this one:**
  - Epic 2 adds the job queue, worker and dead-job alerts to the alert channel from 1.3, and SSE live updates.
  - Epic 8 adds blockers to the Overview.
  - Epic 9 builds the Decision Trace UI on the trace layer from 1.4.
  - Later tabs replace the "Not available yet" placeholders.
