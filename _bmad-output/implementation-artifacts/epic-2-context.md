# Epic 2 Context: From customer input to structured Requirements

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A presales engineer or sales representative adds customer emails, notes and transcripts to an Opportunity. The platform parses them in the background and extracts classified Requirements, each citing the exact source passage. The presales engineer can then edit, split, merge and confirm them, and later extraction never overwrites those edits. This epic turns raw customer input into the structured, traceable Requirement set that Gap detection, Assessments and Estimates build on. It also introduces shared infrastructure that every later epic reuses: the Postgres job queue and worker, the per-Opportunity SSE event stream, the ModelGateway over local Ollama models (with an OpenAI-compatible adapter behind the same port), the agent contract with a code-seeded Agent Registry, and the first agent (`intake_agent`).

## Stories

- Story 2.1: Add Opportunity Sources
- Story 2.2: Background parsing with the worker and job queue
- Story 2.3: Live updates and the source viewer
- Story 2.4: Governed model access through the ModelGateway
- Story 2.5: Extract classified, cited Requirements
- Story 2.6: Edit, split, merge and confirm Requirements
- Story 2.7: Incremental intake with pending changes
- Story 2.8: Treat customer content as untrusted

## Requirements & Constraints

- **Sources:** paste or upload of `.eml`, `.msg`, `.txt`, `.docx`, `.pdf`, `.vtt`. Stored unchanged and versioned; all source content is untrusted.
- **Sales representatives** can add Sources but cannot edit Requirements, Assessments, Estimates or Assumptions. The API returns 403; the UI hides the actions but is never the enforcement point.
- **Uploads:** default 50 MB limit, extension allowlist plus magic-byte check, per-user rate limits (429 problem+json). A rejected file stores nothing. There is no reverse proxy in the current deployment, so all limits must be enforced in the API.
- **Extraction:** each Requirement is classified as functional, integration, data, security, non-functional or commercial and cites at least one source passage. Cross-Source duplicates merge into one Requirement citing all passages, with traced lineage.
- **Quality bar:** ≥90% recall and 100% valid citations on at least 3 annotated intake fixtures (`make eval-intake`); not done until it passes.
- **Human edits always win:** edits, splits, merges, deletes and confirms are traced. Extraction never overwrites a human-touched Requirement; it proposes a pending change that a human accepts or rejects with a reason. Deleted Requirements stay in history.
- **Incremental intake:** a new Source yields only new or changed Requirements. Affected Assessments are flagged once Epic 5 exists; in R1 the engineer chooses what to rerun.
- **Untrusted content:** never grants extra actions; injection is heuristically detected and flagged; prompt-injection tests run in CI.
- **Performance:** ≤50 pages extracted in under 5 minutes; status reads under 500 ms P95.
- **Privacy:** customer data stays on the server (local models only); no customer content or prompt text in logs.

## Technical Decisions

- **Ownership:** `intake` owns Source, extracted-text artifact, Source Passage, Requirement and pending change (`intake_*`). `platform` owns jobs, idempotency, schedules, model calls, files and trace. `registry` owns Agents and config versions. Cross-module access only via `application/public.py`.
- **Mutation path:** command → `identity.authorize` → validate → write → `platform.trace.append`, in one Unit of Work. `row_version` + `If-Match` (412 on mismatch). Commits only at the edge. No LLM or HTTP call inside an open Unit of Work. Roles come from Auth0; Opportunity membership lives in the platform.
- **Storage:** `platform.storage` (local volume), SHA-256 content-addressed, immutable, reference-counted. Re-upload = new Source version on the same blob. Extracted text is its own immutable artifact.
- **Parsing:** worker only, in a subprocess with CPU, memory and time limits: docling (PDF/DOCX), pymupdf PDF fallback, extract-msg, stdlib `email`, in-house `.vtt`. The `api` process never runs jobs, agents or parsing.
- **Job contract:** typed registry (`platform/jobs/registry.py`), priority classes `interactive > background`, enqueue inside the caller's Unit of Work, `FOR UPDATE SKIP LOCKED`, lease + heartbeat, expired-lease reclaim, retries with backoff, `dead` state raising an alert. `platform_idempotency` keys `run:` / `node:` / `out:`; `platform_schedules` for recurring work. Job types `<module>.<verb>`.
- **Event stream:** SSE per Opportunity at `/api/v1/opportunities/{opportunity_id}/events`, fetch-based with bearer token. NOTIFY carries only `{event_id, opportunity_id, source}`; the API re-reads and authorizes per subscriber. Frames: `id`, `event`, `data {event_type, subject_type, subject_id, subject_version, occurred_at, summary}`; replay from `Last-Event-ID`. No WebSockets. Downloads use short-lived HMAC-signed URLs.
- **ModelGateway** is the only path to a model, via a provider-neutral port:
  - Ollama adapter (default): native `/api/chat` and `/api/embed`, `format` = JSON Schema generated from the Pydantic output model.
  - OpenAI-compatible adapter: `response_format` (JSON schema), kept for a later move to vLLM; must pass the same contract tests against a stub server.
  - Every call: model profile from the agent's registry config version, low temperature for structured tasks, Pydantic validation with bounded retries, run token/call/time budgets, a slot from a priority-aware semaphore (slots ≤ `OLLAMA_NUM_PARALLEL`), and a `platform_model_calls` row (run, task, agent, config version, model digest, tokens, latency, outcome; no prompt text).
  - Context size comes only from the model profile, never a provider default or per-call guess. OpenAI-style endpoints cannot set context size per request, so the profile (a named model built from a Modelfile) must carry it.
