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
- source_spec: `_bmad-output/implementation-artifacts/spec-2-1a-upload-opportunity-sources.md`
  summary: Story 2.1 Part B — paste text as a Source (kind note, stored as a UTF-8 `.txt` blob named "Pasted text", 1–1,000,000 characters once trimmed, blank → 422 `file_empty`) and the per-user upload rate limit (30 adds per rolling minute via `PSA_UPLOAD_RATE_PER_MINUTE`, counted in Postgres, 429 `rate_limited` problem+json with `Retry-After`, UI "Too many uploads — try again in a minute").
  evidence: Split from Story 2.1 at user request because the full spec was about 2,900 tokens; Part A ships storage, file upload with size/allowlist/magic-byte checks, versioning, the Sources list and the Sources tab.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-1a-upload-opportunity-sources.md`
  summary: Verify that an API rejection sent before the body is read (disallowed type from the part headers, 403/404, oversized Content-Length) reaches the Sources tab as its "Rejected: …" sentence for a multi-MB file, not as "The upload failed" from a connection reset; if not, drain the body up to the cap before answering or pre-check the extension and size in the browser.
  evidence: Review finding #10 (maybe-false, medium if true). uvicorn may close the connection after an early response while undici is still sending the body; TestClient and the mocked fetch can't show it. Settle with a real uvicorn + Next (undici) test uploading a multi-MB `.exe`.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-1b-paste-text.md`
  summary: [post-demo] Story 2.1 Part C — per-user upload rate limit (30 adds per rolling minute via `PSA_UPLOAD_RATE_PER_MINUTE`, counted in Postgres, 429 `rate_limited` problem+json with `Retry-After`, UI "Too many uploads — try again in a minute"), covering both file uploads and pasted text.
  evidence: Cut from Part B for the 2026-10-07 stakeholder demo; Part B ships paste text alone. Supersedes the rate-limit half of the Part B entry above.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-2a-job-queue-and-worker.md`
  summary: Story 2.2 Part B — `intake.parse_source` job: parse each new Source version in a subprocess with CPU, memory and time limits (pymupdf for PDF, DOCX text from its XML, extract-msg, stdlib `email`, in-house `.vtt`), store the extracted text as an immutable artifact linked to the Source version, and show Queued/Parsing/Parsed/Parse failed with the reason, **Retry** and **Paste text instead** on the Sources tab.
  evidence: Split from Story 2.2 at user request; Part A ships the job queue and worker that Part B's job runs on.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-2a-job-queue-and-worker.md`
  summary: [post-demo] AD-29 remainder — `platform_idempotency` (unique key, result reference, `run:`/`node:`/`out:` grammar) and `platform_schedules` for recurring jobs, plus the real alert on `dead` jobs once Story 1.3 alerting exists (Part A only logs `jobs.dead` at ERROR).
  evidence: Cut for the 2026-10-07 stakeholder demo; nothing uses idempotency or schedules before Epic 5, and Story 1.3 is not built.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-2a-job-queue-and-worker.md`
  summary: [post-demo] Switch PDF and DOCX parsing to docling (pymupdf kept as the PDF fallback) as the architecture specifies; Story 2.2 Part B uses pymupdf and DOCX XML text only.
  evidence: User chose light parsers for the 2026-10-07 demo: docling pulls in torch and model downloads (multi-GB image, slow CPU parsing), a timeline risk.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-4-model-gateway.md`
  summary: [post-demo] Story 2.4 remainder — OpenAI-compatible adapter passing the same contract tests; `ollama` compose service (0.35.0) with NVIDIA GPU on the internal network; `ops/models/*.Modelfile` profiles built at deploy and pinned by digest; `/api/embed`; DB-owned Agent Registry seeded from code (`registry_agent_config_versions`); run budgets (Story 5.6); structured-output spike across every planned agent schema in `evals/spikes/structured-output.md`.
  evidence: Cut for the 2026-10-07 stakeholder demo; the demo uses host Ollama with code-defined profiles and agent configs.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-4-model-gateway.md`
  summary: [post-demo] Replace the demo model `gpt-oss:120b-cloud` (prompts leave the machine to Ollama's cloud) with an on-server model that fits the target GPU, after IT data-handling approval and an eval pass; until then only sample or anonymised Opportunities may use the cloud profile.
  evidence: Dev laptop GPU is 8 GB (RTX PRO 1000), too small for `gpt-oss:20b`; user chose the cloud model for demo quality on 2026-10-04.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-5a-extract-requirements.md`
  summary: [post-demo] Story 2.5 remainder — `make eval-intake` with at least 3 annotated Opportunities in `evals/intake/` and the ≥90% recall / 100% valid citation gate; chunked extraction for inputs larger than one model call with a cross-chunk merge step; `intake.requirement.merged` lineage trace events; Requirements streaming in over SSE (Story 2.3) and the tab badge counting up; incremental re-extraction that proposes changes to human-locked Requirements instead of adding duplicates (Story 2.7).
  evidence: Cut for the 2026-10-07 stakeholder demo; the demo extracts all Sources in one call, supersedes earlier extracted Requirements on each run, and polls for completion.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-5a-extract-requirements.md`
  summary: Story 2.5 Part B — Evidence inspector: `GET /opportunities/{id}/passages/{passage_id}` (readers; `{before, text, after, filename, source_version}` with up to 300 characters of context, 404 across Opportunities), clickable Evidence chips, and Enter or a click on a Requirement opening the right-pane inspector with text, classification, origin `Extracted` and the cited passage highlighted (`mark`, token colour).
  evidence: Split from Story 2.5 at user request because the full spec was about 2,700 tokens; Part A ships extraction, the grouped list and polling. Needed for the 2026-10-07 demo.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-2a-job-queue-and-worker.md`
  summary: Job `last_error` stores the first line of any handler exception message; store the exception class only by default and let handlers raise a dedicated safe-message error (e.g. `JobError(code)`) for a vetted reason.
  evidence: Review finding #12 (medium): driver, HTTP and KeyError messages can echo data, conflicting with "never customer content"; the fix adds public surface, so it was deferred rather than patched. Until then, handlers must map known failures to codes themselves.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-2b-parse-sources.md`
  summary: [post-demo] Parse Outlook `.msg` Sources (currently `failed` with `not_supported`) and reconsider the PDF parser; any copyleft library (`extract-msg` GPL-3.0, `pymupdf` AGPL-3.0) needs a licence decision first, or use a permissive alternative.
  evidence: User chose permissive parsers only for the 2026-10-07 demo (pypdf for PDF, .msg postponed) on 2026-10-04.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-2b-parse-sources.md`
  summary: A Source version whose parse job dies without its handler running (worker killed or lease lost on the final attempt) stays `parsing` forever; add a dead-job hook or a stale-row sweep that marks it `failed`, so Retry is offered and polling stops.
  evidence: Review finding #19 (medium): the job runner marks such jobs `dead` without calling the handler; fixing it needs new public surface in the job layer.
- source_spec: `_bmad-output/implementation-artifacts/spec-2-6-edit-and-confirm-requirements.md`
  summary: [post-demo] Story 2.6 remainder — split, merge, delete-with-reason and manual create (`c`) of Requirements with lineage trace events, and **View diff** on the 412 concurrent-edit message.
  evidence: Cut for the 2026-10-07 stakeholder demo; the demo ships inline edit, Confirm and Confirm all.
- source_spec: `_bmad-output/implementation-artifacts/spec-4-3-detect-gaps.md`
  summary: [post-demo] Epic 4 remainder after the demo slice — Checklist- and Knowledge-grounded triggers (Stories 3.x, 4.1, 4.2: mandatory deterministic Gaps), "Possibly answered", dismiss/reopen/impact change (4.4), question edit/merge/drop/approve (4.5), export and mark sent (4.6), answers (4.7), live Overview count and tab badge, command-palette Gap search, and the `make eval-gaps` gate (≥80% recall, ≤20% irrelevant). Re-detection must stop superseding Gaps once humans can act on them.
  evidence: Cut for the 2026-10-07 stakeholder demo; user chose agent+Requirements grounding, automatic detection after extraction, and ranked cards with an inspector (2026-10-04).
