# Epic 2 Context: From customer input to structured Requirements

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A presales engineer or sales representative adds customer emails, notes and transcripts to an Opportunity. The platform parses them in the background and extracts classified Requirements, each citing the exact source passage. The presales engineer can then edit, split, merge and confirm them, and later extraction never overwrites those edits. This epic turns raw customer input into the structured, traceable Requirement set that Gap detection, Assessments and Estimates build on. It also introduces shared infrastructure that every later epic reuses: the Postgres job queue and worker, the per-Opportunity SSE event stream, the ModelGateway over local Ollama models (with an OpenAI-compatible adapter behind the same port), the agent contract with the Agent Registry, and the first agent (`intake_agent`).

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
- **Uploads:** default 50 MB limit, extension allowlist plus magic-byte check, per-user rate limits (429 problem+json). A rejected file stores nothing. The spine still mentions Caddy, but the current deployment has no reverse proxy, so every limit must be enforced in the API.
- **Extraction:** each Requirement is classified as functional, integration, data, security, non-functional or commercial and cites at least one source passage. Duplicates across Sources merge into one Requirement that cites all their passages, with the lineage traced.
- **Quality bar:** at least 90% recall and 100% valid citations on the annotated intake fixtures. The story-level gate is `make eval-intake`. The shared `make eval` harness (reference set in `evals/`, results stored insert-only in `registry_eval_results`) also scores this bar, and CI blocks prompt, agent, model-profile or digest changes that fail it.
- **Human edits always win:** edits, splits, merges, deletes and confirms are traced. Extraction never overwrites a human-touched Requirement. It proposes a pending change, which a human accepts, or rejects with a reason. Deleted Requirements stay in history.
- **Incremental intake:** a new Source yields only new or changed Requirements. Affected Assessments are flagged once Epic 5 exists; in R1 the engineer chooses what to rerun.
- **Untrusted content:** it never grants extra actions. Injection attempts are detected heuristically and flagged, and prompt-injection tests run in CI.
- **Performance:** up to 50 pages extracted in under 5 minutes; status reads under 500 ms P95.
- **Privacy:** customer data stays on the server (local models only). Logs carry IDs only, never customer content or prompt text.

## Technical Decisions

- **Ownership:** `intake` owns Source, the extracted-text artifact, Source Passage, Requirement and pending Requirement change (tables `intake_*`). `platform` owns jobs, schedules, idempotency keys, model calls, file metadata and trace. `registry` owns Agents, config versions and eval results. Cross-module access goes only through `application/public.py`.
- **Mutation path:** command → `identity.authorize` → validate → write → `platform.trace.append`, all in one Unit of Work. Commands called from other modules join the caller's Unit of Work. Mutable rows carry `row_version`; requests send `If-Match` and get 412 on a mismatch. Commits happen only at the edge (request handler or job runner). No LLM or HTTP call runs inside an open Unit of Work.
- **Authorization:** the API authorizes from the Auth0 access token alone. The `permissions` claim names equal action names (`<module>.<entity>.<verb>`, catalogued in `identity/actions.py`), and a namespaced roles claim drives the sales-representative exclusions. Opportunity membership lives in the platform (`identity/domain/policy.py`).
- **Storage:** files go through `platform.storage` (local volume). They are content-addressed by SHA-256, immutable and reference-counted for purge. A re-upload creates a new Source version on the same blob. Extracted text is its own immutable artifact.
- **Parsing:** runs only in the worker, in a subprocess with CPU, memory and time limits. Parsers: docling (PDF/DOCX), pymupdf as PDF fallback, extract-msg, stdlib `email`, and an in-house `.vtt` parser. The `api` process never runs jobs, agents or parsing.
- **Job contract:**
  - Typed registry (`platform/jobs/registry.py`), priority classes `interactive > background`.
  - Jobs are enqueued inside the caller's Unit of Work and claimed with `FOR UPDATE SKIP LOCKED`.
  - Lease + heartbeat, expired-lease reclaim, retries with backoff; exhausted jobs go to `dead` and raise an alert.
  - `platform_idempotency` key grammar: `run:`, `node:`, `out:`. `platform_schedules` holds recurring work.
  - Job types are named `<module>.<verb>`. Job statuses: `queued, leased, succeeded, failed, dead`.
- **Event stream:**
  - One SSE stream per Opportunity at `/api/v1/opportunities/{opportunity_id}/events`, read fetch-based with the bearer token. No WebSockets.
  - NOTIFY carries only `{event_id, opportunity_id, source}`. The API re-reads each event and authorizes it per subscriber.
  - Frames: `id`, `event`, and `data {event_type, subject_type, subject_id, subject_version, occurred_at, summary}`. Reconnect replays from `Last-Event-ID`. Events come from `platform_trace_events` and `workflows_progress`.
  - Downloads use short-lived HMAC-signed URLs.
