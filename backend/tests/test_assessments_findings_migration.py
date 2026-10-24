"""Migration 0042 (Story 6.6) against a real Postgres: the backfill of Findings stored before
it. A Red Team Finding with Requirement and Estimate line links and Critic Findings (one citing
a Security Agent Finding) are stored, the database is taken back to 0041 and up to head again,
and every backfilled fingerprint must equal the app's `fingerprint(...)`, with
`security_discipline` set only for the Critic Finding citing the Security Agent.

Needs `PSA_MIGRATIONS_DATABASE_URL` (the owner role) to migrate."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.modules.assessments.domain.findings import fingerprint, line_key
from tests import test_assessments_red_team as red_team_tests
from tests import test_assessments_specialists as specialist_tests
from tests import test_estimates_draft as draft_tests
from tests import test_gaps_detection as detection_tests
from tests import test_intake_extraction as extraction_tests
from tests.test_assessments_critic import HAPPY
from tests.test_assessments_red_team import drafted, finding, findings_out
from tests.test_assessments_specialists import AgentGateway, install, prepared, replies, started
from tests.test_gaps_detection import rows
from tests.test_intake_extraction import ASSESS, RED_TEAM, FakeGateway, drain
from tests.test_intake_parse_job import _alembic

storage_dir = extraction_tests.storage_dir
_hidden_jobs = extraction_tests._hidden_jobs
gateway = extraction_tests.gateway
client = extraction_tests.client
_chat_profile = detection_tests._chat_profile
_draft_profile = draft_tests._draft_profile
_review_profile = red_team_tests._review_profile
_assessment_profile = specialist_tests._assessment_profile
_no_auto_run = specialist_tests._no_auto_run


def _findings(engine: Engine, opp_id: str) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT f.id, f.category, f.fingerprint, f.security_discipline, f.status, "
        "f.row_version, r.kind FROM assessments_findings f "
        "JOIN assessments_reviews r ON r.id = f.review_id WHERE r.opportunity_id = :o",
        o=opp_id,
    )


def _expected(engine: Engine, row: dict[str, Any]) -> str:
    requirements = [
        r["requirement_id"]
        for r in rows(
            engine,
            "SELECT requirement_id FROM assessments_finding_requirements WHERE finding_id = :f",
            f=row["id"],
        )
    ]
    keys = [
        line_key(r["section"], r["title"])
        for r in rows(
            engine,
            "SELECT l.section, l.title FROM assessments_finding_lines fl "
            "JOIN estimates_estimate_lines l ON l.id = fl.line_id WHERE fl.finding_id = :f",
            f=row["id"],
        )
    ] + [
        str(r["assessment_finding_id"])
        for r in rows(
            engine,
            "SELECT assessment_finding_id FROM assessments_finding_targets WHERE finding_id = :f",
            f=row["id"],
        )
    ]
    return fingerprint(row["kind"], row["category"], requirements, keys)


def test_the_upgrade_backfills_fingerprints_and_security_discipline(
    client: TestClient, sync_engine: Engine, db_url: str, gateway: FakeGateway
) -> None:
    _, red_opp = drafted(client, sync_engine, db_url, gateway)
    gateway.replies = [
        findings_out(finding("SAP fields", ["R1", "R2"], lines=["SAP order interface"]))
    ]
    assert drain(db_url, RED_TEAM) == ["succeeded"]
    headers, critic_opp = prepared(client, sync_engine, db_url, gateway)
    install(AgentGateway(replies(critic_agent=[HAPPY])))
    started(client, headers, critic_opp["id"])
    assert drain(db_url, ASSESS) == ["succeeded"]

    _alembic("downgrade", "0041_critic_review")
    _alembic("upgrade", "head")

    (red,) = _findings(sync_engine, red_opp["id"])
    assert red["kind"] == "red_team"
    assert red["fingerprint"] == _expected(sync_engine, red)
    assert (red["security_discipline"], red["status"], red["row_version"]) == (False, "open", 1)
    critic = {f["category"]: f for f in _findings(sync_engine, critic_opp["id"])}
    assert len(critic) == 4
    for row in critic.values():
        assert row["kind"] == "critic"
        assert row["fingerprint"] == _expected(sync_engine, row)
        assert row["status"] == "open"
    # Only the Finding citing the Security Agent's F9 is security discipline.
    assert {c: f["security_discipline"] for c, f in critic.items()} == {
        "unsupported_claim": False,
        "timeline": False,
        "dependency": False,
        "risk_coverage": True,
    }
