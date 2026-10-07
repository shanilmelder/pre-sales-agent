"""Knowledge Source rules (Story 3.2) that need no database: the derived stale flag, field
rules, the shared upload checks with `.md`, signed download links, the owner grant and the
knowledge parse child."""

import io
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.modules.identity.actions import Action
from app.modules.identity.domain.policy import (
    KNOWLEDGE_SOURCE_OWNER_GRANTS,
    KNOWLEDGE_SOURCE_RESOURCE,
    OPPORTUNITY_RESOURCE,
    Principal,
    Resource,
    is_allowed,
)
from app.modules.identity.domain.roles import Role
from app.modules.knowledge.adapters import parse_runner
from app.modules.knowledge.domain import sources as rules
from app.platform import downloads
from app.platform.actor import Actor
from app.platform.errors import ForbiddenError
from app.platform.upload_validation import content_matches, extension
from tests.conftest import run_async

KEY = "a-test-signing-key-long-enough"


# --- stale ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reviewed", "stale"),
    [
        (date(2026, 10, 7), False),
        (date(2025, 10, 7), False),  # exactly twelve months ago: not yet stale
        (date(2025, 10, 6), True),  # one day past twelve months
        (date(2024, 1, 1), True),
    ],
)
def test_stale_is_older_than_twelve_months(reviewed: date, stale: bool) -> None:
    assert rules.is_stale(reviewed, date(2026, 10, 7), 12) is stale


def test_months_are_calendar_months_clamped_to_the_month_end() -> None:
    assert rules.subtract_months(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert rules.subtract_months(date(2024, 3, 31), 1) == date(2024, 2, 29)
    assert rules.subtract_months(date(2026, 1, 15), 12) == date(2025, 1, 15)
    assert rules.subtract_months(date(2026, 1, 15), 13) == date(2024, 12, 15)
    assert rules.is_stale(date(2026, 3, 31), date(2026, 10, 7), 6) is True
    assert rules.is_stale(date(2026, 4, 7), date(2026, 10, 7), 6) is False


# --- fields -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "limit"),
    [
        (rules.source_title, 200),
        (rules.source_product, 120),
        (rules.product_version, 60),
        (rules.retire_reason, 500),
    ],
)
def test_field_bounds_and_trimming(rule, limit: int) -> None:  # type: ignore[no-untyped-def]
    assert rule("  x  ") == "x"
    assert rule("x" * limit) == "x" * limit
    for bad in ("", "   ", "x" * (limit + 1), "a\x00b"):
        with pytest.raises(ValueError, match="The "):
            rule(bad)


def test_tags_need_at_least_one_and_are_distinct() -> None:
    a, b = uuid4(), uuid4()
    assert rules.distinct_tags([a, b, a]) == [a, b]
    with pytest.raises(ValueError, match="at least one"):
        rules.distinct_tags([])
    with pytest.raises(ValueError, match="at most"):
        rules.distinct_tags([uuid4() for _ in range(rules.TAGS_MAX + 1)])


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("a.pdf", True),
        ("A.DOCX", True),
        ("a.txt", True),
        ("a.md", True),
        ("a.eml", False),
        ("a.vtt", False),
        ("a.msg", False),
        ("md", False),
        ("a.", False),
    ],
)
def test_the_allowlist(name: str, ok: bool) -> None:
    assert rules.allowed(name) is ok


# --- shared upload checks, `.md` ----------------------------------------------------------------


def test_md_must_be_utf8_text_without_nul_bytes() -> None:
    assert extension("Guide.MD") == ".md"
    assert content_matches(".md", io.BytesIO("# Titel\nstraße\n".encode())) is True
    assert content_matches(".md", io.BytesIO(b"\xff\xfe\x00")) is False
    assert content_matches(".md", io.BytesIO(b"a\x00b")) is False


def test_md_is_parsed_as_text_by_the_platform_parser() -> None:
    from app.platform.parsing.parsers import parse

    result = parse("﻿# Guide\r\nText".encode(), ".md")
    assert result.text == "# Guide\nText" and result.parser == "markdown@1"
    assert parse(b"x", ".txt").parser == "text@1"


# --- signed downloads ---------------------------------------------------------------------------


def test_a_signed_link_round_trips_and_expires() -> None:
    sha = "a" * 64
    token, expires = downloads.sign(KEY, sha256=sha, filename="Guide v1.pdf", ttl_s=300, now=1000)
    assert expires == datetime.fromtimestamp(1300, UTC)
    grant = downloads.verify(KEY, token, now=1299)
    assert (grant.sha256, grant.filename) == (sha, "Guide v1.pdf")
    with pytest.raises(ForbiddenError):
        downloads.verify(KEY, token, now=1301)  # expired
    assert downloads.link_for(token) == f"/api/v1/downloads/{token}"


