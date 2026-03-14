from ku_portal_mcp.timetable import TimetableEntry, _resolve_period_time, timetable_to_ics


def test_resolve_period_time_for_range():
    assert _resolve_period_time("2-3") == ("10:30", "13:15")


def test_resolve_period_time_returns_original_value_for_unknown_period():
    assert _resolve_period_time("A") == ("A", "A")


def test_timetable_to_ics_generates_weekly_event():
    entries = [
        TimetableEntry(
            day_of_week="월",
            period="1",
            subject_name="알고리즘",
            classroom="과학도서관 101",
            start_time="09:00",
            end_time="10:15",
        )
    ]

    ics = timetable_to_ics(entries, semester_start="2026-03-02")

    assert "BEGIN:VCALENDAR" in ics
    assert "SUMMARY:알고리즘" in ics
    assert "LOCATION:과학도서관 101" in ics
    assert "DTSTART:20260302T090000" in ics
    assert "DTEND:20260302T101500" in ics
    assert "RRULE:FREQ=WEEKLY;COUNT=16" in ics
