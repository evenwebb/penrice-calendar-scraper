# Penrice Academy Calendar Scraper

This repository provides small Python scripts that fetch event dates from web pages and build iCalendar (`.ics`) files. The calendars can be imported into any application that supports the iCalendar format.

## Requirements

- Python 3
- `requests`
- `beautifulsoup4`

Install the dependencies using `pip`:

```bash
pip install -r requirements.txt
```

## Usage

### Penrice Academy Term Dates

Run the script to download the term dates from the Penrice Academy website and generate `penrice.ics`:

```bash
python generate_ics.py
```


## How it works

Each script downloads the relevant web page, parses the event information using **BeautifulSoup** and writes one calendar entry per event using standard iCalendar syntax.

Example calendar files (`penrice.ics`) are included for reference.
