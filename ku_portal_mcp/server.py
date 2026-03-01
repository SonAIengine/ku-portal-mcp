"""KUPID Portal MCP Server.

Provides tools for accessing Korea University portal (KUPID):
- Login/session management
- Notice board (kind=11)
- Academic schedule (kind=89)
- Scholarship notices (kind=88)
- Search across all boards
- Library seat availability
- Personal timetable
- Course search & syllabus
"""

import sys
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .auth import login, clear_session, Session
from .scraper import fetch_notice_list, fetch_notice_detail, NoticeItem
from .library import (
    fetch_library_seats, fetch_all_seats,
    LIBRARY_CODES,
)
from .timetable import (
    fetch_timetable_day, fetch_full_timetable, timetable_to_ics,
)
from .courses import (
    search_courses, fetch_syllabus, fetch_departments,
    COLLEGE_CODES,
)

# Load .env file (looks in cwd, then project root)
load_dotenv()

# Logging setup — file logging only to keep stdout clean for MCP protocol
log_dir = Path.home() / ".cache" / "ku-portal-mcp"
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_dir / "server.log")],
)
logger = logging.getLogger(__name__)

server = FastMCP(
    "KU Portal",
    dependencies=["httpx", "beautifulsoup4", "lxml"],
)

# Module-level session cache for reuse across tool calls
_session: Session | None = None


async def _get_session() -> Session:
    """Get or create a valid session. Auto re-login on expiry."""
    global _session
    if _session and _session.is_valid:
        return _session
    _session = await login()
    return _session


async def _with_retry(fn, *args, **kwargs):
    """Execute fn with session, auto re-login on failure and retry once."""
    try:
        session = await _get_session()
        return await fn(session, *args, **kwargs)
    except Exception:
        # Session might be stale — clear and retry
        global _session
        clear_session()
        _session = None
        session = await _get_session()
        return await fn(session, *args, **kwargs)


def _format_items(items: list[NoticeItem], count: int) -> list[dict]:
    return [
        {
            "index": item.index,
            "message_id": item.message_id,
            "title": item.title,
            "date": item.date,
            "writer": item.writer,
        }
        for item in items[:count]
    ]


# ──────────────────────────────────────────────
# Existing tools: Login / Notice / Schedule / Scholarship / Search
# ──────────────────────────────────────────────

@server.tool()
async def kupid_login() -> dict[str, Any]:
    """KUPID 포털에 로그인하고 세션을 확인합니다.

    환경변수 KU_PORTAL_ID, KU_PORTAL_PW가 설정되어 있어야 합니다.
    세션이 유효하면 캐시된 세션을 재사용합니다.
    """
    try:
        session = await _get_session()
        return {
            "success": True,
            "message": "KUPID 로그인 성공",
            "session_valid": session.is_valid,
        }
    except Exception as e:
        clear_session()
        return {"success": False, "message": f"로그인 실패: {e}"}


@server.tool()
async def kupid_get_notices(page: int = 1, count: int = 20) -> dict[str, Any]:
    """KUPID 포털의 공지사항 목록을 조회합니다.

    Args:
        page: 페이지 번호 (기본값: 1)
        count: 한 페이지당 항목 수 (기본값: 20)
    """
    try:
        async def _fetch(session):
            return await fetch_notice_list(session, kind="11", page=page, count=count)

        items = await _with_retry(_fetch)
        return {"success": True, "count": len(items), "notices": _format_items(items, count)}
    except Exception as e:
        logger.error(f"Failed to fetch notices: {e}")
        return {"success": False, "message": f"공지사항 조회 실패: {e}"}


@server.tool()
async def kupid_get_notice_detail(notice_id: str, message_id: str = "") -> dict[str, Any]:
    """KUPID 공지사항의 상세 내용을 조회합니다.

    Args:
        notice_id: 공지사항 index (kupid_get_notices 결과의 index 필드)
        message_id: 공지사항 message_id (kupid_get_notices 결과의 message_id 필드)
    """
    try:
        item = NoticeItem(index=notice_id, message_id=message_id, kind="11",
                          title="", date="", writer="")

        async def _fetch(session):
            return await fetch_notice_detail(session, item)

        detail = await _with_retry(_fetch)
        return {
            "success": True,
            "notice": {
                "id": detail.id, "title": detail.title, "date": detail.date,
                "writer": detail.writer, "content": detail.content,
                "attachments": detail.attachments, "url": detail.url,
            },
        }
    except Exception as e:
        logger.error(f"Failed to fetch notice detail: {e}")
        return {"success": False, "message": f"공지사항 상세 조회 실패: {e}"}


