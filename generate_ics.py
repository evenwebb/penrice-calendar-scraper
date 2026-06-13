"""
Penrice Academy Calendar Scraper

This script scrapes term dates from the Penrice Academy website and generates
an iCalendar (.ics) file that can be imported into calendar applications.
"""

import datetime
import hashlib
import logging
import os
import re
import time
from typing import NamedTuple, Optional

import requests
from bs4 import BeautifulSoup, Tag


# ============================================================================
# Configuration
# ============================================================================

URL = "https://www.penriceacademy.org/page/?title=Term+Dates&pid=49"

# Toggle generation of scraped events (directly parsed from the website).
CREATE_SCRAPED_EVENTS = True
# Toggle generation of inferred holiday breaks between term dates.
CREATE_HOLIDAY_EVENTS = True

# Words that should be Title Cased in event summaries.
TITLECASE_WORDS = ["term", "holiday", "half", "INSET"]

# HTTP request configuration
DEFAULT_RETRIES = 3
DEFAULT_TIMEOUT = 30
INITIAL_RETRY_DELAY = 1

# iCalendar configuration
CALENDAR_PREFIX = "Penrice"
PRODID = "-//Penrice Academy//EN"
OUTPUT_DIR = "docs"
OUTPUT_FILENAME = "penrice.ics"
SITE_URL = "https://evenwebb.github.io/penrice-calendar-scraper"
LOG_FILENAME = "log.txt"
ICAL_LINE_LENGTH = 75
ICAL_NEWLINE = "\r\n"
CALENDAR_TIMEZONE = "Europe/London"

# Half term duration in days (Monday to Friday)
HALF_TERM_WEEKDAYS = 5

# Month mappings for holiday naming
CHRISTMAS_MONTHS = {12, 1}
SPRING_HALF_TERM_MONTH = 2
EASTER_MONTHS = {3, 4}
SUMMER_HALF_TERM_MONTHS = {5, 6}
SUMMER_HOLIDAY_MONTHS = {7, 8}
AUTUMN_HALF_TERM_MONTHS = {10, 11}

# Substrings (lowercase) for matching site copy when inferring holidays.
TERM_RESUME_PHRASES = (
    "term begins",
    "first day of term",
)
END_OF_TERM_PHRASES = (
    "end of term",
    "final day of term",
)


# ============================================================================
# Logging Setup
# ============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
error_handler = logging.FileHandler(LOG_FILENAME, mode='a', encoding='utf-8')
error_handler.setLevel(logging.ERROR)
logger.addHandler(error_handler)


# ============================================================================
# Event model
# ============================================================================


class CalendarEvent(NamedTuple):
    """One calendar row after parsing a source line."""

    start: datetime.date
    end: datetime.date
    summary: str
    suppress_half_term_week_expand: bool = False


# Backwards-compatible name for lists of scraped/normalised events
EventTuple = CalendarEvent


# ============================================================================
# Regular Expressions
# ============================================================================

DATE_RE = re.compile(
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})"
)
# "Tuesday 1st and Wednesday 2nd September 2026: ..." (two days, one month/year)
DUAL_DAY_SAME_MONTH_RE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+and\s+\w+\s+(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"([A-Za-z]+)\s+(\d{4})"
)
MONTH_NAMES = [datetime.date(2000, m, 1).strftime("%B").lower() for m in range(1, 13)]

_TITLECASE_PATTERN: Optional[re.Pattern[str]] = (
    re.compile(
        r"\b(" + "|".join(map(re.escape, TITLECASE_WORDS)) + r")\b",
        re.IGNORECASE,
    )
    if TITLECASE_WORDS
    else None
)


# ============================================================================
# HTTP Utilities
# ============================================================================

def fetch_with_retries(
    url: str,
    retries: int = DEFAULT_RETRIES,
    timeout: int = DEFAULT_TIMEOUT
) -> requests.Response:
    """
    Fetch a URL with exponential backoff retry logic.

    Args:
        url: The URL to fetch
        retries: Maximum number of retry attempts
        timeout: Request timeout in seconds

    Returns:
        Response object from successful request

    Raises:
        requests.RequestException: If all retry attempts fail
    """
    delay = INITIAL_RETRY_DELAY
    headers = {
        "User-Agent": "PenriceTermDatesScraper/1.0 (calendar automation; +https://www.penriceacademy.org/)"
    }
    with requests.Session() as session:
        session.headers.update(headers)
        for attempt in range(retries):
            try:
                response = session.get(url, timeout=timeout)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                logger.warning("Attempt %d failed: %s", attempt + 1, exc)
                if attempt == retries - 1:
                    raise
                time.sleep(delay)
                delay *= 2

    # This should never be reached, but satisfies type checker
    raise requests.RequestException("Failed to fetch URL after all retries")


