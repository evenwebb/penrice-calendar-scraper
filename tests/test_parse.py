"""Tests for date parsing and per-line event extraction."""

import datetime

import pytest

from generate_ics import (
    TERM_RESUME_PHRASES,
    _is_term_resume_event,
    date_from_parts,
    parse_date,
    parse_event_line,
    process_events,
)


def test_date_from_parts_valid() -> None:
    d = date_from_parts(5, "January", 2026)
    assert d == datetime.date(2026, 1, 5)


def test_date_from_parts_invalid_month() -> None:
    assert date_from_parts(5, "Januarv", 2026) is None


def test_parse_date_delegates_to_parts() -> None:
    assert parse_date("5th January 2026 - Term") == datetime.date(2026, 1, 5)


def test_dual_day_inset_range() -> None:
    line = (
        "Tuesday 1st and Wednesday 2nd September 2026: "
        "Staff INSET Days (Students not required to attend)"
    )
    evs = parse_event_line(line)
    assert len(evs) == 1
    ev = evs[0]
    assert ev.start == datetime.date(2026, 9, 1)
    assert ev.end == datetime.date(2026, 9, 2)
    assert "INSET" in ev.summary
    assert ev.suppress_half_term_week_expand is False


def test_range_two_dates() -> None:
    line = "Monday 16th February 2026 to Friday 20th February 2026 - Half Term"
    evs = parse_event_line(line)
    assert len(evs) == 1
    assert evs[0].start == datetime.date(2026, 2, 16)
    assert evs[0].end == datetime.date(2026, 2, 20)


def test_ampersand_two_dates() -> None:
    line = "1st January 2026 & 2nd January 2026 INSET Days"
    evs = parse_event_line(line)
    assert len(evs) == 2
    assert {ev.start for ev in evs} == {
        datetime.date(2026, 1, 1),
        datetime.date(2026, 1, 2),
    }


def test_three_dates_skipped_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    line = (
        "1st January 2026 - 2nd February 2026 - 3rd March 2026 "
        "Impossible triple range"
    )
    with caplog.at_level("WARNING"):
        evs = parse_event_line(line)
    assert evs == []
    assert "Expected exactly 2 dates" in caplog.text


def test_ampersand_wrong_match_count_skipped(caplog: pytest.LogCaptureFixture) -> None:
    line = "1st January 2026 & 2nd January 2026 & 3rd January 2026 x"
    with caplog.at_level("WARNING"):
        evs = parse_event_line(line)
    assert evs == []
    assert " & " in caplog.text or "skipping" in caplog.text


def test_half_term_afternoon_suppresses_week_expand() -> None:
    line = "Thursday 16th October 2025 - Half Term Begins at 3:00pm"
    evs = parse_event_line(line)
    assert len(evs) == 1
    assert evs[0].suppress_half_term_week_expand is True
    out = process_events([line])
    assert len(out) == 1
    assert out[0].start == datetime.date(2025, 10, 16)
    assert out[0].end == datetime.date(2025, 10, 16)


@pytest.mark.parametrize("phrase", TERM_RESUME_PHRASES)
def test_term_resume_phrases(phrase: str) -> None:
    assert _is_term_resume_event(f"Penrice {phrase.title()} for everyone")


def test_term_resume_phrase_config_nonempty() -> None:
    assert len(TERM_RESUME_PHRASES) >= 2
