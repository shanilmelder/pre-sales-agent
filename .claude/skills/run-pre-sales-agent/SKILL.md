---
name: run-pre-sales-agent
description: Redeploy, run, restart or start the local Pre Sales Agent stack. Pulls the current branch, rebuilds and recreates the Docker images and containers (api, worker, web, postgres, pgadmin), runs any pending database migrations (alembic upgrade head), then health-checks it and takes a screenshot. Use when asked to "pull and rebuild", "recreate the containers", "redeploy locally", "run db upgrades/migrations", or "check the app is up".
---

# Run Pre Sales Agent (local Docker stack)

The app is a FastAPI `api`, a job `worker`, a Next.js `web` app, Postgres and pgAdmin. All of
them run from `compose.yaml` under the `local` profile. The driver is a Git Bash script:
`.claude/skills/run-pre-sales-agent/redeploy.sh`. Paths here are relative to the repo root.
The script finds the root itself, so you can run it from any directory in the repo.

## Prerequisites

- Docker Desktop running (`docker compose version` reports v2 or later; v5.5.1 was used).
- A filled-in `.env` at the repo root. The script reads `POSTGRES_USER`, `POSTGRES_PASSWORD`
  and `POSTGRES_DB` from it for the owner-role migration URL.
- Optional: Chrome at `C:\Program Files\Google\Chrome\Application\chrome.exe` for the
  screenshot. Override the path with `CHROME=...`.

## Run (agent path)

```bash
bash .claude/skills/run-pre-sales-agent/redeploy.sh            # pull + rebuild + migrate + smoke (~50 s warm)
bash .claude/skills/run-pre-sales-agent/redeploy.sh --no-pull  # deploy the working tree as it is
bash .claude/skills/run-pre-sales-agent/redeploy.sh --migrate  # only apply pending migrations
bash .claude/skills/run-pre-sales-agent/redeploy.sh --smoke    # only health checks + screenshot
```

The full run does four things in order:

1. **Pull:** `git fetch` and a fast-forward merge of the current branch from `origin`. Your
   uncommitted changes stay in place. A branch that was never pushed skips this step with
   "origin has no branch '…'; skipping the pull".
2. **Rebuild:** `docker compose --profile local up --build --force-recreate --wait -d`.
3. **Migrate:** compare `alembic current` with `alembic heads` inside the `api` container,
   using the owner role. If they differ, run `alembic upgrade head` and restart `api` and
   `worker`. If they match, it prints "already at head; nothing to upgrade".
4. **Smoke:** check the API and web health endpoints, list the container states, then
   screenshot `http://localhost:3000/`.

The screenshot is saved to `.claude/skills/run-pre-sales-agent/shots/signin.png` (git-ignored). Open
it to check: it should show the Auth0 "Welcome / Log in to pre-sales-agent" card.

A healthy run ends like this:

```
==> database migrations
current: 0036_knowledge_checklists  head: 0036_knowledge_checklists
already at head; nothing to upgrade
==> smoke checks
api: {"status":"ok","version":"0.1.0-local","db":"ok"}
web: {"status":"ok","version":"0.1.0-local"}
web /: 307 http://localhost:3000/auth/login?returnTo=%2F
==> done: main @ cbe4519
```

Exit codes: `1` pull failed, `2` compose failed, `3` migration failed, `4` smoke failed.

To test the upgrade path without touching dev data, point the migration at `psa_test`:

```bash
# put psa_test one revision behind, then let the driver bring it back to head
docker compose --profile local exec -T -e PSA_MIGRATIONS_DATABASE_URL="postgresql+psycopg://<POSTGRES_USER>:<POSTGRES_PASSWORD>@postgres:5432/psa_test" api alembic downgrade 0035_knowledge_chunks
MIGRATE_DB=psa_test bash .claude/skills/run-pre-sales-agent/redeploy.sh --migrate
```

With `MIGRATE_DB` set, the driver doesn't restart `api` and `worker`.

## Run (human path)

Run the same script in Git Bash. Afterwards, open http://localhost:3000 and sign in with Auth0. pgAdmin is
at http://127.0.0.1:5050.

## Gotchas

- **Never downgrade the dev `psa` database to test migrations.** A downgrade drops the
  later tables and their data. Use `MIGRATE_DB=psa_test`.
- **Migrations need the owner role.** The `api` container connects as `psa_app`, which
  can't run DDL. The driver passes `PSA_MIGRATIONS_DATABASE_URL` (`POSTGRES_USER` @
  `postgres:5432`) only to the `alembic` exec.
- **Don't `source .env` in the shell.** It also exports the model-profile variables, which
  then leak into anything else run from that shell. The driver reads only the three
  `POSTGRES_*` values, with `grep`.
- **Pull auth:** the default Git credential (`shanil-melder`) gets a 403 on writes to this
  repo, and may on reads. If the plain fetch fails, the driver retries with
  `gh auth token -u shanilmelder`, without changing gh's active account. On 2026-10-23 the
  plain fetch worked, so this fallback hasn't run yet.
- **The restart after a migration is unverified on dev data.** The upgrade was tested on
  `psa_test`, where the restart is skipped. The first real pending migration on `psa` will
  be the first run of `restart api worker`.
- **A diverged branch stops the run (exit 1).** The driver only fast-forwards, so rebase or
  merge by hand first.
- **Only `/healthz` is public on web.** Every other page answers 307 to `/auth/login`, then
  redirects to the Auth0 hosted page. The screenshot therefore shows Auth0 sign-in, not app
  content. Seeing it proves `web` is serving and the Auth0 config is valid. Pages behind
  sign-in need a real session.
- **Images build from the working tree,** uncommitted edits included. That covers local
  changes to `compose.yaml`, such as the pgAdmin service.
- **`--force-recreate` restarts Postgres too.** Data survives in the `pgdata` volume, but
  any open pgAdmin or `psql` sessions drop.

## Troubleshooting

- **`password authentication failed for user "psa"` when connecting from the host:** the
  owner password is `POSTGRES_PASSWORD` in `.env`, not `psa`. The app role is `psa_app`
  with `PSA_APP_DB_PASSWORD`.
- **`fatal: 'orgin' does not appear to be a git repository`:** the remote is named
  `origin`. The driver always uses `origin`.