# ============================================================================
# Date Parsing
# ============================================================================


def date_from_parts(
    day: int,
    month_str: str,
    year: int,
    *,
    context: str = "",
) -> Optional[datetime.date]:
    """
    Build a calendar date from day, full month name, and year.

    Centralises validation and logging for all structured date construction.
    """
    try:
        month = datetime.datetime.strptime(month_str, "%B").month
    except ValueError:
        logger.error(
            "Unrecognised month '%s'%s",
            month_str,
            f" in: {context}" if context else "",
        )
        return None
    try:
        return datetime.date(year, month, day)
    except ValueError:
        logger.error(
            "Invalid date %s-%s-%s%s",
            year,
            month_str,
            day,
            f" context: {context}" if context else "",
        )
        return None


def parse_date(text: str) -> Optional[datetime.date]:
    """
    Parse a date from text using the DATE_RE pattern.

    Args:
        text: String containing a date in format "DD Month YYYY"

    Returns:
        Parsed date object, or None if parsing fails
    """
    match = DATE_RE.search(text)
    if not match:
        return None

    day = int(match.group("day"))
    month_str = match.group("month")
    year = int(match.group("year"))
    return date_from_parts(day, month_str, year, context=text)


# ============================================================================
# Web Scraping
# ============================================================================

def _should_skip_line(line: str) -> bool:
    """
    Check if a line should be skipped during scraping.

    Args:
        line: The line to check

    Returns:
        True if the line should be skipped, False otherwise
    """
    if not line:
        return True

    lower_line = line.lower()
    skip_words = ("privacy", "cookies", "updated")
    return any(word in lower_line for word in skip_words)


def extract_lines_from_soup(soup: BeautifulSoup) -> list[str]:
    """
    Extract term-date lines from an already-parsed page (no network).

    Used by tests and by :func:`extract_lines_from_html`.
    """
    content: Optional[Tag] = soup.select_one("section.user-content")
    if not content:
        content = soup.select_one("div.content__region")

    lines: list[str] = []
    if not content:
        logger.warning("Could not find content section on page")
        return lines

    for paragraph in content.find_all("p"):
        text = paragraph.get_text("\n")
        for line in text.split("\n"):
            line = line.strip()
            if _should_skip_line(line):
                continue
            lines.append(line)

    return lines


def extract_lines_from_html(html: str) -> list[str]:
    """Parse HTML string and return term-date lines (no network)."""
    return extract_lines_from_soup(BeautifulSoup(html, "html.parser"))


def extract_lines() -> list[str]:
    """
    Scrape and extract term date lines from the Penrice Academy website.

    Returns:
        List of text lines containing term date information

    Raises:
        requests.RequestException: If fetching the URL fails
    """
    response = fetch_with_retries(URL)
    return extract_lines_from_html(response.text)


# ============================================================================
# Event Parsing
# ============================================================================

def _clean_event_summary(summary: str) -> str:
    """
    Clean and normalize event summary text.

    Args:
        summary: Raw summary text

    Returns:
        Cleaned summary text
    """
    summary = summary.strip(" -–")
    summary = re.sub(r"^\s*:\s*", "", summary)
    # Remove trailing "Begins at 3:00pm" text that indicates early finish
    summary = re.sub(r"\s*Begins at 3:00\s*pm\.?$", "", summary, flags=re.IGNORECASE)
    return summary


def _canonical_half_term_wording(summary: str) -> str:
    """Unify hyphenated or spaced 'half term' labels for downstream checks."""
    return re.sub(r"(?i)half[- ]term", "Half Term", summary)


# Half term that starts after school the same day — do not expand to Mon–Fri week.
_HALF_TERM_AFTERNOON_START = re.compile(
    r"half[- ]term.*begins\s+at\s+3:00\s*pm",
    re.IGNORECASE | re.DOTALL,
)


def _suppress_half_term_week_expand_from_tail(tail: str) -> bool:
    """
    True when the description after the date(s) marks half term beginning at 3pm.

    Detected on the raw tail before :func:`_clean_event_summary` so we do not
    depend on the full source line string elsewhere.
    """
    return bool(_HALF_TERM_AFTERNOON_START.search(tail))


