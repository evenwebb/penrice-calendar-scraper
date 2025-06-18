import re
import datetime
import logging

import requests
from bs4 import BeautifulSoup


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
error_handler = logging.FileHandler("log.txt")
error_handler.setLevel(logging.ERROR)
logger.addHandler(error_handler)

URL = "https://www.penriceacademy.org/term-dates"

DATE_RE = re.compile(r"(?P<day>\d{1,2})(?:st|nd|rd|th)? (?P<month>[A-Za-z]+) (?P<year>\d{4})")


def parse_date(text: str) -> datetime.date | None:
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


def extract_lines() -> list[str]:
    response = requests.get(URL, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    content = soup.select_one("section.user-content")
    lines: list[str] = []
    if not content:
        return lines
    for p in content.find_all("p"):
        text = p.get_text("\n")
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            lower_line = line.lower()
            if any(word in lower_line for word in ("privacy", "cookies", "updated")):
                continue
            lines.append(line)
    return lines


def parse_event_line(line: str) -> list[tuple[datetime.date, datetime.date, str]]:
    """Return a list of (start, end, summary) tuples parsed from a line."""
    matches = list(DATE_RE.finditer(line))
    if not matches:
        return []

    summary = line[matches[-1].end():].strip(" -\u2013")

    events: list[tuple[datetime.date, datetime.date, str]] = []
    if len(matches) == 1:
        d = parse_date(matches[0].group(0))
        if not d:
            logger.error("Could not parse date from line: %s", line)
            return []
        events.append((d, d, summary))
    elif " & " in line and len(matches) == 2:
        for m in matches:
            d = parse_date(m.group(0))
            if not d:
                logger.error("Could not parse date from line: %s", line)
                return []
            events.append((d, d, summary))
    else:
        start_date = parse_date(matches[0].group(0))
        end_date = parse_date(matches[1].group(0))
        if not start_date or not end_date:
            logger.error("Could not parse date range from line: %s", line)
            return []
        events.append((start_date, end_date, summary))

    return events


def make_ics_event(start: datetime.date, end: datetime.date, summary: str) -> str:
    """Return an iCalendar VEVENT string with a prefixed summary."""

    # All summaries should clearly indicate the source of the event.  Prefix
    # each event title with "Penrice" before writing it to the calendar file.
    prefixed_summary = f"Penrice {summary}".strip()

    dtend = end + datetime.timedelta(days=1)
    return (
        "BEGIN:VEVENT\n"
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}\n"
        f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}\n"
        f"SUMMARY:{prefixed_summary}\n"
        "END:VEVENT\n"
    )


def main() -> None:
    lines = extract_lines()
    events: list[str] = []
    for line in lines:
        for start, end, summary in parse_event_line(line):
            events.append(make_ics_event(start, end, summary))

    ical = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//Penrice Academy//EN\n"
        "CALSCALE:GREGORIAN\n"
        + "".join(events)
        + "END:VCALENDAR\n"
    )

    with open("penrice.ics", "w", encoding="utf-8") as f:
        f.write(ical)

    print("Created penrice.ics with term dates events.")


if __name__ == "__main__":
    main()
