"""Tests for HTML line extraction (no network)."""

import datetime
import re
from pathlib import Path

from generate_ics import extract_lines_from_html, make_ics_event

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "term_dates_snippet.html"


def test_extract_lines_from_html_finds_content_region() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    lines = extract_lines_from_html(html)
    assert any("Term Begins" in ln for ln in lines)
    assert any("Staff INSET" in ln for ln in lines)
    assert any("Half Term Begins at 3:00pm" in ln for ln in lines)


def test_make_ics_event_shape() -> None:
    block = make_ics_event(
        datetime.date(2026, 1, 5),
        datetime.date(2026, 1, 5),
        "Term Begins",
    )
    assert "BEGIN:VEVENT" in block
    assert "DTSTART;VALUE=DATE:20260105" in block
    assert "DTEND;VALUE=DATE:20260106" in block
    assert re.search(r"SUMMARY:Penrice.*Term", block)
