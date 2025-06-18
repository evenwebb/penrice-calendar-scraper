# Penrice Academy Calendar Scraper

This repository contains a small Python script that scrapes the term dates published on the [Penrice Academy website](https://www.penriceacademy.org/term-dates) and converts them into a ready‑to‑import iCalendar (``.ics``) file.

Running the scraper generates ``penrice.ics`` which can be added to Google Calendar, Outlook, Apple Calendar or any other iCalendar compatible application.

## Features

* Fetches the latest term dates directly from the academy site using ``requests``.
* Parses individual dates and date ranges with BeautifulSoup and regular expressions.
* Automatically prefixes every event title with ``Penrice`` so it is clear where the information came from.
* Supports multiple events per line (e.g. ``1st Jan & 2nd Jan``).
* Writes a standards compliant ``.ics`` file and logs any parsing errors to ``log.txt``.

## Requirements

* Python 3.10 or newer
* ``requests``
* ``beautifulsoup4``

Install the dependencies with:

```bash
pip install -r requirements.txt
```

## Usage

From the repository root run:

```bash
python generate_ics.py
```

The script will download the term dates, create ``penrice.ics`` in the current directory and print a simple confirmation message.  Any parse errors are recorded in ``log.txt`` for inspection.

A typical entry in the generated calendar looks like:

```text
BEGIN:VEVENT
DTSTART;VALUE=DATE:20240902
DTEND;VALUE=DATE:20240905
SUMMARY:Penrice Staff Inset Days (Students not required to attend)
END:VEVENT
```

## Customisation

If the academy website changes or you would like to adapt the scraper for a different school, edit ``generate_ics.py``:

1. Update the ``URL`` constant to point at the new term dates page.
2. Adjust ``extract_lines`` and ``parse_event_line`` to match the structure of the new content.
3. Optionally tweak ``make_ics_event`` to alter how events are formatted.
4. Set ``CREATE_SCRAPED_EVENTS`` or ``CREATE_HOLIDAY_EVENTS`` to ``False`` if you
   only want one type of event written to the calendar.
5. Edit ``TITLECASE_WORDS`` to include any words that should always appear in
   Title Case within event summaries.

An example ``penrice.ics`` generated from the current site is included for reference.

