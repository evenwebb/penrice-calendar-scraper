# Parish Council Calendar

This repository contains a Python script that scrapes upcoming meeting dates from the St Mewan Parish Council website and builds an iCalendar (`.ics`) file. The generated calendar can be imported into any calendar application that supports the iCalendar format.

## Requirements

- Python 3
- `requests`
- `beautifulsoup4`

Install the dependencies using `pip`:

```bash
pip install -r requirements.txt
```

## Usage

Run the script to fetch the meeting information and generate `stmewan.ics`:

```bash
python generate_ics.py
```

The script downloads the meeting pages, extracts upcoming dates and associated links (agenda and minutes when available) and writes them into `stmewan.ics`.

## How it works

The `generate_ics.py` script contains a list of meeting pages under `MEETING_TYPES`.
For each page it:

1. Fetches the HTML with `requests`.
2. Parses upcoming meeting entries using **BeautifulSoup**.
3. Converts the textual dates and times into Python `datetime` objects.
4. Creates an iCalendar event for each meeting, appending any agenda or minutes
   links to the event description.
5. Writes all events to `stmewan.ics` in standard iCalendar format.

## Calendar file

An example `stmewan.ics` is included in this repository. After running the script you can import the file into your preferred calendar application to view upcoming Parish Council meetings.

