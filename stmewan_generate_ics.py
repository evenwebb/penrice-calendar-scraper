import re
import datetime
import requests
from bs4 import BeautifulSoup

MEETING_TYPES = [
    {
        "name": "Full Council",
        "url": "https://www.stmewanparishcouncil.gov.uk/Full_Council_24620.aspx",
        "base_url": "https://www.stmewanparishcouncil.gov.uk"
    },
    {
        "name": "Planning",
        "url": "https://www.stmewanparishcouncil.gov.uk/Planning_24621.aspx",
        "base_url": "https://www.stmewanparishcouncil.gov.uk"
    },
    {
        "name": "Extra Ordinary Council",
        "url": "https://www.stmewanparishcouncil.gov.uk/Extra_Ordinary_Council_Meeting_30589.aspx",
        "base_url": "https://www.stmewanparishcouncil.gov.uk"
    },
    {
        "name": "Finance, Staffing, General Purposes & Audit",
        "url": "https://www.stmewanparishcouncil.gov.uk/Finance_Staffing_General_Purposes__and__Audit_24623.aspx",
        "base_url": "https://www.stmewanparishcouncil.gov.uk"
    },
    {
        "name": "Playing Fields",
        "url": "https://www.stmewanparishcouncil.gov.uk/Playing_Fields_24624.aspx",
        "base_url": "https://www.stmewanparishcouncil.gov.uk"
    },
    {
        "name": "Rights of Way",
        "url": "https://www.stmewanparishcouncil.gov.uk/Rights_of_Way_24622.aspx",
        "base_url": "https://www.stmewanparishcouncil.gov.uk"
    }
]

def parse_event_date(date_str):
    # Example: '8 Jan 25' → 2025-01-08
    match = re.match(r'(\d{1,2}) (\w{3}) (\d{2})', date_str)
    if not match:
        return None
    day, month, year = match.groups()
    month_number = datetime.datetime.strptime(month, "%b").month
    year_full = 2000 + int(year)
    return datetime.date(year_full, month_number, int(day))

def parse_time_range(time_str):
    # Example: '19:00 to 21:00' → (19:00, 21:00), or '18:00' → (18:00, None)
    match = re.match(r'(\d{1,2}:\d{2}) to (\d{1,2}:\d{2})', time_str)
    if match:
        return match.group(1), match.group(2)
    match = re.match(r'(\d{1,2}:\d{2})', time_str)
    if match:
        return match.group(1), None
    return None, None

def make_ics_event(dtstart, dtend, summary, description=""):
    return (
        "BEGIN:VEVENT\n"
        f"DTSTART;TZID=Europe/London:{dtstart.strftime('%Y%m%dT%H%M%S')}\n"
        f"DTEND;TZID=Europe/London:{dtend.strftime('%Y%m%dT%H%M%S')}\n"
        f"SUMMARY:{summary}\n"
        f"DESCRIPTION:{description}\n"
        "END:VEVENT\n"
    )

def extract_events_from_html(html, meeting_type, base_url):
    soup = BeautifulSoup(html, "html.parser")
    today = datetime.date.today()
    ics_events = []

    for minutes_div in soup.find_all("div", class_="minutes"):
        h4 = minutes_div.find("h4")
        if not h4: continue
        date_str = h4.get_text(strip=True)
        event_date = parse_event_date(date_str)
        if not event_date or event_date < today:
            continue

        p_tags = minutes_div.find_all("p")
        if len(p_tags) == 0:
            continue
        time_str = p_tags[0].get_text(strip=True)
        start_time_str, end_time_str = parse_time_range(time_str)
        if not start_time_str:
            continue

        summary = f"St Mewan Parish - {meeting_type} Meeting"

        description = ""
        for a in minutes_div.find_all("a"):
            link_text = a.get_text()
            link_url = a.get("href")
            if not link_url: continue
            if not link_url.startswith("http"):
                link_url = base_url + link_url
            if "Agenda" in link_text:
                description += f"Agenda: {link_url}\n"
            if "Minutes" in link_text:
                description += f"Minutes: {link_url}\n"

        try:
            start_dt = datetime.datetime.strptime(f"{event_date} {start_time_str}", "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if end_time_str:
            try:
                end_dt = datetime.datetime.strptime(f"{event_date} {end_time_str}", "%Y-%m-%d %H:%M")
            except Exception:
                end_dt = start_dt + datetime.timedelta(hours=1)
        else:
            end_dt = start_dt + datetime.timedelta(hours=1)

        ics_events.append(make_ics_event(start_dt, end_dt, summary, description.strip()))

    return ics_events

def main():
    all_events = []

    for meeting in MEETING_TYPES:
        print(f"Fetching {meeting['name']} page...")
        response = requests.get(meeting["url"], timeout=20)
        response.raise_for_status()
        events = extract_events_from_html(response.text, meeting["name"], meeting["base_url"])
        all_events.extend(events)

    ical_content = (
        "BEGIN:VCALENDAR\n"
        "VERSION:2.0\n"
        "PRODID:-//St Mewan Parish Council//EN\n"
        "CALSCALE:GREGORIAN\n"
        "METHOD:PUBLISH\n"
        "X-WR-TIMEZONE:Europe/London\n"
        + "".join(all_events)
        + "END:VCALENDAR\n"
    )

    with open("stmewan.ics", "w", encoding="utf-8") as f:
        f.write(ical_content)

    print("Created stmewan.ics with all upcoming meetings.")

if __name__ == "__main__":
    main()