def _try_parse_dual_day_same_month(line: str) -> Optional[list[CalendarEvent]]:
    """
    Parse two ordinal days sharing one month/year (inset-style lines on site).

    Example: "Tuesday 1st and Wednesday 2nd September 2026: Staff INSET ..."
    """
    match = DUAL_DAY_SAME_MONTH_RE.search(line)
    if not match:
        return None
    day_a, day_b = int(match.group(1)), int(match.group(2))
    month_str, year_str = match.group(3), match.group(4)
    year = int(year_str)
    start = date_from_parts(day_a, month_str, year, context=line)
    end = date_from_parts(day_b, month_str, year, context=line)
    if not start or not end:
        return None
    if start > end:
        start, end = end, start
    tail = line[match.end():]
    summary = _clean_event_summary(tail)
    return [CalendarEvent(start, end, summary, False)]


def _parse_single_date_event(
    line: str,
    match: re.Match[str]
) -> list[CalendarEvent]:
    """
    Parse events with a single date in the line.

    Args:
        line: The line containing the event
        match: The regex match for the date

    Returns:
        List of (start_date, end_date, summary) tuples
    """
    end_date = parse_date(match.group(0))
    if not end_date:
        logger.error("Could not parse date from line: %s", line)
        return []

    # Check if there's a day range (e.g., "3rd - 5th January")
    pre = line[:match.start()]
    left_part = pre.split("-")[0]

    tail = line[match.end():]
    suppress = _suppress_half_term_week_expand_from_tail(tail)

    if "-" in pre and not any(month in left_part.lower() for month in MONTH_NAMES):
        day_match = re.search(r"(\d{1,2})(?:st|nd|rd|th)?", left_part)
        if day_match:
            start_day = int(day_match.group(1))
            start_date = date_from_parts(
                start_day,
                datetime.date(end_date.year, end_date.month, 1).strftime("%B"),
                end_date.year,
                context=line,
            )
            if not start_date:
                return []
            summary = _clean_event_summary(tail)
            return [CalendarEvent(start_date, end_date, summary, suppress)]

    summary = _clean_event_summary(tail)
    return [CalendarEvent(end_date, end_date, summary, suppress)]


def _parse_multiple_single_dates(
    line: str,
    matches: list[re.Match[str]]
) -> list[CalendarEvent]:
    """
    Parse events with multiple individual dates (e.g., "1st Jan & 2nd Jan").

    Args:
        line: The line containing the events
        matches: List of regex matches for dates

    Returns:
        List of (start_date, end_date, summary) tuples
    """
    tail = line[matches[-1].end():]
    suppress = _suppress_half_term_week_expand_from_tail(tail)
    summary = _clean_event_summary(tail)
    events: list[CalendarEvent] = []

    for match in matches:
        date = parse_date(match.group(0))
        if not date:
            logger.error("Could not parse date from line: %s", line)
            return []
        events.append(CalendarEvent(date, date, summary, suppress))

    return events


def _parse_date_range_event(
    line: str,
    matches: list[re.Match[str]]
) -> list[CalendarEvent]:
    """
    Parse events with a date range (e.g., "1st Jan - 5th Jan").

    Args:
        line: The line containing the event
        matches: List of regex matches for dates

    Returns:
        List of (start_date, end_date, summary) tuples
    """
    start_date = parse_date(matches[0].group(0))
    end_date = parse_date(matches[1].group(0))

    if not start_date or not end_date:
        logger.error("Could not parse date range from line: %s", line)
        return []

    tail = line[matches[-1].end():]
    suppress = _suppress_half_term_week_expand_from_tail(tail)
    summary = _clean_event_summary(tail)
    return [CalendarEvent(start_date, end_date, summary, suppress)]


def parse_event_line(line: str) -> list[CalendarEvent]:
    """
    Parse event information from a single line of text.

    Handles various date formats:
    - Single date: "5th January 2024 Term Begins"
    - Date range: "3rd - 5th January 2024 INSET Days"
    - Multiple dates: "1st January 2024 & 2nd January 2024 INSET Days"

    Args:
        line: Text line containing event information

    Returns:
        List of :class:`CalendarEvent` rows parsed from the line.
    """
    dual = _try_parse_dual_day_same_month(line)
    if dual is not None:
        return dual

    matches = list(DATE_RE.finditer(line))
    if not matches:
        return []

    if len(matches) == 1:
        return _parse_single_date_event(line, matches[0])
    if " & " in line:
        if len(matches) == 2:
            return _parse_multiple_single_dates(line, matches)
        logger.warning(
            "Line contains ' & ' but has %d date match(es) (need 2); skipping: %s",
            len(matches),
            line[:200],
        )
        return []
    if len(matches) == 2:
        return _parse_date_range_event(line, matches)
    logger.warning(
        "Expected exactly 2 dates for a range line, found %d; skipping: %s",
        len(matches),
        line[:200],
    )
    return []


# ============================================================================
# Half Term Processing
# ============================================================================

