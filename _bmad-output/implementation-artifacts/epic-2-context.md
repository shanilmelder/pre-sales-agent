# Epic 2 Context: From customer input to structured Requirements

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A presales engineer or sales representative adds customer emails, notes and transcripts to an Opportunity. The platform parses them in the background and extracts classified Requirements, each citing the exact source passage. The presales engineer can then edit, split, merge and confirm them, and later extraction never overwrites those edits. This epic turns raw customer input into the structured, traceable Requirement set that Gap detection, Assessments and Estimates build on. It also introduces shared infrastructure that every later epic reuses: the Postgres job queue and worker process, the per-Opportunity SSE event stream, the ModelGateway over local Ollama models, the agent contract with a seeded Agent Registry, and the first agent (`intake_agent`).

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

- **Sources:** added by paste or upload of `.eml`, `.msg`, `.txt`, `.docx`, `.pdf` or `.vtt`. Each is stored unchanged and versioned, and all source content is untrusted.
- **Sales representatives** on an Opportunity can add Sources. They cannot edit Requirements, Assessments, Estimates or Assumptions. The API returns 403 for those actions and the UI hides them, but the UI is never the enforcement point.
- **Extraction:** each Requirement is classified as functional, integration, data, security, non-functional or commercial, and cites at least one source passage. Duplicates across Sources are merged into one Requirement that cites all passages, and the merge lineage is traced.
- **Quality bar:** at least 90% recall and 100% valid citations on the intake reference fixtures (at least 3 annotated Opportunities, run with `make eval-intake`). The story is not done until this passes.
- **Human edits always win:** edits, splits, merges, deletes and confirms are traced. Extraction never overwrites a human-touched Requirement. It proposes a pending change instead, which a human accepts or rejects with a reason. A deleted Requirement stays in history.
- **Incremental intake:** a new Source produces only new or changed Requirements. Once Assessments exist (Epic 5), the platform flags the ones affected, and in R1 the engineer chooses what to rerun.
- **Untrusted content:** Source text never grants extra actions. Injection attempts are detected heuristically and flagged, and prompt-injection tests run in CI.
- **Performance:** extraction of up to 50 pages finishes in under 5 minutes, and status reads take under 500 ms (P95).
- **Privacy:** no customer content or prompt text in logs, and model calls stay on the server through local Ollama.
- **Uploads:** default size limit of 50 MB, enforced at both Caddy and the API. Uploads are checked against an extension allowlist plus magic bytes, with per-user rate limits (429 problem+json). A rejected file stores nothing.

## Technical Decisions

- **Ownership:** `intake` owns Opportunity Source, the extracted-text artifact, Source Passage, Requirement and pending Requirement change, in `intake_*` tables. `platform` owns jobs, idempotency, schedules, model calls, file metadata and trace. `registry` owns Agents and config versions. Other modules reach this data only through `application/public.py`.
- **Mutation path:** every change follows command → `identity.authorize` → validate → write → `platform.trace.append`, all in one Unit of Work. Every mutable row has `row_version`, and the API requires `If-Match` (412 on mismatch). Commits happen only at the edge (request handler or job runner). No LLM or HTTP call happens while a Unit of Work is open.
- **Storage:** files go through `platform.storage` (a local volume in R1). They are content-addressed by SHA-256, immutable and reference-counted. Re-uploading the same file creates a new Source version pointing at the same blob. Extracted text is its own immutable artifact.
- **Parsing:** runs only in the worker, in a subprocess with CPU, memory and time limits. Parsers: docling for PDF and DOCX (pymupdf as the PDF fallback), extract-msg, stdlib `email`, and an in-house `.vtt` parser. The `api` process never runs jobs, agents or parsing.
- **Job contract:** `platform_jobs` uses a typed registry (`platform/jobs/registry.py`) with priority classes (`interactive > background`), enqueueing inside the caller's Unit of Work, `FOR UPDATE SKIP LOCKED` claiming, a lease with heartbeat, reclaiming of expired leases, retries with backoff, and a `dead` state that raises an alert. `platform_idempotency` uses the key grammar `run:` / `node:` / `out:`. Recurring jobs come from `platform_schedules`. Job types are named `<module>.<verb>` (for example `intake.parse_source` and `intake.extract_requirements`). A killed worker must not cause duplicate completion.
- **Event stream:** one SSE stream per Opportunity at `/api/v1/opportunities/{opportunity_id}/events`, read with fetch-based SSE carrying the bearer token. NOTIFY carries only `{event_id, opportunity_id, source}`, and the API re-reads and authorizes each event per subscriber. Frames are `id`, `event` and `data {event_type, subject_type, subject_id, subject_version, occurred_at, summary}`, and reconnect replays from `Last-Event-ID`. There are no WebSockets.
- **Downloads:** originals are served through short-lived HMAC-signed URLs, issued by an authorized API call.
- **ModelGateway:** this is the only path to a model. The Ollama adapter uses the native `/api/chat` with `format` set to the JSON Schema generated from the Pydantic output model, low temperature, validation, and bounded retries. An OpenAI-compatible adapter sits behind the same port and passes the same contract tests. Calls wait on a priority-aware semaphore with no more slots than `OLLAMA_NUM_PARALLEL`. Every call writes a `platform_model_calls` row (run, task, agent, config version, model digest, tokens, latency, outcome).
- **Model profiles:** `ops/models/*.Modelfile` sets `num_ctx` explicitly, and each profile is built at deploy and pinned by digest. Defaults are `gpt-oss:20b` for chat and `bge-m3` for embeddings, with Ollama 0.35.0 on the GPU and the internal network only. A structured-output spike against every planned agent schema records results in `evals/spikes/structured-output.md`, and any schema below 95% valid on the first try is flagged as a blocker for its epic.
- **Agent contract:** `agents/contract.py` defines `AgentResult` with `contract_version`, Findings, Evidence refs, Assumptions, Unknowns, Risks, a recommendation, confidence with its basis, a needs-human-review flag, and `extensions.<agent_id>`. Agents implement `Agent.run(task) -> AgentResult` and only propose. The owning module's `accept_*` command (here `intake.accept_extraction`) validates the result and writes it. The registry is seeded from code with one config version per agent. Agent `actor_id` is `<agent_id>@<semver>`, and prompts live at `agents/<agent_id>/prompts/v<N>.md`.
- **Evidence:** a reference is `{kind, id, version?, span?}`. `source_passage` rows are immutable, tied to a source version, and use Unicode code-point offsets into the extracted-text artifact. Any reference that doesn't resolve is rejected on acceptance.
- **Requirement provenance:** each Requirement carries `origin: extracted | human` and `locked_by_human`. A change aimed at a locked Requirement goes through `intake.propose_requirement_change`. Merges and splits are trace events that record lineage.
- **Untrusted text** enters prompts only inside delimited data blocks, never in system instructions or tool descriptions. Suspected injection sets an `injection_suspected` flag on the affected item and appends an `intake.source.injection_flagged` trace event.
- **Naming:** trace events are `intake.<entity>.<past_tense_verb>` (for example `intake.source.added`, `intake.requirement.edited` and `intake.requirement.merged`), and each has a payload model in `platform/trace/catalogue.py`. Actions are `<module>.<entity>.<verb>`. Errors are problem+json with a stable `code`. IDs are UUIDv7.
- **Testing:** domain code is tested without a DB or LLM. Agents use a fake ModelGateway. Jobs and commands get Postgres integration tests, including a lease-reclaim test.

