#!/bin/sh
# Creates the retention purge role (`psa_purge`, Story 10.6): the only role allowed to delete
# Opportunity data, used only by the worker's daily `platform.purge` job.
#
# Run by the postgres image's entrypoint from /docker-entrypoint-initdb.d on first start of
# an empty data volume only (after 10-app-role.sh). Existing volumes: migration 0058 creates
# the role, and sets its password when PSA_PURGE_DB_PASSWORD is set while it runs.
#
# Table privileges are granted by Alembic migration 0058, which runs as the owner role.
# Requires: POSTGRES_USER, POSTGRES_DB. Optional: PSA_PURGE_DB_PASSWORD (unset: the role is
# created NOLOGIN and the purge job logs `purge.not_configured` or cannot connect).

set -e

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v purge_password="${PSA_PURGE_DB_PASSWORD:-}" -v db_name="$POSTGRES_DB" <<'EOSQL'
SELECT 'CREATE ROLE psa_purge NOLOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'psa_purge')
\gexec
SELECT format('ALTER ROLE psa_purge WITH LOGIN PASSWORD %L', :'purge_password')
WHERE :'purge_password' <> ''
\gexec
GRANT CONNECT ON DATABASE :"db_name" TO psa_purge;
EOSQL
