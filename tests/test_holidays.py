"""Tests for inferred holiday periods."""

import datetime

from generate_ics import END_OF_TERM_PHRASES, TERM_RESUME_PHRASES, CalendarEvent, infer_holidays


def test_infer_summer_holiday_uses_first_day_of_term() -> None:
    events = [
        CalendarEvent(
            datetime.date(2026, 7, 24),
            datetime.date(2026, 7, 24),
            "End of Term (Last day)",
            False,
        ),
        CalendarEvent(
            datetime.date(2026, 9, 3),
            datetime.date(2026, 9, 3),
            "First Day of Term",
            False,
        ),
    ]
    hol = infer_holidays(events)
    assert len(hol) == 1
    assert hol[0].start == datetime.date(2026, 7, 25)
    assert hol[0].end == datetime.date(2026, 9, 2)
    assert "Summer" in hol[0].summary


def test_infer_skips_when_no_term_resume() -> None:
    events = [
        CalendarEvent(
            datetime.date(2027, 7, 23),
            datetime.date(2027, 7, 23),
            "Final Day of Term",
            False,
        ),
    ]
    assert infer_holidays(events) == []


def test_phrase_constants_document_site_variants() -> None:
    assert "term begins" in TERM_RESUME_PHRASES
    assert "first day of term" in TERM_RESUME_PHRASES
    assert "end of term" in END_OF_TERM_PHRASES
    assert "final day of term" in END_OF_TERM_PHRASES
