---
title: 'Rubric review: Architecture Spine, Agentic AI Presales Platform'
target: '../ARCHITECTURE-SPINE.md'
driving_prd: '../../../prds/prd-pre-sales-agent-2026-10-01/prd.md (+ addendum.md)'
reviewed: '2026-10-01'
lenses: ['A: good-spine rubric walk', 'B: PRD to spine reconciliation']
context: 'Fast-path draft. Single Ubuntu GPU VPS and local Ollama models are binding user decisions. [ASSUMPTION] tags are intentional and not penalised.'
---

# Rubric Review: Architecture Spine

## Verdict

**Needs revision before it drives epics.** The core is strong. Module ownership (AD-2), the single mutation path (AD-3), propose-only agents (AD-4/AD-5), the ModelGateway/ToolGateway chokepoints (AD-8/AD-9), deterministic numbers (AD-10), and versioned records with optimistic concurrency (AD-11) are the right divergence points, and their Rules are mostly enforceable. All named library versions were checked against PyPI, npm and GitHub today and are current.

The spine still leaves several real divergence points open:

- who owns Workflow Run and Task state;
- job-queue semantics;
- retention and deletion against append-only, immutable storage;
- notifications and scheduled work;
- audit of events that have no Opportunity, and of reads;
- how the SSE stream is authenticated;
- one AD-8 rule that the chosen transport may not be able to enforce.

The operational envelope is only half decided. Compose, backups and secrets are covered. CI/CD, release and rollback, upgrades, alerting, RPO/RTO and encryption at rest are not decided, deferred or listed as open questions.

| Severity | Count |
| --- | --- |
| Critical | 0 |
| High | 9 |
| Medium | 9 |
| Low | 8 |

## What holds up

- The paradigm and layer table give a mechanically checkable dependency rule (it can be enforced with import-linter).
- AD-3 + AD-12 (trace written in the same transaction, no UPDATE/DELETE grant for the DB role) is enforceable at the DB level.
- AD-6 (control data only in checkpoints, idempotency key per node command) directly addresses LangGraph replay duplication.
- AD-8/AD-22 tie gateway concurrency to `OLLAMA_NUM_PARALLEL` and the VRAM budget. This is the right control for a single GPU.
- AD-14 tags vectors with their embedding model and requires a full re-embed on model change, which prevents a mixed index.
- The user's binding decisions (VPS, Ollama) are applied consistently. The Azure path in the memlog is correctly superseded.
- **Tech verification (2026-10-01):** langgraph 1.2.12, langgraph-checkpoint-postgres 3.1.2, fastapi 0.142.2, pydantic 2.13.5, sqlalchemy 2.1.1, alembic 1.20.0, psycopg 3.3.6, pgvector 0.5.0, docling 2.131.0, pymupdf 1.28.2, extract-msg 0.56.1, opentelemetry-sdk 1.45.0, next 16.3.8, react 19.3.0, tailwindcss 4.3.3, shadcn 4.21.0, @azure/msal-browser 5.23.0 and Ollama v0.35.0 all match the latest published releases.

## Task A: Rubric findings

### High

**H1. Workflow Run, Task and Plan have no owning module or mutation path.**
- **Why it diverges:** AD-2 says every table belongs to a module, but `orchestration` sits outside the modules. The capability map assigns 4.5 to `orchestration` and `platform.jobs`, and neither is a module.
- **Contradiction:** AD-6 puts "the plan, task statuses" in checkpoint state. But FR-15 requires plans that are versioned and visible to users, FR-3 requires task status in the UI and the SSE feed, and FR-63 requires pinned input versions per run. Those are business data, not control data.
- **What teams will do:** one team will write run and task status directly from graph nodes (bypassing AD-3). Another will read status from checkpoints, and a third will mirror it into tables.
- **Fix:** add a `workflows` module that owns `workflows_runs`, `workflows_tasks`, `workflows_plans` (versioned) and the FR-63 input-version pins. Nodes change status only through its commands, and checkpoints hold only IDs. Amend AD-6 to match.

