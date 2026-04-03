"""
Penrice Academy Calendar Scraper

This script scrapes term dates from the Penrice Academy website and generates
an iCalendar (.ics) file that can be imported into calendar applications.
"""

import datetime
import hashlib
import logging
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
OUTPUT_FILENAME = "penrice.ics"
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
    summary = re.sub(r"\s*Begins at 3:00pm\.?$", "", summary, flags=re.IGNORECASE)
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
    s = summary.lower()
    return any(phrase in s for phrase in END_OF_TERM_PHRASES)


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
        for hev in infer_holidays(events):
            event_strings.append(make_ics_event(hev.start, hev.end, hev.summary))

    ical = (
        ICAL_NEWLINE.join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                f"PRODID:{PRODID}",
                "CALSCALE:GREGORIAN",
                "METHOD:PUBLISH",
                f"X-WR-TIMEZONE:{CALENDAR_TIMEZONE}",
            ]
        )
        + ICAL_NEWLINE
        + "".join(event_strings)
        + f"END:VCALENDAR{ICAL_NEWLINE}"
    )

    return ical


def main() -> None:
    """
    Main entry point for the calendar scraper.

    Fetches term dates, parses events, and generates an iCalendar file.
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

        with open(OUTPUT_FILENAME, "w", encoding="utf-8") as f:
            f.write(ical_content)

        print(f"Created {OUTPUT_FILENAME} with term dates events.")

    except requests.RequestException as e:
        logger.error("Failed to fetch term dates: %s", e)
        print(f"Error: Failed to fetch term dates. Check log.txt for details.")
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        print(f"Error: An unexpected error occurred. Check log.txt for details.")


if __name__ == "__main__":
    main()
