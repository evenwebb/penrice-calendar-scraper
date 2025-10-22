"""
Penrice Academy Calendar Scraper

This script scrapes term dates from the Penrice Academy website and generates
an iCalendar (.ics) file that can be imported into calendar applications.
"""

import datetime
import logging
import re
import time
from typing import Optional

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
DEFAULT_TIMEOUT = 60
INITIAL_RETRY_DELAY = 1

# iCalendar configuration
CALENDAR_PREFIX = "Penrice"
PRODID = "-//Penrice Academy//EN"
OUTPUT_FILENAME = "penrice.ics"
LOG_FILENAME = "log.txt"

# Half term duration in days (Monday to Friday)
HALF_TERM_WEEKDAYS = 5

# Month mappings for holiday naming
CHRISTMAS_MONTHS = {12, 1}
SPRING_HALF_TERM_MONTH = 2
EASTER_MONTHS = {3, 4}
SUMMER_HALF_TERM_MONTHS = {5, 6}
SUMMER_HOLIDAY_MONTHS = {7, 8}
AUTUMN_HALF_TERM_MONTHS = {10, 11}


# ============================================================================
# Logging Setup
# ============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
error_handler = logging.FileHandler(LOG_FILENAME, mode='a', encoding='utf-8')
error_handler.setLevel(logging.ERROR)
logger.addHandler(error_handler)


# ============================================================================
# Type Aliases
# ============================================================================

EventTuple = tuple[datetime.date, datetime.date, str]


# ============================================================================
# Regular Expressions
# ============================================================================

DATE_RE = re.compile(
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})"
)
MONTH_NAMES = [datetime.date(2000, m, 1).strftime("%B").lower() for m in range(1, 13)]


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
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=timeout)
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

    try:
        month = datetime.datetime.strptime(month_str, "%B").month
    except ValueError:
        logger.error("Unrecognised month '%s' in line: %s", month_str, text)
        return None

    year = int(match.group("year"))

    try:
        return datetime.date(year, month, day)
    except ValueError:
        logger.error("Invalid date detected in line: %s", text)
        return None


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


def extract_lines() -> list[str]:
    """
    Scrape and extract term date lines from the Penrice Academy website.

    Returns:
        List of text lines containing term date information

    Raises:
        requests.RequestException: If fetching the URL fails
    """
    response = fetch_with_retries(URL)
    soup = BeautifulSoup(response.text, "html.parser")

    # Try multiple selectors to find the content section
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
    # Remove trailing "Begins at 3:00pm" text that indicates early finish
    summary = re.sub(r"\s*Begins at 3:00pm\.?$", "", summary, flags=re.IGNORECASE)
    return summary


def _parse_single_date_event(
    line: str,
    match: re.Match[str]
) -> list[EventTuple]:
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

    if "-" in pre and not any(month in left_part.lower() for month in MONTH_NAMES):
        day_match = re.search(r"(\d{1,2})(?:st|nd|rd|th)?", left_part)
        if day_match:
            start_day = int(day_match.group(1))
            start_date = datetime.date(end_date.year, end_date.month, start_day)
            summary = _clean_event_summary(line[match.end():])
            return [(start_date, end_date, summary)]

    summary = _clean_event_summary(line[match.end():])
    return [(end_date, end_date, summary)]


def _parse_multiple_single_dates(
    line: str,
    matches: list[re.Match[str]]
) -> list[EventTuple]:
    """
    Parse events with multiple individual dates (e.g., "1st Jan & 2nd Jan").

    Args:
        line: The line containing the events
        matches: List of regex matches for dates

    Returns:
        List of (start_date, end_date, summary) tuples
    """
    summary = _clean_event_summary(line[matches[-1].end():])
    events: list[EventTuple] = []

    for match in matches:
        date = parse_date(match.group(0))
        if not date:
            logger.error("Could not parse date from line: %s", line)
            return []
        events.append((date, date, summary))

    return events


def _parse_date_range_event(
    line: str,
    matches: list[re.Match[str]]
) -> list[EventTuple]:
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

    summary = _clean_event_summary(line[matches[-1].end():])
    return [(start_date, end_date, summary)]


