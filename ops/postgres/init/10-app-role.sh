#!/bin/sh
# Creates the least-privileged login role the application connects as (`psa_app`).
#
# Run by the postgres image's entrypoint from /docker-entrypoint-initdb.d on first start of
# an empty data volume only. Existing volumes need `docker compose down -v` once.
# CI runs this script directly against its Postgres service (PGHOST/PGPASSWORD set).
#
# Table privileges are granted by Alembic migrations, which run as the owner role.
# Requires: POSTGRES_USER, POSTGRES_DB, PSA_APP_DB_PASSWORD.

set -e

if [ -z "${PSA_APP_DB_PASSWORD:-}" ]; then
    echo "10-app-role.sh: PSA_APP_DB_PASSWORD must be set" >&2
    exit 1
fi

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v app_password="$PSA_APP_DB_PASSWORD" -v db_name="$POSTGRES_DB" <<'EOSQL'
SELECT format('CREATE ROLE psa_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'psa_app')
\gexec
SELECT format('ALTER ROLE psa_app WITH LOGIN PASSWORD %L', :'app_password')
\gexec
GRANT CONNECT, TEMPORARY ON DATABASE :"db_name" TO psa_app;
EOSQL