**H2. Job-queue semantics are underspecified (AD-7).**
- **Missing pieces:** "Claim with SKIP LOCKED" fixes only the claim. AD-7 does not say:
  - whether the claim holds a row lock for the whole job. Holding a transaction open across a multi-minute LLM graph is a known anti-pattern; the alternative is a lease column plus heartbeat;
  - how a crashed worker's job is reclaimed;
  - the retry and backoff policy, or the dead-letter state;
  - delayed or scheduled jobs (`run_at`), which reminders, re-sync and nightly work need;
  - per-job timeouts;
  - where AD-6's idempotency keys are stored and enforced (for example, a unique constraint on a `platform_idempotency_keys` table, or on the command's target table).
- **Fix:** extend AD-7 with:
  - a `platform_jobs` contract: `status`, `attempts`, `max_attempts`, `run_at`, `locked_by`, `lease_until`, `last_error`;
  - claim-and-commit, then run outside the lock while renewing a heartbeat;
  - reclaim when `lease_until` has passed;
  - terminal `dead` status with an admin view;
  - one idempotency table with a unique key that every `accept_*` and outbound command checks inside the AD-3 transaction.

**H3. Retention, archival and deletion are absent and collide with immutability.**
- **What the PRD requires:** PRD §10 says lost Opportunities are kept 3 years and then archived or deleted. NFR-6 says contract lifetime plus 7 years.
- **The collision:** AD-12 (no DELETE on `trace_events`), AD-18 (files immutable and content-addressed, so shared blobs are deduplicated) and the backups leave no legal path to delete anything.
- **What teams will do:** each module will improvise its own purge, or none will.
- **Fix:** add an AD for retention:
  - a per-Opportunity retention class and expiry date;
  - one privileged `retention` job running under a separate DB role, the only role allowed to delete or archive, which writes a tombstone trace event;
  - blob reference counting before deleting content-addressed files;
  - backup expiry aligned with retention.

  Alternatively, list retention as an Open Question with an owner.

**H4. Notifications and scheduled work have no substrate.**
- **What the PRD requires:**
  - FR-18: notify the engineer and admin when a limit stops a run;
  - FR-37: reminders after N days;
  - FR-40: in-app, Teams and email notifications, plus escalation;
  - FR-8: flag stale Knowledge Sources;
  - FR-55: scheduled re-sync;
  - NFR-2: no duplicate notifications.
- **What the spine has:** no notification port, outbox, in-app inbox model or scheduler.
- **Fix:** add an AD covering:
  - a `notifications` module that owns the in-app inbox, delivered through an outbox written in the same AD-3 transaction;
  - channel adapters (Teams, SMTP) behind ports, sent as idempotent jobs;
  - a single scheduler, either a worker-side cron loop that enqueues `platform_jobs` with `run_at`, or a compose `scheduler` service if AD-1 is amended.

**H5. The audit model covers only Opportunity-scoped mutations.**
- **Schema gap:** the AD-12 schema makes `opportunity_id` required. FR-56 (Agent Registry configuration changes audited), FR-65 (catalogue versioning), FR-8 (Knowledge Sources), FR-58 (role changes) and FR-57 (tool-call denials) have no Opportunity.
- **Rule gap:** AD-12 says trace rows are written only inside AD-3 commands, which are mutations. PRD §10 ("Exports are audited") and NFR-4 ("sensitive operations are audited") need audited reads too: exports and source downloads.
- **What teams will do:** they will invent their own audit tables, or store fake Opportunity IDs.
- **Fix:** make `opportunity_id` nullable, or add a separate append-only `audit_events` table with the same grant rules. Allow audited queries (export, download, admin read) to append audit rows. List the event types that are mandatory.

**H6. SSE authentication is undecided and conflicts with AD-15.**
- **The conflict:** AD-15 validates a bearer JWT on every request, and the web app gets tokens from msal-browser. The browser `EventSource` API can't send an `Authorization` header. File downloads through `<a href>` have the same problem.
- **What teams will do:** some will put the token in the query string (it leaks into proxy logs, which breaks AD-20). Others will add a cookie session, or use fetch-based SSE.
- **Fix:** decide one mechanism in AD-16. Options:
  - fetch-based SSE (for example `@microsoft/fetch-event-source`) with the bearer header;
  - a short-lived, single-use stream ticket from `POST /events/ticket`;
  - a BFF cookie session in Next.js.

  Apply the same mechanism to downloads, and strip query tokens from Caddy logs.