def parse_event_line(line: str) -> list[EventTuple]:
    """
    Parse event information from a single line of text.

    Handles various date formats:
    - Single date: "5th January 2024 Term Begins"
    - Date range: "3rd - 5th January 2024 INSET Days"
    - Multiple dates: "1st January 2024 & 2nd January 2024 INSET Days"

    Args:
        line: Text line containing event information

    Returns:
        List of (start_date, end_date, summary) tuples
    """
    matches = list(DATE_RE.finditer(line))
    if not matches:
        return []

    if len(matches) == 1:
        return _parse_single_date_event(line, matches[0])
    elif " & " in line and len(matches) == 2:
        return _parse_multiple_single_dates(line, matches)
    else:
        return _parse_date_range_event(line, matches)


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
    line: str
) -> tuple[datetime.date, datetime.date]:
    """
    Expand single-day half term events to full week.

    Args:
        start_date: Original start date
        end_date: Original end date
        summary: Event summary
        line: Original line text

    Returns:
        Tuple of (expanded_start, expanded_end)
    """
    # Only expand if it's a single-day half term without "Begins at 3:00pm"
    if "Half Term" in summary and start_date == end_date and "Begins at 3:00pm" not in line:
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
    if not TITLECASE_WORDS:
        return summary

    pattern = re.compile(
        r"\b(" + "|".join(map(re.escape, TITLECASE_WORDS)) + r")\b",
        re.IGNORECASE
    )
    return pattern.sub(lambda m: m.group(0).title(), summary)


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

    return (
        "BEGIN:VEVENT\n"
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}\n"
        f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}\n"
        f"SUMMARY:{prefixed_summary}\n"
        "END:VEVENT\n"
    )


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


def infer_holidays(events: list[EventTuple]) -> list[EventTuple]:
    """
    Infer holiday periods from End of Term and Term Begins events.

    Args:
        events: List of (start_date, end_date, summary) tuples

    Returns:
        List of inferred holiday events
    """
    sorted_events = sorted(events, key=lambda e: e[0])
    holidays: list[EventTuple] = []

    for i, (start_date, end_date, summary) in enumerate(sorted_events):
        if "End of Term" not in summary:
            continue

        # Find the next "Term Begins" event
        next_start = None
        for j in range(i + 1, len(sorted_events)):
            ns, _, ns_summary = sorted_events[j]
            if "Term Begins" in ns_summary:
                next_start = ns
                break

        if next_start:
            # Holiday starts the day after term ends
            hol_start = end_date + datetime.timedelta(days=1)
            # Holiday ends the day before term begins
            hol_end = next_start - datetime.timedelta(days=1)

            if hol_start <= hol_end:
                name = guess_holiday_name(hol_start, hol_end)
                holidays.append((hol_start, hol_end, name))

    return holidays


# ============================================================================
# Main Execution
# ============================================================================

def process_events(lines: list[str]) -> list[EventTuple]:
    """
    Process scraped lines into event tuples.

    Args:
        lines: Raw text lines from the website

    Returns:
        List of processed event tuples
    """
    events: list[EventTuple] = []

    for line in lines:
        for start, end, summary in parse_event_line(line):
            # Expand single-day half terms to full week
            start, end = _expand_half_term_to_week(start, end, summary, line)

            # Normalize half term names with specific seasons
            summary = _normalize_half_term_summary(summary, start)

            events.append((start, end, summary))

    return events


def generate_ical(events: list[EventTuple]) -> str:
    """
    Generate iCalendar content from event tuples.

    Args:
        events: List of event tuples

    Returns:
        Complete iCalendar file content
    """
    event_strings: list[str] = []

    if CREATE_SCRAPED_EVENTS:
        for start, end, summary in events:
            event_strings.append(make_ics_event(start, end, summary))

    if CREATE_HOLIDAY_EVENTS:
        for hstart, hend, hname in infer_holidays(events):
            event_strings.append(make_ics_event(hstart, hend, hname))

    ical = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        f"PRODID:{PRODID}\n"
        "CALSCALE:GREGORIAN\n"
        + "".join(event_strings)
        + "END:VCALENDAR\n"
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