def _normalize_half_term_summary(
    summary: str,
    start_date: datetime.date
) -> str:
    """
    Add specific season to generic 'Half Term' summaries.

    Args:
        summary: The event summary
        start_date: The start date of the event

    Returns:
        Normalized summary with specific season
    """
    if "Half Term" not in summary:
        return summary

    month = start_date.month
    if month == SPRING_HALF_TERM_MONTH:
        return summary.replace("Half Term", "Spring Half Term")
    elif month in SUMMER_HALF_TERM_MONTHS:
        return summary.replace("Half Term", "Summer Half Term")
    elif month in AUTUMN_HALF_TERM_MONTHS:
        return summary.replace("Half Term", "Autumn Half Term")

    return summary


def _expand_half_term_to_week(
    start_date: datetime.date,
    end_date: datetime.date,
    summary: str,
    suppress_week_expand: bool,
) -> tuple[datetime.date, datetime.date]:
    """
    Expand single-day half term events to full week.

    Args:
        start_date: Original start date
        end_date: Original end date
        summary: Event summary (half-term wording already canonicalised)
        suppress_week_expand: When True, half term starts after school the same day
            (parsed from the raw description tail); do not expand.

    Returns:
        Tuple of (expanded_start, expanded_end)
    """
    if (
        "Half Term" in summary
        and start_date == end_date
        and not suppress_week_expand
    ):
        week_start = start_date - datetime.timedelta(days=start_date.weekday())
        week_end = week_start + datetime.timedelta(days=HALF_TERM_WEEKDAYS - 1)
        return week_start, week_end

    return start_date, end_date


# ============================================================================
# iCalendar Generation
# ============================================================================

def _apply_titlecase(summary: str) -> str:
    """
    Apply Title Case to configured words in the summary.

    Args:
        summary: Event summary text

    Returns:
        Summary with Title Case applied to configured words
    """
    if _TITLECASE_PATTERN is None:
        return summary
    return _TITLECASE_PATTERN.sub(lambda m: m.group(0).title(), summary)


def _escape_and_fold_ical_text(text: str, prefix: str = "") -> str:
    """Escape and fold iCalendar text fields per RFC 5545."""
    escaped = (
        text.replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )
    full_line = prefix + escaped
    if len(full_line) <= ICAL_LINE_LENGTH:
        return full_line

    result = [full_line[:ICAL_LINE_LENGTH]]
    remaining = full_line[ICAL_LINE_LENGTH:]
    while remaining:
        result.append(" " + remaining[:ICAL_LINE_LENGTH - 1])
        remaining = remaining[ICAL_LINE_LENGTH - 1:]
    return ICAL_NEWLINE.join(result)


def make_ics_event(
    start: datetime.date,
    end: datetime.date,
    summary: str
) -> str:
    """
    Generate an iCalendar VEVENT string.

    Args:
        start: Event start date
        end: Event end date (inclusive)
        summary: Event description

    Returns:
        Formatted VEVENT string
    """
    summary = _apply_titlecase(summary)

    # All summaries should clearly indicate the source of the event
    prefixed_summary = f"{CALENDAR_PREFIX} {summary}".strip()

    # iCalendar DTEND is exclusive, so add one day
    dtend = end + datetime.timedelta(days=1)
    uid_seed = f"{start.isoformat()}|{end.isoformat()}|{prefixed_summary}"
    uid = f"{hashlib.sha1(uid_seed.encode('utf-8')).hexdigest()}@penrice-calendar"
    dtstamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}",
        _escape_and_fold_ical_text(prefixed_summary, "SUMMARY:"),
        "SEQUENCE:0",
        "END:VEVENT",
        "",
    ]
    return ICAL_NEWLINE.join(lines)


# ============================================================================
# Holiday Inference
# ============================================================================

def guess_holiday_name(start: datetime.date, end: datetime.date) -> str:
    """
    Infer holiday name based on the month of the break.

    Args:
        start: Holiday start date
        end: Holiday end date

    Returns:
        Descriptive name for the holiday period
    """
    month = start.month

    if month in CHRISTMAS_MONTHS:
        return "Christmas Holidays"
    if month == SPRING_HALF_TERM_MONTH:
        return "Spring Half Term"
    if month in EASTER_MONTHS:
        return "Easter Holiday"
    if month in SUMMER_HALF_TERM_MONTHS:
        return "Summer Half Term"
    if month in SUMMER_HOLIDAY_MONTHS:
        return "Summer Holidays"
    if month in AUTUMN_HALF_TERM_MONTHS:
        return "Autumn Half Term"

    return "Holiday"


