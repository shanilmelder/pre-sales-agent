"""Opportunity outcome and retention (Story 10.5): pure domain rules, no database."""

from datetime import UTC, date, datetime

import pytest

from app.modules.opportunities.domain.opportunity import (
    OpportunityStatus,
    Outcome,
    add_years,
    check_contract_end_date,
    derived_status,
    outcome_reason,
    retention_until,
)


def test_lost_is_kept_three_years_after_the_outcome_is_recorded() -> None:
    recorded = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
    assert retention_until(Outcome.LOST, recorded, None) == date(2029, 10, 14)
    # A plain date works too, and a contract end date plays no part.
    assert retention_until(Outcome.LOST, date(2026, 10, 14), date(2040, 1, 1)) == date(2029, 10, 14)


def test_won_is_kept_seven_years_after_contract_end() -> None:
    recorded = datetime(2026, 10, 14, tzinfo=UTC)
    assert retention_until(Outcome.WON, recorded, date(2028, 6, 30)) == date(2035, 6, 30)


def test_open_is_never_purged() -> None:
    assert retention_until(None, None, None) is None
    assert retention_until(None, datetime(2026, 1, 1, tzinfo=UTC), date(2027, 1, 1)) is None


def test_a_missing_date_gives_no_retention_date() -> None:
    assert retention_until(Outcome.LOST, None, None) is None
    assert retention_until(Outcome.WON, datetime(2026, 1, 1, tzinfo=UTC), None) is None


def test_leap_day_moves_to_28_february() -> None:
    assert retention_until(Outcome.LOST, date(2028, 2, 29), None) == date(2031, 2, 28)
    assert retention_until(Outcome.WON, None, date(2028, 2, 29)) == date(2035, 2, 28)
    # Landing on a leap year keeps the 29th.
    assert add_years(date(2024, 2, 29), 4) == date(2028, 2, 29)
    assert add_years(date(2027, 3, 1), 1) == date(2028, 3, 1)


def test_add_years_past_the_last_year_raises() -> None:
    with pytest.raises(ValueError, match="year"):
        add_years(date(9998, 1, 1), 3)


def test_contract_end_date_must_leave_room_for_retention() -> None:
    assert check_contract_end_date(date(9992, 12, 31)) == date(9992, 12, 31)
    with pytest.raises(ValueError, match="before 9993"):
        check_contract_end_date(date(9993, 1, 1))


def test_lost_derives_closed_above_everything() -> None:
    assert derived_status(outcome=Outcome.LOST) is OpportunityStatus.CLOSED
    assert derived_status(True, delivered=True, outcome=Outcome.LOST) is OpportunityStatus.CLOSED


def test_won_keeps_the_status_its_data_gives_it() -> None:
    assert derived_status(True, outcome=Outcome.WON) is OpportunityStatus.BASELINED
    assert derived_status(True, delivered=True, outcome=Outcome.WON) is OpportunityStatus.DELIVERED
    assert derived_status(outcome=Outcome.WON) is OpportunityStatus.INTAKE


def test_outcome_reason_is_trimmed_and_required() -> None:
    assert outcome_reason("  Customer chose a rival  ") == "Customer chose a rival"
    for blank in (None, "", "   "):
        with pytest.raises(ValueError):
            outcome_reason(blank)
    assert len(outcome_reason("x" * 1000)) == 1000
    with pytest.raises(ValueError):
        outcome_reason("x" * 1001)