**H7. AD-8's `num_ctx` rule may be unenforceable through the OpenAI-compatible API.**
- **The problem:** AD-8 says the gateway speaks the OpenAI-compatible API and sets an explicit `num_ctx` on every call. Ollama's OpenAI-compatible endpoints have historically not accepted per-request `options` such as `num_ctx`. Context length comes from the Modelfile or `OLLAMA_CONTEXT_LENGTH`. This needs re-checking on v0.35.0.
- **Related risk:** structured output from gpt-oss (Harmony format) through `format` / `response_format` has had reliability problems.
- **Fix:** do one of the following:
  - set context length per model through Modelfile variants or `OLLAMA_CONTEXT_LENGTH`, and make the gateway assert it;
  - use Ollama's native `/api/chat` in the default adapter and keep OpenAI compatibility only for the vLLM path.

  Also add an R1 spike: confirm schema-constrained output with gpt-oss:20b on the eval set before the epics start.

**H8. The security envelope deviates from NFR-4 without saying so.**
- **NFR-4:** NFR-4 requires encryption at rest and secrets in a managed vault.
  - AD-19 encrypts backups only. Nothing is decided for the Postgres data directory, the storage volume or the host disk (LUKS, or provider disk encryption).
  - Secrets sit in a root-only env file. That may be acceptable for a small company, but it is an unrecorded deviation from NFR-4.
  - The custody of the backup encryption key is not specified.
- **PRD §10 residency:** "approved region, EU" is not addressed. The VPS location and the off-site backup location are not stated.
- **Fix:** add to AD-19:
  - disk encryption at rest;
  - a secrets decision: either an env file plus SOPS/age, or a vault such as Vaultwarden or Infisical self-hosted, logged as a PRD deviation;
  - an owner for the backup key and an escrow copy;
  - an EU location for the VPS and the backup target (or an Open Question).

**H9. CI/CD, release and rollback are not decided, deferred or asked.**
- **The gap:** AD-21 says "CI blocks merges", but no CI platform is named. The GitHub Actions decision from the memlog was dropped in the VPS rework. Nothing covers:
  - the image registry or tagging;
  - how a release reaches the VPS (pull and `compose up`, image digests);
  - rollback, including migration policy. With forward-only Alembic migrations, expand/contract is needed for a safe rollback;
  - where `make eval` runs, given that it needs the GPU. A hosted CI runner has none, so a self-hosted runner or an eval job on the VPS is needed.
- **Fix:** add an operations AD covering:
  - the CI host (for example GitHub Actions plus a self-hosted GPU runner on the VPS for evals);
  - the registry (for example GHCR) and immutable image tags;
  - deployment by pinned digest through a scripted `ops/deploy`;
  - expand/contract migrations;
  - rollback by redeploying the previous digest, with a pre-deploy `pg_dump`.

### Medium

**M1. Upgrades and patching are unaddressed.**
- **Gap:** nothing covers unattended OS security updates, NVIDIA driver and Container Toolkit compatibility, Docker image refresh cadence, PostgreSQL major-version upgrades (pg 18 to 19 requires `pg_upgrade` or dump and restore), Ollama upgrades, or pinning model pulls by digest. `gpt-oss:20b` is a mutable tag, and a silent re-pull changes behaviour without passing AD-21's eval gate.
- **Fix:** pin models by digest in the Agent Registry and require an eval pass to change the digest. Add an upgrade runbook rule to AD-19.

**M2. Monitoring, alerting and the OTel destination are undecided.**
- **Gap:** AD-20 emits OTel but names no collector or store. No log or trace retention is set. There are no health checks or restart policies, and nothing alerts on disk full, GPU out of memory, a failed backup, an expiring certificate or dead jobs. With one server and no HA, finding out late is the main operational risk.
- **Fix:** decide the minimum: compose healthchecks and `restart: unless-stopped`, an OTel collector writing to local files or a small self-hosted backend, and one alert channel (for example email or Teams) for those conditions. Set a log retention period.