def _is_term_resume_event(summary: str) -> bool:
    """True if this line marks when the next term starts (students back)."""
    s = summary.lower()
    return any(phrase in s for phrase in TERM_RESUME_PHRASES)


def _is_end_of_term_for_holiday(summary: str) -> bool:
    """Last day of teaching before a break (wording varies by year on the site)."""
    s = f" {summary.lower()} "
    return any(f" {phrase} " in s or s.startswith(f"{phrase} ") for phrase in END_OF_TERM_PHRASES)


def infer_holidays(events: list[CalendarEvent]) -> list[CalendarEvent]:
    """
    Infer holiday periods from End of Term and term-start events.

    Matches the next event whose summary indicates term resuming (e.g. Term
    Begins or First Day of Term). Wording varies by academic year on the site;
    missing a match pairs summer break with a later year and stretches the
    holiday incorrectly.

    Args:
        events: Parsed :class:`CalendarEvent` rows from the site

    Returns:
        Inferred holiday rows (same type; ``suppress_half_term_week_expand`` unused)
    """
    sorted_events = sorted(events, key=lambda e: e.start)
    holidays: list[CalendarEvent] = []

    for i, ev in enumerate(sorted_events):
        if not _is_end_of_term_for_holiday(ev.summary):
            continue

        # Find the next term-start event (wording differs across published years)
        next_start: Optional[datetime.date] = None
        for j in range(i + 1, len(sorted_events)):
            later = sorted_events[j]
            if _is_term_resume_event(later.summary):
                next_start = later.start
                break

        if next_start:
            # Holiday starts the day after term ends
            hol_start = ev.end + datetime.timedelta(days=1)
            # Holiday ends the day before term begins
            hol_end = next_start - datetime.timedelta(days=1)

            if hol_start <= hol_end:
                name = guess_holiday_name(hol_start, hol_end)
                holidays.append(CalendarEvent(hol_start, hol_end, name, False))

    return holidays


def infer_inset_days(events: list[CalendarEvent], holidays: list[CalendarEvent]) -> list[CalendarEvent]:
    """Detect INSET (teacher training) days from gaps before term starts (#18).

    INSET days are typically 1-3 weekdays immediately before a term-resume event
    that are not already covered by holidays or other events.
    """
    all_events = sorted(events + holidays, key=lambda e: e.start)
    covered_dates: set[datetime.date] = set()
    for ev in all_events:
        d = ev.start
        while d <= ev.end:
            covered_dates.add(d)
            d += datetime.timedelta(days=1)

    inset_events: list[CalendarEvent] = []
    for ev in sorted(events, key=lambda e: e.start):
        if not _is_term_resume_event(ev.summary):
            continue
        # Look backwards from term-resume date for uncovered weekdays
        inset_days: list[datetime.date] = []
        check_date = ev.start - datetime.timedelta(days=1)
        while check_date >= ev.start - datetime.timedelta(days=4):
            if check_date.weekday() < 5 and check_date not in covered_dates:
                inset_days.append(check_date)
            check_date -= datetime.timedelta(days=1)

        if 1 <= len(inset_days) <= 3:
            inset_days.sort()
            label = f"INSET Day{'s' if len(inset_days) > 1 else ''}"
            inset_events.append(CalendarEvent(
                inset_days[0],
                inset_days[-1],
                label,
                False,
            ))

    return inset_events


# ============================================================================
# Main Execution
# ============================================================================

def process_events(lines: list[str]) -> list[CalendarEvent]:
    """
    Process scraped lines into event tuples.

    Args:
        lines: Raw text lines from the website

    Returns:
        List of processed :class:`CalendarEvent` rows
    """
    events: list[CalendarEvent] = []

    for line in lines:
        for ev in parse_event_line(line):
            summary = _canonical_half_term_wording(ev.summary)
            start, end = _expand_half_term_to_week(
                ev.start,
                ev.end,
                summary,
                ev.suppress_half_term_week_expand,
            )
            summary = _normalize_half_term_summary(summary, start)
            events.append(CalendarEvent(start, end, summary, False))

    return events


