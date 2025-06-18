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

# Toggle generation of scraped events (directly parsed from the website).
CREATE_SCRAPED_EVENTS = True
# Toggle generation of inferred holiday breaks between term dates.
CREATE_HOLIDAY_EVENTS = True

# Comma separated words that should be Title Cased in event summaries.
TITLECASE_WORDS = [w.strip() for w in "term,holiday,half,INSET".split(",")]

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
    # Remove any trailing "Begins at 3:00pm" text which occasionally appears
    # on the Penrice website to indicate an early finish before a break.
    summary = re.sub(r"\s*Begins at 3:00pm\.?$", "", summary, flags=re.IGNORECASE)

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


def _apply_titlecase(summary: str) -> str:
    """Return summary with configured words converted to Title Case."""
    if not TITLECASE_WORDS:
        return summary
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, TITLECASE_WORDS)) + r")\b", re.IGNORECASE)
    return pattern.sub(lambda m: m.group(0).title(), summary)


def make_ics_event(start: datetime.date, end: datetime.date, summary: str) -> str:
    """Return an iCalendar VEVENT string with a prefixed summary."""

    summary = _apply_titlecase(summary)

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


def guess_holiday_name(start: datetime.date, end: datetime.date) -> str:
    """Return a holiday name based on the month of the break."""
    if start.month in {12, 1}:
        return "Christmas Holidays"
    if start.month == 2:
        return "Spring Half Term"
    if start.month in {3, 4}:
        return "Easter Holiday"
    if start.month in {5, 6}:
        return "Summer Half Term"
    if start.month in {7, 8}:
        return "Summer Holidays"
    if start.month in {10, 11}:
        return "Autumn Half Term"
    return "Holiday"


def infer_holidays(events: list[tuple[datetime.date, datetime.date, str]]) -> list[tuple[datetime.date, datetime.date, str]]:
    """Infer holiday periods from End of Term and Term Begins events."""
    sorted_events = sorted(events, key=lambda e: e[0])
    holidays: list[tuple[datetime.date, datetime.date, str]] = []
    for i, (start_d, end_d, summary) in enumerate(sorted_events):
        if "End of Term" not in summary:
            continue
        next_start = None
        for j in range(i + 1, len(sorted_events)):
            ns, _, ns_summary = sorted_events[j]
            if "Term Begins" in ns_summary:
                next_start = ns
                break
        if next_start:
            hol_start = end_d + datetime.timedelta(days=1)
            hol_end = next_start - datetime.timedelta(days=1)
            if hol_start <= hol_end:
                name = guess_holiday_name(hol_start, hol_end)
                holidays.append((hol_start, hol_end, name))
    return holidays


def main() -> None:
    lines = extract_lines()
    events: list[str] = []
    parsed: list[tuple[datetime.date, datetime.date, str]] = []
    for line in lines:
        for start, end, summary in parse_event_line(line):
            if (
                "Half Term" in summary
                and start == end
                and "Begins at 3:00pm" not in line
            ):
                week_start = start - datetime.timedelta(days=start.weekday())
                end = week_start + datetime.timedelta(days=4)
                start = week_start
            if "Half Term" in summary:
                if start.month == 2:
                    summary = summary.replace("Half Term", "Spring Half Term")
                elif start.month in {5, 6}:
                    summary = summary.replace("Half Term", "Summer Half Term")
                elif start.month in {10, 11}:
                    summary = summary.replace("Half Term", "Autumn Half Term")
            parsed.append((start, end, summary))
            if CREATE_SCRAPED_EVENTS:
                events.append(make_ics_event(start, end, summary))

    if CREATE_HOLIDAY_EVENTS:
        for hstart, hend, hname in infer_holidays(parsed):
            events.append(make_ics_event(hstart, hend, hname))

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
