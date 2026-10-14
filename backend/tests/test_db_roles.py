"""The least-privileged app role (migration 0002): default privileges and no DDL outside the
checkpointer's schema (migration 0028)."""

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine


def test_default_privileges_cover_later_tables_and_sequences(sync_engine: Engine) -> None:
    with sync_engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT d.defaclobjtype AS objtype, a.privilege_type AS privilege "
                "FROM pg_default_acl d "
                "JOIN pg_namespace n ON n.oid = d.defaclnamespace "
                "CROSS JOIN LATERAL aclexplode(d.defaclacl) a "
                "WHERE n.nspname = 'public' AND a.grantee = 'psa_app'::regrole"
            )
        ).all()
    granted: dict[str, set[str]] = {}
    for objtype, privilege in rows:
        granted.setdefault(objtype, set()).add(privilege)
    assert granted == {
        "r": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "S": {"USAGE", "SELECT"},
    }


def test_app_role_cannot_create_tables_in_public(sync_engine: Engine) -> None:
    with sync_engine.connect() as conn:
        role: str = conn.execute(sa.text("SELECT current_user")).scalar_one()
        assert role == "psa_app", "DB-backed tests must run as psa_app (see README)"
        with pytest.raises(sa.exc.ProgrammingError) as info:
            conn.execute(sa.text("CREATE TABLE public.psa_app_must_not_create (id int)"))
        assert isinstance(info.value.orig, psycopg.errors.InsufficientPrivilege)
        conn.rollback()


def test_app_role_can_create_the_checkpointer_tables_in_their_own_schema(
    sync_engine: Engine,
) -> None:
    """Story 5.2: the migrations create `orchestration_checkpoints` and grant `psa_app` USAGE
    and CREATE there, so the worker's checkpointer `setup()` can create its tables."""
    with sync_engine.connect() as conn:
        conn.execute(sa.text("CREATE TABLE orchestration_checkpoints.psa_app_probe (id int)"))
        conn.rollback()
        with pytest.raises(sa.exc.ProgrammingError) as info:
            conn.execute(sa.text("CREATE SCHEMA psa_app_must_not_create"))
        assert isinstance(info.value.orig, psycopg.errors.InsufficientPrivilege)
        conn.rollback()