@server.tool()
async def kupid_get_schedules(page: int = 1, count: int = 20) -> dict[str, Any]:
    """KUPID 포털의 학사일정 목록을 조회합니다.

    Args:
        page: 페이지 번호 (기본값: 1)
        count: 한 페이지당 항목 수 (기본값: 20)
    """
    try:
        async def _fetch(session):
            return await fetch_notice_list(session, kind="89", page=page, count=count)

        items = await _with_retry(_fetch)
        return {"success": True, "count": len(items), "schedules": _format_items(items, count)}
    except Exception as e:
        logger.error(f"Failed to fetch schedules: {e}")
        return {"success": False, "message": f"학사일정 조회 실패: {e}"}


@server.tool()
async def kupid_get_schedule_detail(schedule_id: str, message_id: str = "") -> dict[str, Any]:
    """KUPID 학사일정의 상세 내용을 조회합니다.

    Args:
        schedule_id: 학사일정 index (kupid_get_schedules 결과의 index 필드)
        message_id: 학사일정 message_id (kupid_get_schedules 결과의 message_id 필드)
    """
    try:
        item = NoticeItem(index=schedule_id, message_id=message_id, kind="89",
                          title="", date="", writer="")

        async def _fetch(session):
            return await fetch_notice_detail(session, item)

        detail = await _with_retry(_fetch)
        return {
            "success": True,
            "schedule": {
                "id": detail.id, "title": detail.title, "date": detail.date,
                "writer": detail.writer, "content": detail.content,
                "attachments": detail.attachments, "url": detail.url,
            },
        }
    except Exception as e:
        logger.error(f"Failed to fetch schedule detail: {e}")
        return {"success": False, "message": f"학사일정 상세 조회 실패: {e}"}


@server.tool()
async def kupid_get_scholarships(page: int = 1, count: int = 20) -> dict[str, Any]:
    """KUPID 포털의 장학공지 목록을 조회합니다.

    Args:
        page: 페이지 번호 (기본값: 1)
        count: 한 페이지당 항목 수 (기본값: 20)
    """
    try:
        async def _fetch(session):
            return await fetch_notice_list(session, kind="88", page=page, count=count)

        items = await _with_retry(_fetch)
        return {"success": True, "count": len(items), "scholarships": _format_items(items, count)}
    except Exception as e:
        logger.error(f"Failed to fetch scholarships: {e}")
        return {"success": False, "message": f"장학공지 조회 실패: {e}"}


@server.tool()
async def kupid_get_scholarship_detail(scholarship_id: str, message_id: str = "") -> dict[str, Any]:
    """KUPID 장학공지의 상세 내용을 조회합니다.

    Args:
        scholarship_id: 장학공지 index (kupid_get_scholarships 결과의 index 필드)
        message_id: 장학공지 message_id (kupid_get_scholarships 결과의 message_id 필드)
    """
    try:
        item = NoticeItem(index=scholarship_id, message_id=message_id, kind="88",
                          title="", date="", writer="")

        async def _fetch(session):
            return await fetch_notice_detail(session, item)

        detail = await _with_retry(_fetch)
        return {
            "success": True,
            "scholarship": {
                "id": detail.id, "title": detail.title, "date": detail.date,
                "writer": detail.writer, "content": detail.content,
                "attachments": detail.attachments, "url": detail.url,
            },
        }
    except Exception as e:
        logger.error(f"Failed to fetch scholarship detail: {e}")
        return {"success": False, "message": f"장학공지 상세 조회 실패: {e}"}