**M3. Backup scope, RPO and RTO are undefined.**
- **Gap:** "Nightly" implies up to 24 h of data loss. That may be acceptable, but it is not stated. The scope does not say whether it includes the checkpoint schema (same DB, so yes), the host env file, Caddy certificates, or Ollama models (which can be rebuilt). A restore test is planned quarterly, but no restore runbook is named.
- **Fix:** state the RPO and RTO. Consider WAL archiving (for example pgBackRest or WAL-G) if 24 h is too much. List the backup scope and put the restore runbook in `ops/`.

**M4. The Agent Registry has no single source of truth.**
- **The conflict:** FR-56 has administrators registering agents, model and prompt versions, permissions and status at runtime, and AD-22 puts models in the registry. AD-21 puts prompts in repo files (`v<N>.md`).
- **What is undecided:** is the registry DB-backed and editable, or seeded from code? Can an administrator select a prompt version that isn't deployed? How does FR-63 capture a configuration snapshot?
- **Fix:** amend AD-21/AD-22. The registry is DB-owned by `registry`. Prompts and schemas are code artifacts, and a registry entry may reference only versions present in the deployed image. Each change creates an immutable `registry_agent_config_version` that runs pin (FR-63).

**M5. FR-6 says human edits are never overwritten by extraction, but the spine has no rule for it.**
- **Gap:** AD-11 versions Requirements but doesn't define provenance. FR-7 (incremental re-extraction) and FR-5 (merges are recorded) will diverge across intake stories unless the rule is fixed.
- **Fix:** add `origin: extracted | human` and a `locked_by_human` flag to Requirements. `accept_extraction` must never update a human-touched Requirement; it proposes a diff instead. Merges and splits are trace events with lineage.

**M6. Upload and API hardening are missing.**
- **Gap:** docling and pymupdf parse untrusted customer files. Nothing sets file size limits, MIME and type validation, malware scanning, parser isolation (a resource-limited container or subprocess), zip and decompression-bomb limits, or API rate limits. The ADs cover prompt injection but not hostile files.
- **Fix:** add to AD-18 and AD-9:
  - Caddy and API body limits;
  - an allowlist of extensions plus magic-byte checks;
  - ClamAV (optional);
  - parsing in worker jobs with CPU, memory and time limits;
  - per-user rate limits at the proxy or API.

**M7. GPU contention and fairness have no rule.**
- **Gap:** one semaphore (AD-8) serves interactive runs, bulk Knowledge ingestion (embeddings) and re-embed jobs. One large Opportunity or re-embed can starve other users and break NFR-1 (extraction in under 5 min).
- **Fix:** add priority classes to `platform_jobs` and the gateway (interactive > background ingestion/re-embed), with a per-Opportunity concurrency cap. Also state whether the embedding model and the chat model stay co-resident in VRAM.

**M8. PRD deviations are recorded only in the memlog.**
- **Gap:** the spine silently replaces several PRD statements:
  - PRD §9 and §11 (OpenAI/Anthropic model providers);
  - NFR-3 ("API services scale horizontally", "provider rate limits");
  - NFR-4 (managed vault);
  - addendum (LangSmith, WebSockets option).

  Open Question 2 covers only NFR-3 concurrency. Downstream readers of the PRD will build against the wrong constraints.
- **Fix:** add a short "PRD deviations" section that lists each change, its reason (binding user decision) and the PRD edit to request.

**M9. External-URL Evidence (AD-13) has no snapshot owner.**
- **Gap:** "Allowlisted URL captured at retrieval time" implies a stored snapshot, but no module owns it. Without one, Evidence can't be re-verified after the page changes, and the FR-19 research-source fallback has no home.
- **Fix:** `knowledge` (or a `research` sub-area) owns `research_snapshots` (URL, fetched_at, content hash, stored blob). `external_url` Evidence references a snapshot ID, not a raw URL.

### Low

