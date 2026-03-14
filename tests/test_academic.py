from datetime import date

from ku_portal_mcp.academic import get_default_year_semester, resolve_year_semester


def test_get_default_year_semester_for_winter_uses_previous_academic_year():
    assert get_default_year_semester(date(2026, 1, 15)) == ("2025", "winter")


def test_get_default_year_semester_for_first_semester():
    assert get_default_year_semester(date(2026, 3, 14)) == ("2026", "1")


def test_resolve_year_semester_keeps_explicit_values():
    assert resolve_year_semester("2024", "2", today=date(2026, 3, 14)) == ("2024", "2")


def test_resolve_year_semester_fills_missing_values():
    assert resolve_year_semester("", "", today=date(2026, 7, 10)) == ("2026", "summer")
