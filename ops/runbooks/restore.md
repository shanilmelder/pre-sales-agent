# Restore and the retention purge

Story 10.6. How a database restore interacts with the controlled retention purge.

## What the purge does

- The worker's daily `platform.purge` job (row `platform.purge` in `platform_schedules`,
  every 86,400 s) deletes every Opportunity whose retention date has passed: lost, the day
  the outcome was recorded plus 3 years; won, the contract end date plus 7 years. Open
  Opportunities are never purged.
- It connects as the privileged `psa_purge` role (`PSA_PURGE_DATABASE_URL`, worker only).
  Without that URL it logs `purge.not_configured` and deletes nothing.
- The role can log in only if it has a password. Set `PSA_PURGE_DB_PASSWORD` when migration
  0058 runs (or on a fresh volume, for the postgres init script); otherwise the role is
  created `NOLOGIN` and the purge cannot connect: it deletes nothing (each daily run fails
  to connect and, on its last attempt, sends a "could not run" alert). To give an existing
  role a password afterwards, as the owner:

  ```sql
  ALTER ROLE psa_purge LOGIN PASSWORD '<a strong, URL-safe password>';
  ```

  and set `PSA_PURGE_DATABASE_URL=postgresql+psycopg://psa_purge:<that password>@postgres:5432/<db>`
  for the worker.
- Each Opportunity is purged in its own transaction, with a `platform.purge.completed` trace
  event (ids and counts only). Admin > Retention lists what is due and the last purges.
- Nothing else deletes Opportunity data; there is no on-demand delete.

## Backups must age out purged data

**Requirement for the backup setup:** backups must be kept for **at most 35 days** (the
retention period the deletion duties assume) and must not be copied anywhere they would be
kept longer. Check this when configuring or changing backups; nothing in the application
enforces it. Data the purge deleted stays in older backups until they age out, so with a
35-day limit it is gone from every copy at most 35 days after its purge.

## After any restore: purge before users return

A restored database can bring back Opportunities that were already purged (their retention
date is still in the past). Run the purge **before** users are let back in:

1. Restore the database; keep the `api` (and `web`) stopped.
2. Run migrations (`alembic upgrade head`) as usual.
3. Make sure `psa_purge` can log in (see above: `PSA_PURGE_DB_PASSWORD` set when the
   migrations ran, or `ALTER ROLE psa_purge LOGIN PASSWORD ...`), start the `worker` with
   `PSA_PURGE_DATABASE_URL` set, and make the purge run now instead
   of waiting for its schedule:

   ```sh
   docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "UPDATE platform_schedules SET next_run_at = now() WHERE name = 'platform.purge'"
   ```

   The worker enqueues it within a minute.
4. Check the worker log for `purge.completed` with `failed: 0` (and no
   `purge.not_configured`), or in SQL that the job succeeded:

   ```sql
   SELECT status, attempts, last_error FROM platform_jobs
   WHERE job_type = 'platform.purge' ORDER BY created_at DESC LIMIT 1;
   ```

   If it failed, fix the cause (the log names the Opportunity UUIDs and the error class) and
   repeat step 3. Reruns are safe: purged Opportunities are not selected again.
5. Only then start the `api` and `web` and let users back in.

The restored blobs (`files` volume) follow the same rule: restore the volume from the same
point in time as the database, so the purge's reference counts match the files.
