"""Alembic environment. The URL comes only from `app.platform.config` (PSA_DATABASE_URL).

Migrations are expand/contract only (AD-19). They run synchronously through psycopg 3.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.platform.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Module metadata is registered here once modules own tables (Story 1.4+).
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