@pytest.mark.parametrize("mangle", ["wrong key", "tampered body", "tampered mac", "junk", "empty"])
def test_a_bad_link_is_forbidden(mangle: str) -> None:
    token, _ = downloads.sign(KEY, sha256="b" * 64, filename="x.pdf", ttl_s=300, now=1000)
    body, mac = token.split(".")
    bad = {
        "wrong key": token,
        "tampered body": f"{body[:-2]}AA.{mac}",
        "tampered mac": f"{body}.{mac[:-2]}AA",
        "junk": "not-a-token",
        "empty": "",
    }[mangle]
    key = "another-signing-key-entirely" if mangle == "wrong key" else KEY
    with pytest.raises(ForbiddenError):
        downloads.verify(key, bad, now=1100)


def test_signing_rejects_a_non_hash() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        downloads.sign(KEY, sha256="../etc/passwd", filename="x", ttl_s=1)


# --- authorization ------------------------------------------------------------------------------


def _principal(user_id, *roles: Role) -> Principal:  # type: ignore[no-untyped-def]
    return Principal(actor=Actor(type="user", id=str(user_id)), roles=frozenset(roles))


def test_the_owner_may_write_their_source_but_not_register_for_others() -> None:
    owner_id = uuid4()
    source = Resource(type=KNOWLEDGE_SOURCE_RESOURCE, id=uuid4(), owner_id=owner_id)
    owner = _principal(owner_id, Role.COMMERCIAL)
    for action in KNOWLEDGE_SOURCE_OWNER_GRANTS:
        assert is_allowed(owner, action, source) is True
    assert is_allowed(owner, Action.KNOWLEDGE_SOURCE_REGISTER, source) is False
    stranger = _principal(uuid4(), Role.COMMERCIAL)
    assert all(not is_allowed(stranger, a, source) for a in KNOWLEDGE_SOURCE_OWNER_GRANTS)
    admin = _principal(uuid4(), Role.PLATFORM_ADMINISTRATOR)
    assert all(is_allowed(admin, a, source) for a in KNOWLEDGE_SOURCE_OWNER_GRANTS)


def test_an_owner_who_lost_every_role_loses_access() -> None:
    owner_id = uuid4()
    source = Resource(type=KNOWLEDGE_SOURCE_RESOURCE, id=uuid4(), owner_id=owner_id)
    assert is_allowed(_principal(owner_id), Action.KNOWLEDGE_SOURCE_REVIEW, source) is False


def test_opportunity_grants_do_not_apply_to_knowledge_sources() -> None:
    user_id = uuid4()
    opportunity = Resource(type=OPPORTUNITY_RESOURCE, id=uuid4(), owner_id=user_id)
    me = _principal(user_id, Role.PRESALES_ENGINEER)
    assert is_allowed(me, Action.KNOWLEDGE_SOURCE_REVIEW, opportunity) is False
    assert is_allowed(me, Action.SOURCE_ADD, opportunity) is True


def test_registering_is_for_administrators_only() -> None:
    allowed = {Role.PLATFORM_ADMINISTRATOR}
    for role in Role:
        assert is_allowed(_principal(uuid4(), role), Action.KNOWLEDGE_SOURCE_REGISTER) is (
            role in allowed
        )


# --- the knowledge parse child ------------------------------------------------------------------


def test_the_knowledge_child_parses_md_and_reports_corrupt_files(tmp_path: Path) -> None:
    good = tmp_path / "g.md"
    good.write_bytes(b"# Hello\nworld\n")
    out = run_async(parse_runner.run_parse(good, ".md", timeout_s=60, max_memory_mb=1024))
    assert (out.text, out.parser) == ("# Hello\nworld\n", "markdown@1")

    from app.platform.parsing.rules import ParseError

    bad = tmp_path / "b.pdf"
    bad.write_bytes(b"%PDF-1.7 garbage")
    with pytest.raises(ParseError) as caught:
        run_async(parse_runner.run_parse(bad, ".pdf", timeout_s=60, max_memory_mb=1024))
    assert caught.value.code.value == "unreadable"
    with pytest.raises(ParseError) as unsupported:
        run_async(parse_runner.run_parse(bad, ".eml", timeout_s=60, max_memory_mb=1024))
    assert unsupported.value.code.value == "not_supported"