@server.tool()
async def kupid_search(keyword: str, board: str = "all", count: int = 20) -> dict[str, Any]:
    """KUPID 포털에서 키워드로 공지사항/학사일정/장학공지를 검색합니다.

    제목에 키워드가 포함된 항목을 반환합니다.

    Args:
        keyword: 검색할 키워드
        board: 검색 대상 ("all", "notice", "schedule", "scholarship")
        count: 최대 결과 수 (기본값: 20)
    """
    try:
        boards = {
            "notice": "11",
            "schedule": "89",
            "scholarship": "88",
        }
        if board == "all":
            targets = boards.items()
        elif board in boards:
            targets = [(board, boards[board])]
        else:
            return {"success": False, "message": f"잘못된 board: {board}. all/notice/schedule/scholarship 중 선택"}

        results = []
        kw_lower = keyword.lower()

        for board_name, kind in targets:
            async def _fetch(session, k=kind):
                return await fetch_notice_list(session, kind=k)

            items = await _with_retry(_fetch)
            for item in items:
                if kw_lower in item.title.lower():
                    results.append({
                        "board": board_name,
                        "index": item.index,
                        "message_id": item.message_id,
                        "title": item.title,
                        "date": item.date,
                        "writer": item.writer,
                    })

        results = results[:count]
        return {"success": True, "keyword": keyword, "count": len(results), "results": results}
    except Exception as e:
        logger.error(f"Failed to search: {e}")
        return {"success": False, "message": f"검색 실패: {e}"}


# ──────────────────────────────────────────────
# New: Library seat availability (no auth required)
# ──────────────────────────────────────────────

@server.tool()
async def kupid_get_library_seats(library_name: str = "") -> dict[str, Any]:
    """고려대학교 도서관 열람실 좌석 현황을 조회합니다.

    인증 없이 실시간 좌석 현황을 확인할 수 있습니다.

    Args:
        library_name: 도서관 이름 필터 (빈 문자열이면 전체 도서관 조회)
            - 중앙도서관, 중앙광장, 백주년기념 학술정보관, 과학도서관, 하나스퀘어, 법학도서관
    """
    try:
        if library_name:
            # Find matching library code
            code = None
            for c, name in LIBRARY_CODES.items():
                if library_name in name or name in library_name:
                    code = c
                    break
            if not code:
                return {
                    "success": False,
                    "message": f"도서관을 찾을 수 없습니다: {library_name}",
                    "available_libraries": list(LIBRARY_CODES.values()),
                }
            rooms = await fetch_library_seats(code)
            library_data = {LIBRARY_CODES[code]: [asdict(r) for r in rooms]}
        else:
            all_data = await fetch_all_seats()
            library_data = {
                name: [asdict(r) for r in rooms]
                for name, rooms in all_data.items()
            }

        # Calculate totals
        total_seats = 0
        total_available = 0
        total_in_use = 0
        for rooms in library_data.values():
            for room in rooms:
                total_seats += room["total_seats"]
                total_available += room["available"]
                total_in_use += room["in_use"]

        return {
            "success": True,
            "libraries": library_data,
            "summary": {
                "total_seats": total_seats,
                "total_available": total_available,
                "total_in_use": total_in_use,
                "occupancy_rate": f"{(total_in_use / total_seats * 100):.1f}%" if total_seats else "0%",
            },
        }
    except Exception as e:
        logger.error(f"Failed to fetch library seats: {e}")
        return {"success": False, "message": f"도서관 좌석 조회 실패: {e}"}


# ──────────────────────────────────────────────
# New: Personal timetable (SSO required)
# ──────────────────────────────────────────────

@server.tool()
async def kupid_get_timetable(day: str = "all", ics_export: bool = False) -> dict[str, Any]:
    """개인 수업시간표를 조회합니다 (SSO 로그인 필요).

    포털 메인 페이지의 시간표 위젯 데이터를 파싱합니다.

    Args:
        day: 요일 ("all"=전체, "mon"/"tue"/"wed"/"thu"/"fri")
        ics_export: True이면 ICS 캘린더 파일 내용도 포함
    """
    try:
        day_map = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5}

        if day == "all":
            async def _fetch(session):
                return await fetch_full_timetable(session)
            entries = await _with_retry(_fetch)
        elif day in day_map:
            d = day_map[day]
            async def _fetch_day(session, d=d):
                return await fetch_timetable_day(session, d)
            entries = await _with_retry(_fetch_day)
        else:
            return {
                "success": False,
                "message": f"잘못된 요일: {day}. all/mon/tue/wed/thu/fri 중 선택",
            }

        result = {
            "success": True,
            "count": len(entries),
            "timetable": [
                {
                    "day": e.day_of_week,
                    "period": e.period,
                    "subject": e.subject_name,
                    "classroom": e.classroom,
                    "start_time": e.start_time,
                    "end_time": e.end_time,
                }
                for e in entries
            ],
        }

        if not entries:
            result["message"] = "등록된 수업이 없습니다"

        if ics_export and entries:
            result["ics_content"] = timetable_to_ics(entries)

        return result
    except Exception as e:
        logger.error(f"Failed to fetch timetable: {e}")
        return {"success": False, "message": f"시간표 조회 실패: {e}"}