- **Model profiles:** `ops/models/*.Modelfile` set `num_ctx` explicitly, built at deploy into named models pinned by digest. Defaults `gpt-oss:20b` (chat) and `bge-m3` (embeddings) on Ollama 0.35.0, GPU, internal network only. Weights + KV cache must fit the 48 GB GPU. A structured-output spike over every planned agent schema records results in `evals/spikes/structured-output.md`; any schema under 95% first-try valid blocks its epic.
- **Agent contract:** `agents/contract.py` `AgentResult` with `contract_version`, Findings, Evidence refs, Assumptions, Unknowns, Risks, recommendation, confidence with basis, needs-human-review flag, `extensions.<agent_id>`. Agents implement `Agent.run(task) -> AgentResult` and only propose; `intake.accept_extraction` validates and writes. Registry seeded from code, one config version per agent. `actor_id` = `<agent_id>@<semver>`; prompts at `agents/<agent_id>/prompts/v<N>.md`. Only `orchestration/` imports LangGraph.
- **Evidence:** `{kind, id, version?, span?}`. `source_passage` rows are immutable, tied to a source version, with Unicode code-point offsets into the extracted-text artifact. Unresolvable references are rejected on acceptance.
- **Requirement provenance:** `origin: extracted | human` and `locked_by_human`. Changes to locked Requirements go through `intake.propose_requirement_change`. Merges and splits are lineage trace events.
- **Untrusted text** enters prompts only inside delimited data blocks. Suspected injection sets `injection_suspected` and appends `intake.source.injection_flagged`.
- **Conventions:** trace events `intake.<entity>.<past_tense_verb>` with a payload model in `platform/trace/catalogue.py`; actions `<module>.<entity>.<verb>`; problem+json errors; UUIDv7 IDs; config via `pydantic-settings` with `PSA_` prefix.
- **Testing:** domain without DB or LLM; agents use a fake ModelGateway; jobs and commands get Postgres integration tests, including lease reclaim.

## UX & Interaction Patterns

- **Sources tab:** drag-and-drop, file picker or paste. Rejected uploads show an inline, specific reason on the row. Live status pills (Queued, Parsing, Parsed, Parse failed); **Parse failed** is red with the reason, **Retry** and **Paste text instead**. The inspector shows extracted text, metadata, version and **Download original**.
- **Empty state:** a new Opportunity with no Sources shows one sentence plus the inline upload/paste area.
- **Requirements tab:** grouped by classification with origin and lock state; streams in during extraction with "Extracting — 2 of 3 sources", a running dot and a counting tab badge.
- **Keyboard:** `e` inline edit (save on blur with `If-Match`), `x` multi-select, `c` create, Enter opens the inspector.
- **Evidence chip:** kind icon + label; click opens the passage in the inspector with the span highlighted; superseded references struck through.
- **Pending change:** amber marker; diff view with diff-tint and `+`/`−` markers (not semantic green/red), new Evidence, **Accept** / **Reject** (reason required).
- **412:** "Changed by [user] since you opened it" with Reload or View diff.
- **Connection:** "Reconnecting…" while disconnected, "Offline — edits disabled" after 60 s.
- **Copy:** glossary terms exactly, specific failure reasons, no emoji.

## Cross-Story Dependencies

- **From Epic 1:** scaffold, Auth0 identity and `identity.authorize`, Unit of Work, trace writer, Opportunity membership, workspace tabs, inspector and status pill, and the alerting used for dead jobs.
- **Within the epic:** 2.1 → 2.2 → 2.3; 2.4 (gateway, agent contract, registry seed) before 2.5; 2.5 → 2.6 → 2.7; 2.8 hardens the intake agent from 2.5.
- **Later epics:** the job queue, ModelGateway and SSE stream are reused by Epics 3–9; the 2.4 spike results feed agent schemas in Epic 5; the 2.7 Assessment-impact notice activates with Epic 5; Epic 4 answers use `intake.propose_requirement_change`; Epic 7 moves the code-seeded registry to DB-only reads through `registry/application/public.py`.