## UX & Interaction Patterns

- **Sources tab:** drag-and-drop or choose a file, or paste text. A rejected upload shows an inline reason on the file row ("Rejected: .exe files aren't allowed", "Rejected: larger than 50 MB"). Status pills (Queued, Parsing, Parsed, Parse failed) update live. **Parse failed** is red, shows the reason, and offers **Retry** and **Paste text instead**. Selecting a Source shows its extracted text, metadata and version in the inspector, plus **Download original**.
- **First-run empty state:** a new Opportunity with no Sources shows one sentence plus the upload and paste area inline.
- **Requirements tab:** Requirements are grouped by classification and show origin and lock state. During extraction they stream in, the header shows "Extracting — 2 of 3 sources" with a running dot, and the tab badge counts up.
- **Keyboard:** `e` edits inline (saves on blur with `If-Match`), `x` multi-selects, `c` creates, and Enter opens the inspector.
- **Evidence chip:** a kind icon plus a label in meta type. Clicking it opens the cited passage in the inspector with the span highlighted. Superseded references are shown struck through.
- **Pending change:** an amber marker on the locked Requirement opens the diff view (diff-tint background plus `+`/`−` text markers, never semantic green or red) with the new Evidence, **Accept** and **Reject**. Reject requires a reason.
- **Concurrent edit (412):** shows "Changed by [user] since you opened it" with Reload or View diff. Nothing is overwritten silently.
- **Connection state:** the status bar shows "Reconnecting…" while disconnected and "Offline — edits disabled" after 60 s. Missed events replay without a toast.
- **Injection flag:** shown as a warning label in the inspector.
- **Copy:** uses glossary terms exactly, gives specific failure reasons, and uses no emoji.

## Cross-Story Dependencies

- **Depends on Epic 1:** the scaffold, Auth0 identity and `identity.authorize`, Unit of Work, trace writer, Opportunity membership, the workspace tabs (Sources, Requirements), the inspector and status pill components, and the Story 1.3 alerting used for dead jobs.
- **Within this epic:**
  - 2.1 → 2.2 (parsing jobs) → 2.3 (live status and the viewer).
  - 2.4 (gateway, agent contract, registry seed) must exist before 2.5.
  - 2.5 → 2.6 → 2.7, because pending changes need human-locked Requirements.
  - 2.8 hardens the intake agent built in 2.5.
- **Later epics depend on this one:**
  - The job queue, ModelGateway and SSE stream are reused by Epics 3–9.
  - The Assessment-impact notice in 2.7 becomes active once Epic 5 exists.
  - Epic 4 answers propose Requirement updates through `intake.propose_requirement_change`.
  - Epic 7 extends the seeded Agent Registry.