- **L1. Accessibility and browser support are not assigned.** NFR-7 (WCAG 2.1 AA) and NFR-8 (Chrome/Edge desktop) are not mentioned. The Deferred "UI design system" line implies UX owns them. **Fix:** say so explicitly, and add axe or Lighthouse checks to CI.
- **L2. FR-61 detection and §9 minimisation are partly unaddressed.** FR-61 asks for prompt-injection detection "where possible". PRD §9 asks for data minimisation in prompts. AD-9 covers isolation only. **Fix:** add an optional injection-heuristic flag recorded on the Finding, plus a rule that agents receive only query results scoped to their task.
- **L3. FR-24 pricing rules service is missing from AD-17.** The integration list omits it. **Fix:** add a `pricing` port. Today it can be a table adapter.
- **L4. Stack gaps.** The table lacks:
  - the pgvector server extension version and the Postgres image (for example `pgvector/pgvector:pg18`);
  - Caddy (unpinned);
  - document-generation libraries for FR-12, FR-36 and FR-47 (for example python-docx, openpyxl);
  - a Python job/cron helper (if any);
  - confirmation that docling and torch wheels support Python 3.13 (already tagged `[ASSUMPTION]`).
- **L5. Idempotency covers only Workflow Run start.** User-initiated creates (create Opportunity, upload Source, submit Review) can double-submit. **Fix:** accept an optional `Idempotency-Key` header on POST, handled through the H2 table.
- **L6. FR-18 tool-call budgets are not enforced anywhere.** AD-8 enforces model budgets only. **Fix:** ToolGateway enforces the run's tool-call budget.
- **L7. The Opportunity lifecycle status is missing from Conventions.** The 4.1 statuses (intake ... closed) are absent, and nothing says whether status is stored or derived. **Fix:** add the enum and say whether it is derived from state or set by commands.
- **L8. Worker behaviour when the DB is unavailable is unstated (FR-19).** **Fix:** one line in AD-7 — the worker stops claiming jobs, in-flight nodes fail without committing, and the run resumes from the checkpoint.

### Deferred list check

Nothing under Deferred lets two units diverge:

- Temporal, vLLM, HA, Langfuse, staging and multi-tenancy are each safe to defer, given AD-1, AD-8 and AD-20.
- The epic-level deferrals (Negotiation internals, Calibration, Proposal template engine, M365 details) are constrained by existing ADs.

One caveat: once a second developer deploys, "Staging optional" interacts with H9, the missing release process.

### Operational envelope coverage

| Dimension | Status |
| --- | --- |
| Deployment topology | Decided (AD-19) |
| Environments | Decided (local, prod; staging deferred) |
| Infra / host | Decided, with assumptions (Ubuntu 24.04, GPU sizing is OQ-1) |
| Secrets | Decided, but deviates from NFR-4 without saying so (H8) |
| Backups | Partly decided; no RPO/RTO or scope (M3) |
| Encryption at rest | Missing (H8) |
| Data residency | Missing (H8) |
| CI/CD, release, rollback | Missing (H9) |
| Upgrades / patching | Missing (M1) |
| Monitoring / alerting | Partly decided; no destination or alerts (M2) |
| Scheduling / cron | Missing (H4) |
| Retention / purge | Missing (H3) |

## Task B: PRD to spine reconciliation (requirements silently dropped)

