# Pre-Sales Agent — Flow / Sequence Diagram

Covers: sign-in (Auth0), creating an Opportunity, adding a Source (async parse job via the
Postgres job queue and the `worker` process), and an assessment agent call through the
ModelGateway (Ollama).

```mermaid
sequenceDiagram
    actor User
    participant Web as Web (Next.js)
    participant Auth0
    participant API as API (FastAPI)
    participant UoW as UoW / Trace
    participant DB as Postgres (psa)
    participant Queue as platform_jobs
    participant Worker
    participant Parser as parse_cli (child process)
    participant Gateway as ModelGateway
    participant Ollama

    %% --- Authentication ---
    User->>Web: Open app
    Web->>Auth0: Redirect to Universal Login
    Auth0-->>Web: Callback with session / access token
    Web->>API: Request with Authorization: Bearer <token>
    API->>Auth0: Fetch/validate JWKS (RS256, iss/aud/exp)
    API->>DB: Provision user on first valid sub (if new)
    API-->>Web: 200 (or 401 token_missing/expired/invalid)

    %% --- Create Opportunity ---
    User->>Web: Create Opportunity
    Web->>API: POST /opportunities
    API->>UoW: authorize + domain rules
    UoW->>DB: INSERT opportunity (row_version)
    UoW->>DB: append trace event (opportunity.created)
    UoW-->>API: commit
    API-->>Web: 201 Opportunity

    %% --- Add Source (async parse) ---
    User->>Web: Upload Source file
    Web->>API: POST /opportunities/{id}/sources
    API->>UoW: authorize + store file (platform/files, storage)
    UoW->>DB: INSERT source version (row_version)
    API->>Queue: enqueue(intake.parse_source, payload)
    UoW->>DB: append trace event (source.added)
    API-->>Web: 202 Accepted (source pending)

    loop poll (PSA_WORKER_POLL_S)
        Worker->>Queue: claim next job
    end
    Queue-->>Worker: ParseSource job (leased)
    Worker->>Parser: spawn child process (timeout, RLIMIT)
    Parser-->>Worker: plain text / not_supported / error
    Worker->>DB: save parsed text + status
    Worker->>DB: append trace event (source.parsed)
    Worker->>Queue: complete / fail job
    Web->>API: GET source status (poll or refetch)
    API-->>Web: parsed | failed

    %% --- Assessment via ModelGateway ---
    User->>Web: Run Assessment
    Web->>API: POST /opportunities/{id}/assessments
    API->>Queue: enqueue assessment job
    Worker->>Gateway: chat(profile, schema, prompt)
    Gateway->>Ollama: POST /api/chat (format=JSON Schema)
    Ollama-->>Gateway: model response
    Gateway->>DB: INSERT platform_model_calls row
    Gateway-->>Worker: validated structured result (retries if invalid)
    Worker->>DB: save assessment result + trace event
    Web->>API: GET assessment result
    API-->>Web: 200 Assessment
```

Source: `backend/app/main_worker.py`, `app/platform/jobs/queue.py`,
`app/modules/intake/application/jobs.py`, `app/platform/model_gateway/`,
`app/platform/uow.py`, `app/platform/trace/`, and the Auth0 flow documented in
`README.md`.