- **ModelGateway** is the only path to a model, through a provider-neutral port:
  - The Ollama adapter (default) calls native `/api/chat` and `/api/embed`, with `format` set to the JSON Schema generated from the Pydantic output model.
  - The OpenAI-compatible adapter uses `response_format` (kept for a later move to vLLM) and must pass the same contract tests against a stub server.
  - On every call the gateway: takes the model profile from the agent's registry config version; uses low temperature for structured tasks; validates with Pydantic and retries within a bound; enforces the run's token, call and time budgets; takes a slot from a priority-aware semaphore (slots ≤ `OLLAMA_NUM_PARALLEL`); and writes a `platform_model_calls` row (run, task, agent, config version, model digest, tokens, latency, outcome; no prompt text).
  - Context size comes only from the model profile, never from a provider default or a per-call guess.
- **Model profiles:** `ops/models/<profile>.Modelfile` sets `num_ctx` explicitly. Each is built into a named Ollama model, pinned by digest. Defaults are `gpt-oss:20b` (chat) and `bge-m3` (embeddings, 1024 dims), both resident on one 48 GB GPU. Weights plus KV cache (`num_ctx` × `OLLAMA_NUM_PARALLEL`) must fit. A structured-output spike over every planned agent schema goes in `evals/spikes/structured-output.md`; any schema below 95% first-try valid blocks its epic.
- **Agent contract:**
  - `agents/contract.py` defines `AgentResult`: `contract_version`, Findings, Evidence refs, Assumptions, Unknowns, Risks, recommendation, confidence with basis, a needs-human-review flag, and `extensions.<agent_id>` with a registered schema.
  - Agents are plain classes implementing `Agent.run(task) -> AgentResult` and only propose. `intake.accept_extraction` validates the result and writes it.
  - `actor_id` is `<agent_id>@<semver>`. Prompts live at `agents/<agent_id>/prompts/v<N>.md`. A config may reference only prompt and schema versions present in the image. Only `orchestration/` imports LangGraph.
- **Evidence:** `{kind, id, version?, span?}`; `version` is required when the target is versioned. `source_passage` rows are immutable, tied to a source version, and use Unicode code-point offsets into the extracted-text artifact. References that don't resolve are rejected on acceptance.
- **Requirement provenance:** `origin: extracted | human` plus `locked_by_human`. Changes to a locked Requirement go through `intake.propose_requirement_change`. Merges and splits are lineage trace events.
- **Untrusted text** enters prompts only inside delimited data blocks, never in system instructions or tool descriptions. A suspected injection sets `injection_suspected` and appends `intake.source.injection_flagged`.
- **Conventions:** trace events are `intake.<entity>.<past_tense_verb>`, each with one payload model in `platform/trace/catalogue.py`. The trace is append-only. Errors are problem+json with a stable `code`. IDs are UUIDv7. Config comes from `pydantic-settings` with the `PSA_` prefix. The web app uses only the generated API client.
- **Testing:** domain code is tested without DB or LLM; agents use a fake ModelGateway; jobs and commands get Postgres integration tests, including lease reclaim.

## UX & Interaction Patterns

- **Sources tab:** drag-and-drop, file picker or paste. A rejected upload shows a specific inline reason on its row. Live status pills: Queued, Parsing, Parsed, Parse failed. **Parse failed** is red and shows the reason, with **Retry** and **Paste text instead**. The inspector shows the extracted text, metadata, version and **Download original**.
- **Empty state:** a new Opportunity with no Sources shows one sentence plus the inline upload/paste area.
- **Requirements tab:** grouped by classification, showing origin and lock state. During extraction it streams in, with "Extracting — 2 of 3 sources", a running dot and a tab badge that counts up.
- **Keyboard:** `e` inline edit (saves on blur with `If-Match`), `x` multi-select, `c` create, Enter opens the inspector.
- **Evidence chip:** a kind icon plus a label. Clicking it opens the passage in the inspector with the span highlighted. Superseded references are struck through.
- **Pending change:** an amber marker. The diff view uses the diff-tint token with `+`/`−` markers (not semantic green/red) and shows the new Evidence. **Accept** applies it; **Reject** requires a reason.
- **412:** "Changed by [user] since you opened it", with Reload or View diff.
- **Connection:** "Reconnecting…" while disconnected; "Offline — edits disabled" after 60 s.
- **Copy:** glossary terms exactly, specific failure reasons, no emoji.

## Cross-Story Dependencies

- **From Epic 1:** scaffold, Auth0 token validation and `identity.authorize`, Unit of Work, trace writer, Opportunity membership, workspace tabs, inspector and status pill.
- **Within the epic:** 2.1 → 2.2 → 2.3. 2.4 (gateway, agent contract, registry seed) comes before 2.5. Then 2.5 → 2.6 → 2.7. 2.8 hardens the intake agent from 2.5.
- **Later epics:**
  - Epics 3–9 reuse the job queue, ModelGateway and SSE stream.
  - Epic 4 Gap answers go through `intake.propose_requirement_change`.
  - Epic 5 run input pins record source and Requirement versions, which drive the 2.7 notice of affected Assessments.
  - Epic 7 registry reads are DB-only through `registry/application/public.py`.
  - The Story 7.6 `make eval` harness re-scores the extraction bar.
