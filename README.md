<div align="center">

# 🏫 Penrice Academy Calendar Scraper

Automatically fetches term dates from Penrice Academy and generates an iCalendar (`.ics`) feed you can subscribe to in Apple Calendar, Google Calendar, Outlook, and other calendar apps.

</div>

---

## 📚 Table of Contents

- [⚡ Quick Start](#-quick-start)
- [✨ Features](#-features)
- [📦 Installation](#-installation)
- [🚀 Usage](#-usage)
- [⚙️ Configuration](#️-configuration)
- [🤖 GitHub Actions Automation](#-github-actions-automation)
- [📲 Subscribe in Calendar Apps](#-subscribe-in-calendar-apps)
- [🧩 Dependencies](#-dependencies)
- [🛠️ Troubleshooting](#️-troubleshooting)
- [⚠️ Known Limitations](#️-known-limitations)
- [📄 License](#-license)

---

## ⚡ Quick Start

```bash
git clone https://github.com/evenwebb/penrice-calendar-scraper.git
cd penrice-calendar-scraper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 generate_ics.py
```

✅ Output file: `penrice.ics`

---

## ✨ Features

| Feature | Description |
|---|---|
| `🏫 Live Term-Date Scraping` | Pulls current term-date information directly from the Penrice Academy website. |
| `🧠 Robust Date Parsing` | Handles single dates, date ranges, and multi-date lines in the published content. |
| `🏖️ Holiday Inference` | Optionally infers and adds holiday periods between term boundaries. |
| `📅 Stable iCalendar Output` | Generates RFC 5545 `.ics` with deterministic UIDs and proper line folding. |
| `🧪 Resilient Fetching` | Uses request retry/backoff to reduce transient network failures. |
| `🤖 Automated Updates` | Daily GitHub Actions workflow updates output and can open failure issues. |

---

## 📦 Installation

```bash
git clone https://github.com/evenwebb/penrice-calendar-scraper.git
cd penrice-calendar-scraper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 🚀 Usage

```bash
python3 generate_ics.py
```

The script fetches term dates and writes `penrice.ics` to the repository root.

---

## ⚙️ Configuration

Settings are defined near the top of `generate_ics.py`.

| Option | Default | Description |
|---|---|---|
| `URL` | `https://www.penriceacademy.org/page/?title=Term+Dates&pid=49` | Source page for term dates. |
| `CREATE_SCRAPED_EVENTS` | `True` | Include events parsed directly from the website. |
| `CREATE_HOLIDAY_EVENTS` | `True` | Include inferred holiday breaks between terms. |
| `TITLECASE_WORDS` | `term, holiday, half, INSET` | Words normalized to title case in event summaries. |
| `DEFAULT_RETRIES` | `3` | HTTP retry attempts for page fetch. |
| `DEFAULT_TIMEOUT` | `60` | HTTP timeout in seconds. |
| `INITIAL_RETRY_DELAY` | `1` | Initial retry backoff delay in seconds. |
| `OUTPUT_FILENAME` | `penrice.ics` | Output calendar file path/name. |
| `LOG_FILENAME` | `log.txt` | Log file for scraper errors and warnings. |
| `CALENDAR_PREFIX` | `Penrice` | Prefix for generated event titles. |
| `CALENDAR_TIMEZONE` | `Europe/London` | Timezone used in calendar metadata. |

---

## 🤖 GitHub Actions Automation

This repo includes `.github/workflows/scrape.yml`:

- `⏰` Runs daily at `11:00 UTC`
- `🖱️` Supports manual runs (`workflow_dispatch`)
- `🔁` Retries scraper runs before failing (`SCRAPER_RUN_ATTEMPTS`, default `2`)
- `📝` Commits `penrice.ics` only when output changes
- `🚨` Optionally opens or updates a GitHub issue on failure (`CREATE_FAILURE_ISSUE=true`)

Configure these repository secrets if needed:

- `CREATE_FAILURE_ISSUE` (`true`/`false`)
- `SCRAPER_RUN_ATTEMPTS` (integer)

---

## 📲 Subscribe in Calendar Apps

Use the raw GitHub `.ics` URL as a subscription URL:

`https://raw.githubusercontent.com/<github-user>/penrice-calendar-scraper/<branch>/penrice.ics`

### 🗓️ Google Calendar

1. Open Google Calendar on web.
2. Click **+** next to **Other calendars**.
3. Select **From URL**.
4. Paste the raw `.ics` URL.

### 🍎 iPhone / iPad

1. Open **Settings**.
2. Go to **Calendar** -> **Accounts** -> **Add Account** -> **Other**.
3. Tap **Add Subscribed Calendar**.
4. Paste the raw `.ics` URL.

### 🤖 Android

1. Add the subscription in Google Calendar web using **From URL**.
2. Ensure that calendar is enabled in your Android calendar app sync settings.

---

## 🧩 Dependencies

| Package | Purpose |
|---|---|
| `requests` | HTTP requests to source pages |
| `beautifulsoup4` | HTML parsing and extraction |

---

## 🛠️ Troubleshooting

- `🧱` If no events are generated, verify the source site structure has not changed.
- `📜` Check `log.txt` for parsing errors.
- `🔁` If workflow runs fail intermittently, increase `SCRAPER_RUN_ATTEMPTS`.

---

## ⚠️ Known Limitations

- `🌐` Parsing depends on Penrice website content structure and wording.
- `📆` Inferred holiday events may miss exceptional one-off academic changes.

---

## 📄 License

[GPL-3.0](LICENSE)
