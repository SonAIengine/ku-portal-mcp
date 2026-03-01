"""Library seat availability for Korea University libraries.

Uses the HODI (librsv.korea.ac.kr) public JSON API.
No authentication required.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

LIBRSV_BASE = "https://librsv.korea.ac.kr"

# Library code mapping (from /libraries/lib endpoint)
LIBRARY_CODES = {
    1: "중앙도서관",
    2: "중앙광장",
    3: "백주년기념 학술정보관",
    4: "과학도서관",
    5: "하나스퀘어",
    6: "법학도서관",
}

_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "accept": "application/json, text/plain, */*",
    "referer": f"{LIBRSV_BASE}/",
}


@dataclass
class ReadingRoomStatus:
    room_name: str
    room_name_eng: str
    total_seats: int
    available: int
    in_use: int
    disabled: int
    is_notebook_allowed: bool
    operating_hours: str


async def fetch_library_list() -> list[dict[str, Any]]:
    """Fetch list of libraries from HODI API."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{LIBRSV_BASE}/libraries/lib",
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 1:
        raise RuntimeError(f"HODI API error: {data.get('message')}")

    return data["data"]


async def fetch_library_seats(library_code: int) -> list[ReadingRoomStatus]:
    """Fetch seat status for a specific library."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{LIBRSV_BASE}/libraries/lib-status/{library_code}",
            headers=_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 1:
        raise RuntimeError(f"HODI API error: {data.get('message')}")

    rooms = []
    for room in data.get("data", []):
        start = room.get("startTm", "0000")
        end = room.get("endTm", "0000")
        if start == "0000" and end == "0000":
            hours = "24시간"
        else:
            hours = f"{start[:2]}:{start[2:]}-{end[:2]}:{end[2:]}"

        rooms.append(ReadingRoomStatus(
            room_name=room.get("name", ""),
            room_name_eng=room.get("nameEng", ""),
            total_seats=room.get("cnt", 0),
            available=room.get("available", 0),
            in_use=room.get("inUse", 0),
            disabled=room.get("disabled", 0),
            is_notebook_allowed=room.get("noteBookYN") == "Y",
            operating_hours=hours,
        ))

    return rooms


async def fetch_all_seats() -> dict[str, list[ReadingRoomStatus]]:
    """Fetch seat status for all libraries."""
    result = {}
    for code, name in sorted(LIBRARY_CODES.items()):
        try:
            rooms = await fetch_library_seats(code)
            result[name] = rooms
        except Exception as e:
            logger.warning(f"Failed to fetch seats for {name}: {e}")
    return result
