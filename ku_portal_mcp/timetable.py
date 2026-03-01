"""Personal timetable retrieval from KUPID portal.

Fetches the timetable widget from the portal main page via
POST /front/EkuSchedule.kpd AJAX endpoint.
Requires SSO login.
"""

import asyncio
import re
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from .auth import Session, PORTAL_BASE, _BROWSER_HEADERS

logger = logging.getLogger(__name__)

TIMETABLE_URL = f"{PORTAL_BASE}/front/EkuSchedule.kpd"

DAY_NAMES = {0: "일", 1: "월", 2: "화", 3: "수", 4: "목", 5: "금", 6: "토"}

# Standard period-to-time mapping for Korea University
PERIOD_TIMES = {
    "1": ("09:00", "10:15"),
    "2": ("10:30", "11:45"),
    "3": ("12:00", "13:15"),
    "4": ("13:30", "14:45"),
    "5": ("15:00", "16:15"),
    "6": ("16:30", "17:45"),
    "7": ("18:00", "18:50"),
    "8": ("19:00", "19:50"),
    "9": ("20:00", "20:50"),
}


@dataclass
class TimetableEntry:
    day_of_week: str
    period: str
    subject_name: str
    classroom: str
    start_time: str
    end_time: str


async def fetch_timetable_day(session: Session, day: int) -> list[TimetableEntry]:
    """Fetch timetable entries for a specific day of the week.

    Args:
        session: Valid KUPID session.
        day: Day of week (0=Sun, 1=Mon, ..., 6=Sat).

    Returns:
        List of timetable entries for that day.
    """
    cookie = (
        f"ssotoken={session.ssotoken}; "
        f"PORTAL_SESSIONID={session.portal_session_id};"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            TIMETABLE_URL,
            data={"week": str(day)},
            headers={
                **_BROWSER_HEADERS,
                "cookie": cookie,
                "referer": f"{PORTAL_BASE}/front/Main.kpd",
                "content-type": "application/x-www-form-urlencoded",
                "x-requested-with": "XMLHttpRequest",
            },
        )
        resp.raise_for_status()

    html = resp.text
    return _parse_timetable_html(html, day)


def _parse_timetable_html(html: str, day: int) -> list[TimetableEntry]:
    """Parse timetable HTML response into structured entries."""
    soup = BeautifulSoup(html, "lxml")
    entries = []

    day_name = DAY_NAMES.get(day, str(day))

    tbody = soup.find("tbody")
    if not tbody:
        return entries

    for row in tbody.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 3:
            # "강의가 없습니다" row has colspan=3
            continue

        period = tds[0].get_text(strip=True)
        subject = tds[1].get_text(strip=True)
        classroom = tds[2].get_text(strip=True)

        if not subject or subject == "강의가 없습니다":
            continue

        # Resolve start/end times from period
        start_time, end_time = _resolve_period_time(period)

        entries.append(TimetableEntry(
            day_of_week=day_name,
            period=period,
            subject_name=subject,
            classroom=classroom,
            start_time=start_time,
            end_time=end_time,
        ))

    return entries


def _resolve_period_time(period: str) -> tuple[str, str]:
    """Convert period string (e.g., '1', '2-3') to start/end times."""
    parts = re.split(r"[-~]", period.strip())
    start_period = parts[0].strip()
    end_period = parts[-1].strip()

    start_time = PERIOD_TIMES.get(start_period, ("", ""))[0]
    end_time = PERIOD_TIMES.get(end_period, ("", ""))[1]

    return start_time or period, end_time or period


async def fetch_full_timetable(session: Session) -> list[TimetableEntry]:
    """Fetch the full weekly timetable (Mon-Fri) in parallel."""
    results = await asyncio.gather(
        *(fetch_timetable_day(session, day) for day in range(1, 6))
    )
    all_entries = []
    for entries in results:
        all_entries.extend(entries)
    return all_entries


def timetable_to_ics(entries: list[TimetableEntry], semester_start: str = "") -> str:
    """Convert timetable entries to ICS (iCalendar) format.

    Args:
        entries: Timetable entries.
        semester_start: Semester start date (YYYY-MM-DD). Defaults to next Monday.

    Returns:
        ICS calendar string.
    """
    if not semester_start:
        today = datetime.now()
        # Find next Monday
        days_ahead = 0 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        start_date = today + timedelta(days=days_ahead)
    else:
        start_date = datetime.strptime(semester_start, "%Y-%m-%d")

    day_to_offset = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ku-portal-mcp//KU Timetable//KO",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:KU 수업시간표",
    ]

    for entry in entries:
        offset = day_to_offset.get(entry.day_of_week, 0)
        event_date = start_date + timedelta(days=offset - start_date.weekday())
        if event_date < start_date:
            event_date += timedelta(weeks=1)

        if ":" in entry.start_time and ":" in entry.end_time:
            sh, sm = entry.start_time.split(":")
            eh, em = entry.end_time.split(":")
            dtstart = event_date.replace(hour=int(sh), minute=int(sm))
            dtend = event_date.replace(hour=int(eh), minute=int(em))
        else:
            continue

        uid = f"{entry.subject_name}-{entry.day_of_week}-{entry.period}@kupid"

        lines.extend([
            "BEGIN:VEVENT",
            f"DTSTART:{dtstart.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{dtend.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{entry.subject_name}",
            f"LOCATION:{entry.classroom}",
            f"DESCRIPTION:교시: {entry.period}",
            f"UID:{uid}",
            "RRULE:FREQ=WEEKLY;COUNT=16",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
