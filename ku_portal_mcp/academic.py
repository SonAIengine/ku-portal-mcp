"""Academic year/semester defaults for Korea University."""

from __future__ import annotations

from datetime import date


def get_default_year_semester(today: date | None = None) -> tuple[str, str]:
    """Return the best-effort current academic year and semester.

    Mapping:
    - Jan-Feb: previous academic year winter term
    - Mar-Jun: current academic year 1st semester
    - Jul-Aug: current academic year summer term
    - Sep-Dec: current academic year 2nd semester
    """
    if today is None:
        today = date.today()

    month = today.month
    year = today.year

    if month <= 2:
        return str(year - 1), "winter"
    if month <= 6:
        return str(year), "1"
    if month <= 8:
        return str(year), "summer"
    return str(year), "2"


def resolve_year_semester(
    year: str | None = None,
    semester: str | None = None,
    today: date | None = None,
) -> tuple[str, str]:
    """Resolve missing year/semester values using the current academic term."""
    default_year, default_semester = get_default_year_semester(today=today)
    return (year or default_year), (semester or default_semester)
