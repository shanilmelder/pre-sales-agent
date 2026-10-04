"""Alembic environment. URLs come only from `app.platform.config`.

Migrations run as the schema owner role (PSA_MIGRATIONS_DATABASE_URL, falling back to
PSA_DATABASE_URL); the app connects as `psa_app`. Migrations are expand/contract only
(AD-19) and run synchronously through psycopg 3.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Model imports register their tables on Base.metadata.
import app.modules.assessments.adapters.models
import app.modules.estimates.adapters.models
import app.modules.gaps.adapters.models
import app.modules.identity.adapters.models
import app.modules.intake.adapters.models
import app.modules.opportunities.adapters.models
import app.platform.files
import app.platform.jobs.models
import app.platform.model_gateway.models
import app.platform.trace.models  # noqa: F401
from app.platform.config import get_settings
from app.platform.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
APP_ROLE = "psa_app"


def _url() -> str:
    settings = get_settings()
    return settings.migrations_database_url or settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # Alembic reads alembic_version before any migration runs, so the app role would
        # otherwise fail with an opaque "permission denied for table alembic_version".
        current_user = connection.exec_driver_sql("SELECT current_user").scalar()
        # End the transaction that query autobegan: otherwise Alembic's begin_transaction()
        # joins it, never commits, and every migration is rolled back on close.
        connection.rollback()
        if current_user == APP_ROLE:
            raise SystemExit(
                f"Migrations must run as the schema owner, not {APP_ROLE}: set "
                "PSA_MIGRATIONS_DATABASE_URL to the owner role's URL."
            )
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