def generate_ical(events: list[CalendarEvent]) -> str:
    """
    Generate iCalendar content from event tuples.

    Args:
        events: List of event tuples

    Returns:
        Complete iCalendar file content
    """
    event_strings: list[str] = []

    if CREATE_SCRAPED_EVENTS:
        for ev in events:
            event_strings.append(make_ics_event(ev.start, ev.end, ev.summary))

    if CREATE_HOLIDAY_EVENTS:
        holidays = infer_holidays(events)
        for hev in holidays:
            event_strings.append(make_ics_event(hev.start, hev.end, hev.summary))
        # INSET day detection (#18): find teacher training days before term starts
        for iev in infer_inset_days(events, holidays):
            event_strings.append(make_ics_event(iev.start, iev.end, iev.summary))

    ical = (
        ICAL_NEWLINE.join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                f"PRODID:{PRODID}",
                "CALSCALE:GREGORIAN",
                "METHOD:PUBLISH",
                f"X-WR-TIMEZONE:{CALENDAR_TIMEZONE}",
                "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
                "X-PUBLISHED-TTL:PT12H",
            ]
        )
        + ICAL_NEWLINE
        + "".join(event_strings)
        + f"END:VCALENDAR{ICAL_NEWLINE}"
    )

    return ical


# ============================================================================
# HTML Landing Page
# ============================================================================

def _html_escape(text: str) -> str:
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _build_year_overview(events: list) -> str:
    """Generate monthly calendar blocks with colour-coded days."""
    import calendar
    from collections import defaultdict
    # Build a map of date -> label/type
    day_map = {}
    for ev in events:
        label = ev.summary[:30]
        if "holiday" in ev.summary.lower() or "half term" in ev.summary.lower():
            etype = "holiday"
        elif "inset" in ev.summary.lower():
            etype = "inset"
        else:
            etype = "term"
        d = ev.start
        while d <= ev.end:
            day_map[d] = (label, etype)
            d += datetime.timedelta(days=1)
    # Group by month
    months = defaultdict(list)
    for d, (label, etype) in sorted(day_map.items()):
        months[(d.year, d.month)].append((d.day, etype))
    blocks = []
    for (year, month), days in sorted(months.items()):
        mon_name = calendar.month_name[month]
        day_markers = ""
        for day, etype in sorted(days, key=lambda x: x[0]):
            day_markers += f'<span class="ov-day ov-{etype}" title="{mon_name} {day}: {etype}">{day}</span>'
        blocks.append(f'<div class="ov-month"><div class="ov-month-name">{mon_name} {year}</div><div class="ov-days">{day_markers}</div></div>')
    return "\n".join(blocks)


