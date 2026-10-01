"""The least-privileged app role (migration 0002): default privileges and no DDL."""

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