| # | PRD source | Requirement or constraint | Spine status | Finding |
| --- | --- | --- | --- | --- |
| 1 | §10 Retention, NFR-6 | Lost Opportunities kept 3 years, then archived or deleted; audit kept for contract lifetime + 7 years | Dropped; conflicts with AD-12/AD-18 | H3 |
| 2 | §10 Residency | Data stays in the approved EU region | Dropped (VPS and backup location unstated) | H8 |
| 3 | §10 Access | Exports are audited | Dropped (audit only on mutations) | H5 |
| 4 | NFR-4 | Encryption at rest | Dropped (only backups encrypted) | H8 |
| 5 | NFR-4 | Secrets in a managed vault | Replaced by an env file without saying so | H8, M8 |
| 6 | NFR-4 | Sensitive operations audited (including reads) | Partial | H5 |
| 7 | FR-40 | In-app, Teams and email notifications; overdue escalation | Dropped (AD-17 names M365 only as an integration) | H4 |
| 8 | FR-18 | Notify the engineer and admin when a limit stops a run | Dropped | H4 |
| 9 | FR-37 | Reminders after configurable days | Dropped (no scheduler) | H4 |
| 10 | FR-8 | Stale-source flag after 12 months | Dropped (no scheduler) | H4 |
| 11 | FR-55 | Scheduled re-sync of SharePoint/Confluence | Dropped (no scheduler) | H4 |
| 12 | NFR-2 | No duplicate notifications | Dropped (idempotency only for CRM and run start) | H4, H2 |
| 13 | FR-56 | Agent configuration changes audited | Not representable (`opportunity_id` required) | H5 |
| 14 | FR-65 | Catalogue changes versioned; retired entries stay valid | Partial (Conventions require catalogue references; versioning not ruled) | add to AD-11 |
| 15 | FR-15 | Plans versioned and visible to users | Contradicted by AD-6 (plan only in checkpoint) | H1 |
| 16 | FR-63 | Run pins Source, Requirement and Agent-config versions | Partial (no config snapshot) | H1, M4 |
| 17 | FR-6 | Human edits never overwritten by extraction | Dropped | M5 |
| 18 | FR-5 | Merges of duplicate Requirements recorded | Implicit only | M5 |
| 19 | FR-19 | Research-source fallback; DB-unavailable behaviour | Dropped | M9, L8 |
| 20 | FR-61 | Detect injection attempts where possible | Partial (isolation only) | L2 |
| 21 | §9 Privacy | Minimise customer personal data in prompts | Partial (logs covered by AD-20; prompts not) | L2 |
| 22 | NFR-7 | WCAG 2.1 AA | Dropped | L1 |
| 23 | NFR-8 | Desktop Chrome/Edge | Dropped | L1 |
| 24 | NFR-3 | API scales horizontally; provider rate limits enforced | Replaced without saying so (single VPS; OQ-2 covers concurrency only) | M8 |
| 25 | §9, §11 | Model providers OpenAI/Anthropic | Replaced by Ollama (binding), but not recorded as a PRD deviation in the spine | M8 |
| 26 | FR-24, §11 | Pricing rules service as a deterministic dependency | Dropped from AD-17 | L3 |
| 27 | FR-12, FR-36 | `.docx` / `.xlsx` / email-draft exports | No generation library or rule | L4 |
| 28 | FR-18 | Tool-call limits per run | Dropped (model budgets only) | L6 |
| 29 | SM-C2, FR-59 | Cost per Opportunity within the sponsor's budget | Partial (`platform_model_calls` exists; with local models, "cost" means GPU-time attribution, not tokens × price, and the spine doesn't define it) | add a cost-model line to AD-20 |
| 30 | 4.1 / FR-1 | Opportunity lifecycle statuses | Dropped from Conventions | L7 |
| 31 | Upload safety (implied by FR-4 + NFR-4) | Size, type and malware controls; parser isolation | Dropped | M6 |
| 32 | FR-48, §5 | The platform never sends customer communications | Covered for agents (AD-9); not stated for system code (for example, the notification adapter must never target external recipients) | fold into H4 |

Covered adequately: FR-14 and FR-29 blocking (AD-10), FR-16/17 durability and HITL (AD-6/AD-7), FR-25 contract and Evidence (AD-4/AD-13), FR-33 deterministic arithmetic (AD-10), FR-37 self-approval and FR-62 Baseline pointer (AD-11/AD-15), FR-41 append-only trace (AD-12), FR-53 idempotent CRM write-back (AD-17), FR-57 tool permissions (AD-9), FR-60 eval gate (AD-21), FR-64 sales-rep restrictions (AD-15).

## Suggested order of fixes

1. H1 + H2 (workflow ownership, job contract). These shape every R1 epic.
2. H6 + H7 (SSE auth, `num_ctx`/structured-output spike). Both are cheap to decide now and expensive to change later.
3. H5 + H3 (audit model, retention). Schema-level decisions; settle them before the first migration.
4. H4 (notifications and scheduler). Needed by R1 (FR-18, FR-37 reminders) even though FR-40 is R2.
5. H8 + H9 + M1–M3 (operational envelope). One "Operations" AD or an expansion of AD-19.
6. M8 PRD deviations section. Then the Medium and Low items.