def build_index_html(events: list) -> str:
    """Generate a stylish single-page HTML site promoting the calendar."""
    now = datetime.datetime.now().strftime("%d %B %Y at %H:%M")
    ics_url = f"{SITE_URL}/{OUTPUT_FILENAME}"
    webcal_url = ics_url.replace("https://", "webcal://")
    gcal_url = f"https://calendar.google.com/calendar/render?cid={ics_url.replace('https://', 'webcal://')}"

    # Sort events by date
    sorted_events = sorted(events, key=lambda e: e.start)
    today = datetime.date.today()
    upcoming = [e for e in sorted_events if e.end >= today]
    past = [e for e in sorted_events if e.end < today]

    def event_type_label(summary: str) -> str:
        s = summary.lower()
        if "holiday" in s or "half term" in s:
            return "holiday"
        if "inset" in s:
            return "inset"
        return "term"

    event_rows = ""
    for ev in upcoming[:30]:
        label = event_type_label(ev.summary)
        if ev.start == ev.end:
            date_str = ev.start.strftime("%d %b %Y")
        else:
            date_str = f"{ev.start.strftime('%d %b')} – {ev.end.strftime('%d %b %Y')}"
        event_rows += f"""
            <tr class="event-{label}">
                <td class="event-date">{date_str}</td>
                <td class="event-name">{_html_escape(ev.summary)}</td>
            </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Penrice Academy — Term Dates Calendar</title>
    <meta name="description" content="Subscribe to the Penrice Academy term dates and school holiday calendar. Never miss a term start, half term break, or INSET day.">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📅</text></svg>">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root{{--bg:#0a0a12;--surface:#12121e;--surface2:#1a1a2c;--border:rgba(139,157,181,0.18);--text:#e4e8f0;--muted:#8b9db5;--accent:#60a5fa;--accent-dim:rgba(96,165,250,0.12);--green:#4ade80;--amber:#fbbf24;--purple:#c084fc;--radius:14px;--radius-sm:8px}}
        [data-theme="light"]{{--bg:#f8fafc;--surface:#ffffff;--surface2:#f1f5f9;--border:rgba(100,116,139,0.15);--text:#1e293b;--muted:#64748b;--accent:#2563eb;--accent-dim:rgba(37,99,235,0.1);--green:#16a34a;--amber:#d97706;--purple:#9333ea}}
        *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
        body{{font-family:'Outfit',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;transition:background .2s,color .2s}}
        .container{{max-width:800px;margin:0 auto;padding:2rem 1.5rem 4rem}}
        .header{{text-align:center;padding:3rem 0 2.5rem}}
        .header h1{{font-size:2.2rem;font-weight:700;letter-spacing:-0.02em;margin-bottom:0.5rem}}
        .header .badge{{display:inline-block;font-size:0.8rem;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--accent);background:var(--accent-dim);padding:0.3rem 0.85rem;border-radius:100px;margin-bottom:1rem}}
        .header p{{color:var(--muted);font-size:1.05rem;max-width:500px;margin:0 auto}}
        .theme-toggle{{position:fixed;top:1rem;right:1rem;background:var(--surface);border:1px solid var(--border);color:var(--text);cursor:pointer;padding:0.45rem 0.8rem;border-radius:8px;font-size:0.85rem;transition:background .15s;z-index:10}}
        .theme-toggle:hover{{background:var(--surface2)}}

        .subscribe-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:2rem;margin-bottom:2rem;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.2)}}
        .subscribe-card h2{{font-size:1.3rem;margin-bottom:1.25rem}}
        .sub-buttons{{display:flex;flex-wrap:wrap;gap:0.75rem;justify-content:center;margin-bottom:1.5rem}}
        .sub-btn{{display:inline-flex;align-items:center;gap:0.5rem;padding:0.7rem 1.4rem;border-radius:100px;font-weight:600;font-size:0.9rem;text-decoration:none;transition:all .15s;border:1px solid var(--border);background:var(--surface2);color:var(--text)}}
        .sub-btn:hover{{transform:translateY(-1px);box-shadow:0 4px 12px rgba(0,0,0,.25);border-color:var(--accent)}}
        .sub-btn.primary{{background:var(--accent);color:#fff;border-color:var(--accent)}}
        .sub-btn.primary:hover{{background:var(--accent);opacity:0.9}}
        .sub-url{{font-family:'JetBrains Mono',monospace;font-size:0.82rem;color:var(--muted);word-break:break-all;background:var(--surface2);padding:0.6rem 1rem;border-radius:var(--radius-sm);margin-top:1rem}}

        .instructions{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1.25rem;margin-bottom:2.5rem}}
        .inst-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:1.5rem}}
        .inst-card h3{{font-size:1rem;margin-bottom:0.6rem;display:flex;align-items:center;gap:0.5rem}}
        .inst-card p,.inst-card ol{{font-size:0.88rem;color:var(--muted);line-height:1.7}}
        .inst-card ol{{padding-left:1.25rem}}
        .inst-card li{{margin-bottom:0.3rem}}

        .events-card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:1.5rem;margin-bottom:2rem}}
        .events-card h2{{font-size:1.2rem;margin-bottom:1rem}}
        table{{width:100%;border-collapse:collapse;font-size:0.9rem}}
        th{{text-align:left;padding:0.5rem 0.75rem;color:var(--muted);font-weight:500;font-size:0.8rem;text-transform:uppercase;letter-spacing:0.04em;border-bottom:1px solid var(--border)}}
        td{{padding:0.55rem 0.75rem;border-bottom:1px solid var(--border)}}
        .event-date{{font-family:'JetBrains Mono',monospace;font-size:0.82rem;white-space:nowrap;color:var(--muted)}}
        .event-holiday .event-name{{color:var(--amber)}}
        .event-inset .event-name{{color:var(--purple)}}
        .event-term .event-name{{color:var(--green)}}
        tr:hover{{background:rgba(96,165,250,0.04)}}

        .ov-month{{background:var(--surface2);border-radius:var(--radius-sm);padding:0.75rem 1rem;border:1px solid var(--border)}}
        .ov-month-name{{font-size:0.82rem;font-weight:600;margin-bottom:0.5rem;color:var(--text)}}
        .ov-days{{display:flex;flex-wrap:wrap;gap:3px}}
        .ov-day{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:4px;font-size:0.65rem;font-family:'JetBrains Mono',monospace;cursor:default}}
        .ov-term{{background:rgba(74,222,128,0.2);color:var(--green)}}
        .ov-holiday{{background:rgba(251,191,36,0.2);color:var(--amber)}}
        .ov-inset{{background:rgba(192,132,252,0.2);color:var(--purple)}}
        footer{{text-align:center;padding:2rem 0;color:var(--muted);font-size:0.85rem;border-top:1px solid var(--border);margin-top:2rem}}
        footer a{{color:var(--accent)}}
        @media(max-width:600px){{.header h1{{font-size:1.6rem}}.container{{padding:1rem}}.sub-buttons{{flex-direction:column}}.sub-btn{{justify-content:center}}}}
    </style>
</head>
<body>
    <button class="theme-toggle" onclick="toggleTheme()" aria-label="Toggle theme">☀️ 🌙</button>
    <div class="container">
        <div class="header">
            <div class="badge">Cornwall · Education</div>
            <h1>Penrice Academy<br>Term Dates</h1>
            <p>Subscribe to stay in sync with school terms, holidays, half term breaks, and INSET days. Updates automatically when the school publishes new dates.</p>
        </div>

        <div class="subscribe-card">
            <h2>📅 Subscribe to the Calendar</h2>
            <div class="sub-buttons">
                <a href="{webcal_url}" class="sub-btn primary">📱 Add to Apple / iOS</a>
                <a href="{gcal_url}" class="sub-btn" target="_blank" rel="noopener">🔗 Add to Google Calendar</a>
                <a href="{OUTPUT_FILENAME}" class="sub-btn" download>💾 Download .ics File</a>
            </div>
            <div class="sub-url">{ics_url}</div>
        </div>

        <div class="instructions">
            <div class="inst-card">
                <h3>📱 iPhone / iPad</h3>
                <ol><li>Tap the <strong>Add to Apple / iOS</strong> button above</li><li>Tap <strong>Subscribe</strong> when prompted</li><li>The calendar appears in your Calendar app</li></ol>
            </div>
            <div class="inst-card">
                <h3>🔗 Google Calendar</h3>
                <ol><li>Tap <strong>Add to Google Calendar</strong> above</li><li>Sign in if needed</li><li>Confirm to add the calendar</li></ol>
            </div>
            <div class="inst-card">
                <h3>💻 Outlook / Desktop</h3>
                <ol><li>Click <strong>Download .ics File</strong> above</li><li>Open the downloaded file</li><li>Your calendar app will import it</li></ol>
            </div>
            <div class="inst-card">
                <h3>🔄 Auto-Updates</h3>
                <p>This calendar checks for new term dates every 24 hours. If you subscribe via the Apple or Google links above, your calendar updates automatically — no need to re-download.</p>
            </div>
        </div>

        <div class="events-card">
            <h2>📋 Upcoming Dates</h2>
            <table>
                <thead><tr><th>Date</th><th>Event</th></tr></thead>
                <tbody>{event_rows if event_rows else '<tr><td colspan="2" style="color:var(--muted)">No upcoming dates found. Check back when the school publishes the new academic year.</td></tr>'}</tbody>
            </table>
        </div>

        <div class="events-card">
            <h2>📅 Academic Year Overview</h2>
            <p style="color:var(--muted);margin-bottom:1rem;font-size:0.9rem">Colour-coded view of the school year. <span style="color:var(--green)">■ Terms</span> · <span style="color:var(--amber)">■ Holidays</span> · <span style="color:var(--purple)">■ INSET Days</span></p>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:0.75rem">
                {_build_year_overview(sorted_events)}
            </div>
        </div>

        <footer>
            <p>Penrice Academy Term Dates Calendar · Updated {now}</p>
            <p style="margin-top:0.5rem">An open-source fan-made project. <a href="https://github.com/evenwebb/penrice-calendar-scraper">Source on GitHub</a></p>
        </footer>
    </div>
    <script>
    (function(){{var t=localStorage.getItem('penrice-theme')||(window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');document.documentElement.setAttribute('data-theme',t)}})();
    function toggleTheme(){{var c=document.documentElement.getAttribute('data-theme');var n=c==='dark'?'light':'dark';document.documentElement.setAttribute('data-theme',n);localStorage.setItem('penrice-theme',n)}}
    </script>
</body>
</html>"""


def main() -> None:
    """Main entry point for the calendar scraper.

    Fetches term dates, parses events, and generates an iCalendar file and HTML landing page.
    """
    try:
        lines = extract_lines()
        if not lines:
            logger.error("No lines extracted from website")
            print("Error: No term dates found on website. Check log.txt for details.")
            return

        events = process_events(lines)
        if not events:
            logger.error("No events parsed from extracted lines")
            print("Error: No events parsed. Check log.txt for details.")
            return

        ical_content = generate_ical(events)

        # Ensure output directory exists
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        ics_path = os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)
        with open(ics_path, "w", encoding="utf-8") as f:
            f.write(ical_content)
        print(f"Created {ics_path} with term dates events.")

        # Generate HTML landing page
        html = build_index_html(events)
        html_path = os.path.join(OUTPUT_DIR, "index.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Created {html_path}")

    except requests.RequestException as e:
        logger.error("Failed to fetch term dates: %s", e)
        print(f"Error: Failed to fetch term dates. Check log.txt for details.")
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        print(f"Error: An unexpected error occurred. Check log.txt for details.")


if __name__ == "__main__":
    main()