# ──────────────────────────────────────────────
# New: Course search & syllabus (SSO required)
# ──────────────────────────────────────────────

@server.tool()
async def kupid_search_courses(
    year: str = "2026",
    semester: str = "1",
    college: str = "",
    department: str = "",
    campus: str = "1",
) -> dict[str, Any]:
    """개설과목을 검색합니다 (SSO 로그인 필요).

    학과/단과대별로 개설된 과목을 조회합니다.
    단과대 코드가 비어있으면 사용 가능한 단과대 목록을 반환합니다.

    Args:
        year: 학년도 (기본값: "2026")
        semester: 학기 ("1"=1학기, "2"=2학기, "summer"=여름학기, "winter"=겨울학기)
        college: 단과대 코드 (예: "5720"=정보대학, ""이면 코드 목록 반환)
        department: 학과 코드 (예: "5722"=컴퓨터학과, ""이면 학과 목록 반환)
        campus: 캠퍼스 ("1"=서울, "2"=세종)
    """
    try:
        # If no college specified, return available colleges
        if not college:
            return {
                "success": True,
                "message": "단과대 코드를 선택해주세요",
                "colleges": [
                    {"code": code, "name": name}
                    for code, name in COLLEGE_CODES.items()
                ],
            }

        # If no department specified, fetch department list
        if not department:
            async def _fetch_depts(session, col=college):
                return await fetch_departments(session, col, year, semester)
            depts = await _with_retry(_fetch_depts)
            college_name = COLLEGE_CODES.get(college, college)
            return {
                "success": True,
                "message": f"{college_name}의 학과를 선택해주세요",
                "college": college_name,
                "departments": depts,
            }

        # Search courses
        async def _fetch_courses(session):
            return await search_courses(
                session, year=year, semester=semester,
                campus=campus, college=college, department=department,
            )

        courses = await _with_retry(_fetch_courses)
        return {
            "success": True,
            "count": len(courses),
            "courses": [
                {
                    "campus": c.campus,
                    "course_code": c.course_code,
                    "section": c.section,
                    "course_type": c.course_type,
                    "course_name": c.course_name,
                    "professor": c.professor,
                    "credits": c.credits,
                    "schedule": c.schedule,
                }
                for c in courses
            ],
        }
    except Exception as e:
        logger.error(f"Failed to search courses: {e}")
        return {"success": False, "message": f"개설과목 검색 실패: {e}"}


@server.tool()
async def kupid_get_syllabus(
    course_code: str,
    section: str = "00",
    year: str = "2026",
    semester: str = "1",
) -> dict[str, Any]:
    """강의계획서를 조회합니다 (SSO 로그인 필요).

    Args:
        course_code: 학수번호 (예: "COSE101")
        section: 분반 (예: "02")
        year: 학년도 (기본값: "2026")
        semester: 학기 ("1"=1학기, "2"=2학기, "summer"=여름학기, "winter"=겨울학기)
    """
    try:
        async def _fetch(session):
            return await fetch_syllabus(
                session, course_code=course_code, section=section,
                year=year, semester=semester,
            )

        content = await _with_retry(_fetch)

        if not content or len(content) < 50:
            return {
                "success": False,
                "message": f"강의계획서를 찾을 수 없습니다: {course_code} (분반 {section})",
            }

        return {
            "success": True,
            "course_code": course_code,
            "section": section,
            "year": year,
            "semester": semester,
            "content": content,
        }
    except Exception as e:
        logger.error(f"Failed to fetch syllabus: {e}")
        return {"success": False, "message": f"강의계획서 조회 실패: {e}"}


def main():
    try:
        logger.info("Starting KU Portal MCP Server v0.3.0...")
        logger.info(f"Python: {sys.version}")
        server.run()
    except Exception as e:
        logger.error(f"Server error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
