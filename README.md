# Penrice Academy Calendar Scraper

This project provides a small Python script that collects the term dates from the Penrice Academy website and produces a ready‑to‑import iCalendar file.  The resulting `penrice.ics` file can be opened in any calendar application such as Google Calendar, Outlook or Apple Calendar.

## Features

* Downloads the latest term dates from <https://www.penriceacademy.org/term-dates>.
* Parses single dates and date ranges using BeautifulSoup and regular expressions.
* Generates standards‑compliant calendar events for each entry.
* Saves the events to `penrice.ics`.

## Requirements

* Python 3
* `requests`
* `beautifulsoup4`

Install the dependencies with:

```bash
pip install -r requirements.txt
```

## Usage

Run the script from the repository root:

```bash
python generate_ics.py
```

The script prints a confirmation message and writes the calendar file.  A portion of the generated output resembles the following:

```text
BEGIN:VEVENT
DTSTART;VALUE=DATE:20240902
DTEND;VALUE=DATE:20240905
SUMMARY:Penrice Staff Inset Days (Students not required to attend)
END:VEVENT
```

## Customisation

All scraping logic lives in `generate_ics.py`.  To adapt this tool for another website, modify the `URL` constant and adjust the `extract_lines` and `parse_event_line` helpers to suit the new page structure.  Each parsed entry is converted into an iCalendar event by `make_ics_event`.

An example `penrice.ics` is included for reference.
