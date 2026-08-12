"""KUPID Portal MCP Server.

Provides tools for accessing Korea University portal (KUPID):
- Login/session management
- Notice board (bulletin API b=6, no auth)
- Academic schedule (registrar.korea.ac.kr, no auth)
- Scholarship notices (bulletin API b=10, no auth)
- Search across all boards
- Library seat availability
- Academic records via AMS (수강신청/시간표/성적/개설과목/강의실, 2차 인증 필요)
- Canvas LMS (mylms.korea.ac.kr) integration
"""

import asyncio
import re
import sys
import logging
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from . import ams
from .academic import resolve_year_semester
from .auth import login, clear_session, make_client, Session
from .portal_api import (
    BoardPost,
    BOARD_NAMES,
    BOARD_NOTICE,
    BOARD_SCHOLARSHIP,
    MAX_LIST_SIZE,
    fetch_academic_schedule,
    fetch_board,
    fetch_board_page,
    fetch_post_detail,
    search_boards,
)
from .library import (
    fetch_library_seats,
    fetch_all_seats,
    LIBRARY_CODES,
)
from .timetable import (
    TimetableEntry,
    resolve_period_time,
    timetable_to_ics,
)
from .dept_notices import fetch_dept_notice_list, fetch_dept_notice_detail
from .dept_registry import resolve_site, list_all_sites, DEFAULT_SITES
from .lms import (
    lms_login,
    LMSSession,
    _clear_lms_session,
    fetch_lms_courses,
    fetch_lms_assignments,
    fetch_lms_modules,
    fetch_lms_todo,
    fetch_lms_upcoming_events,
    fetch_lms_dashboard,
    fetch_lms_announcements,
    fetch_lms_grades,
    fetch_lms_submissions,
    fetch_lms_quizzes,
    fetch_lms_syllabus,
    download_lms_file,
    fetch_lms_boards,
    fetch_lms_board_posts,
    fetch_lms_board_post,
)
from . import __version__

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

# Module-level session cache with async locks to prevent race conditions
_session: Session | None = None
_lms_session: LMSSession | None = None
_session_lock = asyncio.Lock()
_lms_session_lock = asyncio.Lock()

# Errors that may indicate a stale session (worth retrying with fresh login).
# Deliberately excludes KeyError/IndexError/AttributeError: those signal a
# response-schema/parsing bug, not an expired session, so re-logging in would
# only repeat the same failure (and risk account lockout from rapid re-auth).
# HTTPError covers 401/403 + network blips; ValueError/RuntimeError cover the
# portal returning a login page that then fails to parse.
_RETRIABLE = (
    httpx.HTTPError,
    ValueError,
    RuntimeError,
)


async def _get_session() -> Session:
    """Get or create a valid session. Proactive refresh near expiry."""
    global _session
    async with _session_lock:
        if _session and _session.is_valid and not _session.should_refresh:
            return _session
        if _session and _session.should_refresh:
            logger.info("KUPID session near expiry, proactively refreshing")
        elif _session:
            logger.info("KUPID session expired, re-logging in")
        _session = await login()
        return _session


def _format_posts(posts: list[BoardPost]) -> list[dict]:
    return [
        {
            "post_seq": post.post_seq,
            "title": post.title,
            "date": post.date,
            "writer": post.writer,
            "department": post.department,
            "views": post.views,
            "is_notice": post.is_notice,
            "attachments": post.attachments,
            "comments": post.comments,
            "summary": post.summary,
            "url": post.url,
        }
        for post in posts
    ]


async def _find_post(board_id: int, post_seq: int) -> BoardPost | None:
    """게시판 목록에서 post_seq에 해당하는 글을 찾는다.

    무인증으로는 게시글 단건 조회 API가 없어 목록에서 선형 탐색한다.
    """
    posts, _ = await fetch_board(board_id, limit=MAX_LIST_SIZE)
    for post in posts:
        if post.post_seq == post_seq:
            return post
    return None


def _normalize_calendar_semester(semester: str) -> str:
    """학사일정표는 정규학기(1/2)만 지원하므로 계절학기를 인접 학기로 매핑한다.

    학사일정표의 2학기는 8월~다음해 1월을 포함하므로, 여름(7~8월)과
    겨울(1~2월) 계절학기는 모두 해당 학년도 2학기 표에 속한다.
    """
    return "2" if semester in ("summer", "winter") else semester


async def _board_detail(board_id: int, post_seq: int, label: str) -> dict[str, Any]:
    """게시글 상세를 반환한다.

    포털 로그인이 되면 본문 전문과 첨부파일을, 실패하면 목록의 요약을 반환한다.
    """
    try:
        post = await _find_post(board_id, post_seq)
        if not post:
            return {
                "success": False,
                "message": (
                    f"post_seq={post_seq}인 {label}을(를) 최근 {MAX_LIST_SIZE}건에서 "
                    f"찾지 못했습니다. 오래된 글은 무인증 조회 범위를 벗어납니다."
                ),
            }
    except Exception as e:
        logger.error(f"Failed to fetch {label} list: {e}")
        return {"success": False, "message": f"{label} 조회 실패: {e}"}

    summary = _format_posts([post])[0]

    try:
        session = await _get_session()
        async with make_client(session) as client:
            detail = await fetch_post_detail(client, post.url)
    except Exception as e:
        # 로그인 없이도 목록 수준 정보는 돌려준다.
        logger.warning(f"{label} 본문 조회 실패, 요약으로 대체: {e}")
        return {
            "success": True,
            "detail": summary,
            "note": (
                f"본문 전문은 포털 로그인이 필요합니다 ({e}). "
                "요약(summary)과 원문 링크(url)만 제공됩니다."
            ),
        }

    return {
        "success": True,
        "detail": {
            **summary,
            # 팝업 페이지에는 작성자 이름이 없어 목록 값을 유지한다.
            "title": detail.title or summary["title"],
            "date": detail.date or summary["date"],
            "department": detail.department or summary["department"],
            "approver": detail.approver,
            "views": detail.views or summary["views"],
            "content": detail.content,
            "attachments": detail.attachments,
        },
    }


# AMS 시간표 격자의 요일 접두어 → 표시 이름
_DAY_LABELS = {
    "mon": "월",
    "tue": "화",
    "wed": "수",
    "thu": "목",
    "fri": "금",
    "sat": "토",
}


async def _resolve_ams_term(
    session: ams.AmsSession, year: str = "", semester: str = ""
) -> str:
    """학년도/학기를 AMS 학기 코드(예: 20261R)로 바꾼다.

    조회 가능한 학기만 서버가 알려주므로, 지정된 값이 목록에 없으면
    가장 최근 학기로 되돌린다.
    """
    terms = await ams.fetch_terms(session)
    if not terms:
        raise RuntimeError("조회 가능한 학기가 없습니다.")

    if year and semester:
        wanted = f"{year}{semester}R"
        for term in terms:
            if term.get("code") == wanted:
                return term["code"]
        logger.warning(f"{wanted} 학기를 찾지 못해 최근 학기로 조회합니다")

    return terms[0]["code"]


def _sum_credits(rows: list[dict]) -> float:
    """'2.0(2)' 형태의 학점 문자열을 합산한다."""
    total = 0.0
    for row in rows:
        raw = (row.get("cdtTime") or "").split("(")[0].strip()
        try:
            total += float(raw)
        except ValueError:
            continue
    return round(total, 1)


def _cell_classroom(cell: str) -> str:
    """격자 칸에서 강의실만 뽑는다.

    칸은 '<학수번호-분반><br><과목명><br><교수><br><강의실>' 형태로 온다.
    """
    parts = [p.strip() for p in re.split(r"<br\s*/?>", cell or "") if p.strip()]
    return parts[-1] if len(parts) > 1 else ""


def _grid_to_entries(grid: list[dict]) -> list[TimetableEntry]:
    """AMS 시간표 격자(교시 행 × 요일 열)를 시간표 항목 목록으로 편다."""
    entries = []
    for row in grid:
        period = (row.get("timeTime") or "").replace("교시", "").strip()
        start, end = resolve_period_time(period)
        for prefix, label in _DAY_LABELS.items():
            subject = row.get(f"{prefix}SubjtNm")
            if not subject:
                continue
            entries.append(
                TimetableEntry(
                    day_of_week=label,
                    period=period,
                    subject_name=subject,
                    classroom=_cell_classroom(row.get(f"{prefix}Nm") or ""),
                    start_time=start,
                    end_time=end,
                )
            )
    return entries


async def _get_ams_session() -> ams.AmsSession:
    """AMS 세션을 가져온다. 없으면 2차 인증이 필요하다고 알린다."""
    session = ams.load_session()
    if session and session.is_valid:
        return session
    raise RuntimeError(
        "AMS(학사) 2차 보안인증이 필요합니다. "
        "kupid_ams_auth_start()로 인증 코드를 받은 뒤 "
        "kupid_ams_auth_verify(code)로 인증을 완료하세요."
    )


# ──────────────────────────────────────────────
# 학사 시스템(AMS) 2차 인증
# ──────────────────────────────────────────────


@server.tool()
async def kupid_ams_auth_start() -> dict[str, Any]:
    """학사 시스템(AMS) 2차 보안인증을 시작해 이메일로 인증 코드를 보냅니다.

    수강신청내역·시간표·성적 조회는 학교 정책상 2차 보안인증이 필요합니다.
    이 tool을 호출하면 6자리 코드가 발송되며(5분 유효),
    kupid_ams_auth_verify(code)로 인증을 마치면 약 50분간 세션이 유지됩니다.

    코드는 KUPID 포털에 등록된 이메일로 갑니다. 발송 주소는 이 서버가 아니라
    학교가 정하며, 응답에는 마스킹된 주소만 담깁니다. 사용자가 따로 등록할
    것은 없고, 바꾸려면 포털 > My Page > 개인정보 수정에서 하면 됩니다.
    메일이 보이지 않으면 스팸함을 확인하도록 안내하세요.
    """
    try:
        session = ams.load_session()
        if session and session.is_valid and await ams.verify_session(session):
            return {
                "success": True,
                "already_authenticated": True,
                "message": "이미 인증된 세션이 있습니다. 바로 조회할 수 있습니다.",
            }

        masked_email = await ams.start_login()
        return {
            "success": True,
            "already_authenticated": False,
            "masked_email": masked_email,
            "message": (
                f"{masked_email or '등록된 메일'}로 6자리 인증 코드를 보냈습니다. "
                "5분 안에 kupid_ams_auth_verify(code)로 입력하세요."
            ),
        }
    except Exception as e:
        logger.error(f"AMS auth start failed: {e}")
        return {"success": False, "message": f"AMS 인증 시작 실패: {e}"}


@server.tool()
async def kupid_ams_auth_verify(code: str) -> dict[str, Any]:
    """이메일로 받은 6자리 코드로 학사 시스템(AMS) 인증을 완료합니다.

    Args:
        code: 메일로 받은 6자리 인증 코드
    """
    try:
        await ams.complete_login(code)
        return {
            "success": True,
            "message": "AMS 인증 완료. 수강신청내역·시간표·성적을 조회할 수 있습니다.",
        }
    except Exception as e:
        logger.error(f"AMS auth verify failed: {e}")
        return {"success": False, "message": f"AMS 인증 실패: {e}"}


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
    """KUPID 포털의 공지사항 목록을 조회합니다. (로그인 불필요)

    상단 고정 공지가 먼저 오고 그 다음 최신순으로 정렬됩니다.
    무인증 조회는 최신 500건까지만 가능합니다.

    Args:
        page: 페이지 번호 (기본값: 1)
        count: 한 페이지당 항목 수 (기본값: 20)
    """
    try:
        posts, total = await fetch_board_page(BOARD_NOTICE, page=page, count=count)
        return {
            "success": True,
            "count": len(posts),
            "total": total,
            "notices": _format_posts(posts),
        }
    except Exception as e:
        logger.error(f"Failed to fetch notices: {e}")
        return {"success": False, "message": f"공지사항 조회 실패: {e}"}


@server.tool()
async def kupid_get_notice_detail(post_seq: int) -> dict[str, Any]:
    """KUPID 공지사항의 상세 정보를 조회합니다. (로그인 불필요)

    차세대 포털은 본문 전문에 로그인을 요구하므로 요약과 원문 링크를 제공합니다.

    Args:
        post_seq: 공지사항 post_seq (kupid_get_notices 결과의 post_seq 필드)
    """
    return await _board_detail(BOARD_NOTICE, post_seq, "공지사항")


@server.tool()
async def kupid_get_schedules(
    year: int = 0, semester: int = 0, month: str = ""
) -> dict[str, Any]:
    """고려대학교 학사일정을 조회합니다. (로그인 불필요)

    교무처 학사일정표(registrar.korea.ac.kr)에서 학기별 일정을 가져옵니다.

    Args:
        year: 학년도 (예: 2026). 0이면 현재 학년도
        semester: 학기 (1 또는 2). 0이면 현재 학기
        month: 특정 월만 필터링 (예: "8월"). 비우면 전체
    """
    try:
        resolved_year, resolved_semester = resolve_year_semester(
            str(year) if year else "", str(semester) if semester else ""
        )
        resolved_semester = _normalize_calendar_semester(resolved_semester)
        if resolved_semester not in ("1", "2"):
            return {
                "success": False,
                "message": f"학사일정은 1 또는 2학기만 지원합니다 (입력: {semester})",
            }

        entries, caption = await fetch_academic_schedule(
            resolved_year, resolved_semester
        )

        if month:
            entries = [e for e in entries if e.month == month]

        return {
            "success": True,
            "year": resolved_year,
            "semester": resolved_semester,
            "caption": caption,
            "count": len(entries),
            "schedules": [
                {"month": e.month, "date": e.date, "event": e.event} for e in entries
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch schedules: {e}")
        return {"success": False, "message": f"학사일정 조회 실패: {e}"}


@server.tool()
async def kupid_get_scholarships(page: int = 1, count: int = 20) -> dict[str, Any]:
    """KUPID 포털의 장학공지 목록을 조회합니다. (로그인 불필요)

    Args:
        page: 페이지 번호 (기본값: 1)
        count: 한 페이지당 항목 수 (기본값: 20)
    """
    try:
        posts, total = await fetch_board_page(BOARD_SCHOLARSHIP, page=page, count=count)
        return {
            "success": True,
            "count": len(posts),
            "total": total,
            "scholarships": _format_posts(posts),
        }
    except Exception as e:
        logger.error(f"Failed to fetch scholarships: {e}")
        return {"success": False, "message": f"장학공지 조회 실패: {e}"}


@server.tool()
async def kupid_get_scholarship_detail(post_seq: int) -> dict[str, Any]:
    """KUPID 장학공지의 상세 정보를 조회합니다. (로그인 불필요)

    차세대 포털은 본문 전문에 로그인을 요구하므로 요약과 원문 링크를 제공합니다.

    Args:
        post_seq: 장학공지 post_seq (kupid_get_scholarships 결과의 post_seq 필드)
    """
    return await _board_detail(BOARD_SCHOLARSHIP, post_seq, "장학공지")


@server.tool()
async def kupid_search(
    keyword: str, board: str = "all", count: int = 20
) -> dict[str, Any]:
    """KUPID 포털 게시판에서 키워드로 검색합니다. (로그인 불필요)

    제목 또는 요약에 키워드가 포함된 항목을 반환합니다.
    학사일정은 게시판이 아니므로 kupid_get_schedules를 사용하세요.

    Args:
        keyword: 검색할 키워드
        board: 검색 대상 ("all", "notice", "scholarship")
        count: 최대 결과 수 (기본값: 20)
    """
    try:
        boards = {
            "notice": BOARD_NOTICE,
            "scholarship": BOARD_SCHOLARSHIP,
        }
        if board == "all":
            target_ids = list(boards.values())
        elif board in boards:
            target_ids = [boards[board]]
        else:
            return {
                "success": False,
                "message": f"잘못된 board: {board}. all/notice/scholarship 중 선택",
            }

        matches = await search_boards(keyword, target_ids, limit=MAX_LIST_SIZE)
        results = [
            {
                "board": BOARD_NAMES.get(board_id, str(board_id)),
                **_format_posts([post])[0],
            }
            for board_id, post in matches[:count]
        ]

        return {
            "success": True,
            "keyword": keyword,
            "count": len(results),
            "results": results,
        }
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
                name: [asdict(r) for r in rooms] for name, rooms in all_data.items()
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
                "occupancy_rate": f"{(total_in_use / total_seats * 100):.1f}%"
                if total_seats
                else "0%",
            },
        }
    except Exception as e:
        logger.error(f"Failed to fetch library seats: {e}")
        return {"success": False, "message": f"도서관 좌석 조회 실패: {e}"}


# ──────────────────────────────────────────────
# New: Personal timetable (SSO required)
# ──────────────────────────────────────────────


@server.tool()
async def kupid_get_timetable(
    day: str = "all", ics_export: bool = False, year: str = "", semester: str = ""
) -> dict[str, Any]:
    """개인 수업시간표를 조회합니다 (AMS 2차 인증 필요).

    Args:
        day: 요일 ("all"=전체, "mon"/"tue"/"wed"/"thu"/"fri"/"sat")
        ics_export: True이면 ICS 캘린더 파일 내용도 포함
        year: 학년도 (기본값: 현재 학기)
        semester: 학기 ("1" 또는 "2")
    """
    try:
        session = await _get_ams_session()
        term = await _resolve_ams_term(session, year, semester)
        grid = await ams.fetch_timetable(session, term)
        entries = _grid_to_entries(grid)

        if day != "all":
            if day not in _DAY_LABELS:
                return {
                    "success": False,
                    "message": f"잘못된 day: {day}. all/mon/tue/wed/thu/fri/sat 중 선택",
                }
            entries = [e for e in entries if e.day_of_week == _DAY_LABELS[day]]

        result = {
            "success": True,
            "term": term,
            "day": day,
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
        if ics_export:
            result["ics"] = timetable_to_ics(entries)
        return result
    except Exception as e:
        logger.error(f"Failed to fetch timetable: {e}")
        return {"success": False, "message": f"시간표 조회 실패: {e}"}


# ──────────────────────────────────────────────
# New: Course search & syllabus (SSO required)
# ──────────────────────────────────────────────


@server.tool()
async def kupid_search_courses(subject: str, campus: str = "") -> dict[str, Any]:
    """교과목명으로 개설과목을 검색합니다 (AMS 2차 인증 필요).

    학수번호, 분반, 강의실, 건물, 캠퍼스를 반환합니다. 학사 시스템이 제공하는
    검색 조건이 교과목명뿐이라, 단과대/학과 단위 목록 조회는 지원하지 않습니다.

    Args:
        subject: 교과목명 키워드 (필수, 부분일치)
        campus: 캠퍼스로 필터링 (예: "자연계", "인문사회계")
    """
    try:
        if not subject.strip():
            return {
                "success": False,
                "message": "교과목명 키워드(subject)는 필수입니다.",
            }

        session = await _get_ams_session()
        rows = await ams.fetch_room_guide(session, subject.strip())

        if campus:
            rows = [r for r in rows if campus in (r.get("buldCampsDivNm") or "")]

        return {
            "success": True,
            "keyword": subject,
            "count": len(rows),
            "courses": [
                {
                    "course_code": r.get("sbjtnb") or "",
                    "section": r.get("dvcno") or "",
                    "course_name": r.get("subjtNm") or "",
                    "classroom": r.get("lecrmNm") or "",
                    "building": r.get("buldDivNm") or "",
                    "campus": r.get("buldCampsDivNm") or "",
                    "dept_code": r.get("estblDeprtCd") or "",
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.error(f"Failed to search courses: {e}")
        return {"success": False, "message": f"개설과목 검색 실패: {e}"}


def _resolve_syllabus_term(
    year: str, semester: str, today: date | None = None
) -> tuple[str, str]:
    """학년도와 AMS 학기 코드(1R/2R)를 정한다.

    계절학기에는 강의계획서가 없다시피 하므로, 방학 중이면 다가오는 정규
    학기로 넘긴다(여름 → 그 해 2학기, 겨울 → 다음 학년도 1학기). 호출자가
    "1R" 같은 코드를 직접 주면 그대로 쓴다.
    """
    resolved_year, resolved_semester = resolve_year_semester(
        year or None, semester or None, today=today
    )

    if resolved_semester == "summer":
        return resolved_year, "2R"
    if resolved_semester == "winter":
        return str(int(resolved_year) + 1), "1R"

    return resolved_year, {"1": "1R", "2": "2R"}.get(
        resolved_semester, resolved_semester
    )


@server.tool()
async def kupid_syllabus(
    course_code: str,
    year: str = "",
    semester: str = "",
    section: str = "00",
    grad_dept: str = "",
) -> dict[str, Any]:
    """학수번호로 강의계획서를 조회합니다 (로그인 불필요).

    평가 비중(중간/기말/과제 %), 주차별 강의계획, 교재·참고문헌, 성적평가
    방식(절대/상대), 강의시간·강의실, 담당교수 연락처를 반환합니다.

    Args:
        course_code: 학수번호 (예: "AAI117", "BDC108")
        year: 학년도 (기본: 현재 학년도)
        semester: 학기 "1" 또는 "2" (기본: 현재 또는 다가오는 정규학기)
        section: 분반 (기본 "00")
        grad_dept: 대학원 코드 (기본: SW·AI융합대학원 7298)
    """
    try:
        code = course_code.strip().upper()
        if not code:
            return {"success": False, "message": "학수번호(course_code)는 필수입니다."}

        syy, term = _resolve_syllabus_term(year, semester)
        result = await ams.fetch_syllabus(
            code,
            syy,
            term,
            section=section or "00",
            grad_dept=grad_dept or ams.GSCIT_GRAD_DEPT,
        )

        if result is None:
            return {
                "success": False,
                "message": (
                    f"{syy}학년도 {term} {code} 과목을 찾을 수 없습니다. "
                    "미개설이거나 대학원 코드(grad_dept)가 다를 수 있습니다."
                ),
            }

        base = result["base"]
        evaluation = [
            {"item": r.get("evlItemCtnt") or "", "percent": r.get("evlSco") or 0}
            for r in result["evaluation"]
        ]

        return {
            "success": True,
            "course_code": base.get("sbjtnb") or code,
            "course_name": base.get("subjtNm") or "",
            "year": syy,
            "semester": term,
            "section": base.get("dvcno") or section,
            "credits": base.get("cdt"),
            "category": (base.get("cmpsjNm") or "").strip(),
            "department": base.get("estblDeprtNm") or "",
            "schedule": base.get("lctreTimePlaceLisup") or "",
            "professor": {
                "name": base.get("per001KorNm") or "",
                "email": base.get("per001EmailAddr") or "",
                "department": base.get("per001DeptNm") or "",
                "office": base.get("per001WorkPlace") or "",
                "office_hours": base.get("cnslgPosblTimeDesc") or "",
                "homepage": base.get("per001Homepage") or "",
            },
            "grading_method": base.get("gradeEvlMthdNm") or "",
            "grading_note": base.get("gradeEvlMthdDesc") or "",
            "evaluation": evaluation,
            "evaluation_total": sum(e["percent"] for e in evaluation),
            "goal": base.get("lrnGoalCtnt") or "",
            "outline": base.get("profSylblCtnt") or "",
            "prerequisites": base.get("atnlcRqistCtnt") or "",
            "textbook": base.get("txtbkCtnt") or "",
            "references": [
                {
                    "title": r.get("referBookNm") or "",
                    "publisher": r.get("pblcmNm") or "",
                    "isbn": r.get("isbnVal") or "",
                }
                for r in result["references"]
            ],
            "weekly": [
                {
                    "week": r.get("lessnWkOdr"),
                    "content": (r.get("lctreCtnt") or "").strip(),
                    "midterm": r.get("mdtexOprtYn") == "1",
                    "final": r.get("fnlexOprtYn") == "1",
                }
                for r in result["weekly"]
            ],
            "note": (
                "" if evaluation else "담당교수가 아직 평가 비중을 등록하지 않았습니다."
            ),
        }
    except Exception as e:
        logger.error(f"Failed to fetch syllabus: {e!r}")
        # 네트워크 예외는 메시지가 비어 오는 일이 있어 타입을 함께 남긴다.
        return {
            "success": False,
            "message": f"강의계획서 조회 실패: {type(e).__name__}: {e}",
        }


@server.tool()
async def kupid_room_schedule(
    subject: str, building: str = "", room: str = ""
) -> dict[str, Any]:
    """교과목명으로 강의실을 조회합니다 (AMS 2차 인증 필요).

    학사 시스템의 강의실안내조회는 교과목명 키워드로만 검색할 수 있어,
    "이 강의실에 무슨 수업이 있나"가 아니라 "이 과목이 어느 강의실인가"를 답합니다.
    건물·호실은 결과를 좁히는 필터로 쓰입니다.

    Args:
        subject: 교과목명 키워드 (필수, 부분일치)
        building: 건물명으로 결과 필터링 (예: "정보통신관")
        room: 강의실명으로 결과 필터링 (예: "604")
    """
    try:
        if not subject.strip():
            return {
                "success": False,
                "message": "교과목명 키워드(subject)는 필수입니다.",
            }

        session = await _get_ams_session()
        rows = await ams.fetch_room_guide(session, subject.strip())

        if building:
            rows = [r for r in rows if building in (r.get("buldDivNm") or "")]
        if room:
            rows = [r for r in rows if room in (r.get("lecrmNm") or "")]

        return {
            "success": True,
            "subject": subject,
            "count": len(rows),
            "rooms": [
                {
                    "course_code": r.get("sbjtnb") or "",
                    "section": r.get("dvcno") or "",
                    "course_name": r.get("subjtNm") or "",
                    "classroom": r.get("lecrmNm") or "",
                    "building": r.get("buldDivNm") or "",
                    "campus": r.get("buldCampsDivNm") or "",
                    "room_type": r.get("lecrmDivNm") or "",
                    "dept_code": r.get("estblDeprtCd") or "",
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch room guide: {e}")
        return {"success": False, "message": f"강의실 조회 실패: {e}"}


# ──────────────────────────────────────────────
# 학사 시스템(AMS) 조회 — 2차 보안인증 필요
# ──────────────────────────────────────────────


@server.tool()
async def kupid_my_courses(year: str = "", semester: str = "") -> dict[str, Any]:
    """내 수강신청 내역을 조회합니다 (AMS 2차 인증 필요).

    학수번호, 강의시간, 강의실, 교수, 학점, 이수구분 등 상세 정보를 반환합니다.
    대학원 과목도 포함됩니다.

    Args:
        year: 학년도 (기본값: 현재 학기 기준 자동 선택)
        semester: 학기 ("1"=1학기, "2"=2학기)
    """
    try:
        session = await _get_ams_session()
        term = await _resolve_ams_term(session, year, semester)
        rows = await ams.fetch_enrollment(session, term)

        courses = [
            {
                "course_code": r.get("sbjtnb") or "",
                "section": r.get("dvcno") or "",
                "course_name": r.get("subjtNm") or "",
                "professor": r.get("cgprfNmLisup") or "",
                "credits": r.get("cdtTime") or "",
                "course_type": (r.get("cmpsjNm") or "").strip(),
                "schedule": r.get("lctreTimePlaceLisup") or "",
                "status": r.get("sttusNm") or "",
                "payment": r.get("payDt") or "",
                "dept_code": r.get("estblDeprtCd") or "",
            }
            for r in rows
        ]
        return {
            "success": True,
            "term": term,
            "count": len(courses),
            "total_credits": _sum_credits(rows),
            "courses": courses,
        }
    except Exception as e:
        logger.error(f"Failed to fetch my courses: {e}")
        return {"success": False, "message": f"수강신청 내역 조회 실패: {e}"}


@server.tool()
async def kupid_get_all_grades(year_term: str = "") -> dict[str, Any]:
    """전체 성적, 누적 GPA, 취득학점을 조회합니다 (AMS 2차 인증 필요).

    Args:
        year_term: 학년도/학기 코드로 필터 (예: "20261R"). 비우면 전체
    """
    try:
        session = await _get_ams_session()
        rows, summary = await ams.fetch_grades(session)

        if year_term:
            rows = [
                r for r in rows if f"{r.get('syy')}{r.get('smtDivcd')}" == year_term
            ]

        grades = [
            {
                "year": r.get("syy") or "",
                "semester": r.get("smtDivcd") or "",
                "course_code": r.get("sbjtnb") or "",
                "section": r.get("dvcno") or "",
                "course_name": r.get("subjtNm") or "",
                "course_type": r.get("cmpsjDivNm") or "",
                "credits": r.get("cdt"),
                "grade": r.get("gradeGrdDivcd") or "",
                "grade_point": r.get("cmpsjGp"),
                "retake_of": r.get("ratlcSyySmtNm") or "",
            }
            for r in rows
        ]

        acmtl = summary[0] if summary else {}
        return {
            "success": True,
            "count": len(grades),
            "grades": grades,
            "summary": {
                "gpa": acmtl.get("gpa"),
                "earned_credits": acmtl.get("aplyCdt"),
                "total_grade_points": acmtl.get("tgp"),
                "converted_score": acmtl.get("covsnSco"),
                "major_credits": acmtl.get("cmpsjCdt"),
            },
        }
    except Exception as e:
        logger.error(f"Failed to fetch grades: {e}")
        return {"success": False, "message": f"성적 조회 실패: {e}"}


# ──────────────────────────────────────────────
# New: Department notices (no auth required)
# ──────────────────────────────────────────────


@server.tool()
async def kupid_dept_notices(
    site_name: str = "", page: int = 1, count: int = 20
) -> dict[str, Any]:
    """학과/대학원 홈페이지 공지사항을 조회합니다 (인증 불필요).

    고려대학교 학과 홈페이지의 공지사항 게시판을 스크래핑합니다.
    site_name을 지정하지 않으면 사용 가능한 사이트 목록을 반환합니다.

    환경변수 KU_DEPT_URLS로 소속 학과를 설정할 수 있습니다.
    형식: "라벨|URL,라벨|URL,..."
    예: "SW·AI융합대학원|https://gscit.korea.ac.kr/gscit/board/notice_master.do"

    Args:
        site_name: 사이트 이름 또는 키 (빈 문자열이면 사이트 목록 반환)
        page: 페이지 번호 (기본값: 1)
        count: 한 페이지당 항목 수 (기본값: 20)
    """
    try:
        if not site_name:
            sites = list_all_sites()
            if not sites:
                return {
                    "success": True,
                    "message": (
                        "설정된 학과 사이트가 없습니다. "
                        "환경변수 KU_DEPT_URLS를 설정하거나 site_name에 "
                        "내장 사이트 키(gscit_master, cs_under 등)를 지정하세요."
                    ),
                    "available_sites": [
                        {"key": k, "label": v["label"], "url": v["url"]}
                        for k, v in DEFAULT_SITES.items()
                    ],
                }
            return {
                "success": True,
                "message": "사이트를 선택해주세요",
                "sites": sites,
            }

        site = resolve_site(site_name)
        if not site:
            return {
                "success": False,
                "message": f"사이트를 찾을 수 없습니다: {site_name}",
                "available_sites": list_all_sites(),
            }

        offset = (page - 1) * count
        items = await fetch_dept_notice_list(site["url"], offset=offset, limit=count)
        return {
            "success": True,
            "site": site["label"],
            "page": page,
            "count": len(items),
            "notices": [
                {
                    "article_no": n.article_no,
                    "title": n.title,
                    "writer": n.writer,
                    "date": n.date,
                    "views": n.views,
                    "is_pinned": n.is_pinned,
                    "has_attachment": n.has_attachment,
                }
                for n in items
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch dept notices: {e}")
        return {"success": False, "message": f"학과 공지사항 조회 실패: {e}"}


@server.tool()
async def kupid_dept_notice_detail(site_name: str, article_no: str) -> dict[str, Any]:
    """학과/대학원 공지사항의 상세 내용을 조회합니다 (인증 불필요).

    kupid_dept_notices로 조회한 공지의 상세 내용을 가져옵니다.

    Args:
        site_name: 사이트 이름 또는 키 (kupid_dept_notices에서 사용한 값)
        article_no: 게시글 번호 (kupid_dept_notices 결과의 article_no 필드)
    """
    try:
        site = resolve_site(site_name)
        if not site:
            return {
                "success": False,
                "message": f"사이트를 찾을 수 없습니다: {site_name}",
                "available_sites": list_all_sites(),
            }

        detail = await fetch_dept_notice_detail(site["url"], article_no)
        return {
            "success": True,
            "site": site["label"],
            "notice": {
                "article_no": detail.article_no,
                "title": detail.title,
                "content": detail.content,
                "attachments": detail.attachments,
                "url": detail.url,
            },
        }
    except Exception as e:
        logger.error(f"Failed to fetch dept notice detail: {e}")
        return {"success": False, "message": f"학과 공지사항 상세 조회 실패: {e}"}


# ──────────────────────────────────────────────
# New: Canvas LMS (mylms.korea.ac.kr)
# ──────────────────────────────────────────────


async def _get_lms_session() -> LMSSession:
    """Get or create a valid LMS session. Proactive refresh near expiry."""
    global _lms_session
    async with _lms_session_lock:
        if _lms_session and _lms_session.is_valid and not _lms_session.should_refresh:
            return _lms_session
        if _lms_session and _lms_session.should_refresh:
            logger.info("LMS session near expiry, proactively refreshing")
        elif _lms_session:
            logger.info("LMS session expired, re-logging in")
        import os

        user_id = os.environ.get("KU_PORTAL_ID", "")
        password = os.environ.get("KU_PORTAL_PW", "")
        _lms_session = await lms_login(user_id, password)
        return _lms_session


async def _lms_with_retry(fn, *args, **kwargs):
    """Execute LMS API call with auto re-login on auth failure."""
    try:
        session = await _get_lms_session()
        return await fn(session, *args, **kwargs)
    except _RETRIABLE as e:
        logger.warning(
            f"LMS request failed ({type(e).__name__}: {e}), retrying with fresh session"
        )
        global _lms_session
        async with _lms_session_lock:
            _clear_lms_session()
            _lms_session = None
        session = await _get_lms_session()
        return await fn(session, *args, **kwargs)


@server.tool()
async def kupid_lms_courses() -> dict[str, Any]:
    """Canvas LMS 수강과목 목록을 조회합니다.

    mylms.korea.ac.kr의 Canvas LMS에서 수강 중인 과목 목록을 가져옵니다.
    SSO 로그인이 필요합니다.
    """
    try:
        courses = await _lms_with_retry(fetch_lms_courses)
        return {
            "success": True,
            "count": len(courses),
            "courses": [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "course_code": c.get("course_code"),
                    "term": c.get("term", {}).get("name") if c.get("term") else None,
                    "workflow_state": c.get("workflow_state"),
                }
                for c in courses
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS courses: {e}")
        return {"success": False, "message": f"LMS 수강과목 조회 실패: {e}"}


@server.tool()
async def kupid_lms_assignments(
    course_id: int, upcoming_only: bool = False
) -> dict[str, Any]:
    """Canvas LMS 과제 목록을 조회합니다.

    특정 과목의 전체 과제(assignments) 목록을 가져옵니다.
    기본적으로 완료/마감 과제 포함 전체를 반환합니다.
    kupid_lms_courses로 course_id를 먼저 확인하세요.

    Args:
        course_id: 과목 ID (kupid_lms_courses의 id 필드)
        upcoming_only: True이면 마감 전 과제만 표시 (기본값: False, 전체 과제 반환)
    """
    try:

        async def _fetch(session, cid=course_id, upcoming=upcoming_only):
            return await fetch_lms_assignments(session, cid, upcoming)

        assignments = await _lms_with_retry(_fetch)
        return {
            "success": True,
            "course_id": course_id,
            "count": len(assignments),
            "assignments": [
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "due_at": a.get("due_at"),
                    "lock_at": a.get("lock_at"),
                    "unlock_at": a.get("unlock_at"),
                    "points_possible": a.get("points_possible"),
                    "submission_types": a.get("submission_types"),
                    "submission": {
                        "workflow_state": a.get("submission", {}).get("workflow_state"),
                        "submitted_at": a.get("submission", {}).get("submitted_at"),
                        "score": a.get("submission", {}).get("score"),
                        "grade": a.get("submission", {}).get("grade"),
                        "late": a.get("submission", {}).get("late"),
                        "missing": a.get("submission", {}).get("missing"),
                    }
                    if a.get("submission")
                    else None,
                    "description": (a.get("description") or "")[:2000],
                    "html_url": a.get("html_url"),
                }
                for a in assignments
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS assignments: {e}")
        return {"success": False, "message": f"LMS 과제 조회 실패: {e}"}


@server.tool()
async def kupid_lms_modules(course_id: int) -> dict[str, Any]:
    """Canvas LMS 강의자료(모듈)를 조회합니다.

    주차별 강의 모듈과 포함된 자료를 가져옵니다.
    kupid_lms_courses로 course_id를 먼저 확인하세요.

    Args:
        course_id: 과목 ID (kupid_lms_courses의 id 필드)
    """
    try:

        async def _fetch(session, cid=course_id):
            return await fetch_lms_modules(session, cid)

        modules = await _lms_with_retry(_fetch)
        return {
            "success": True,
            "course_id": course_id,
            "count": len(modules),
            "modules": [
                {
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "position": m.get("position"),
                    "state": m.get("state"),
                    "items_count": m.get("items_count"),
                    "items": [
                        {
                            "id": item.get("id"),
                            "title": item.get("title"),
                            "type": item.get("type"),
                            "content_id": item.get("content_id"),
                            "url": item.get("url"),
                            "html_url": item.get("html_url"),
                        }
                        for item in m.get("items", [])
                    ],
                }
                for m in modules
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS modules: {e}")
        return {"success": False, "message": f"LMS 모듈 조회 실패: {e}"}


@server.tool()
async def kupid_lms_todo() -> dict[str, Any]:
    """Canvas LMS 할 일(Todo) 목록을 조회합니다.

    마감이 다가오는 과제, 퀴즈 등을 보여줍니다.
    """
    try:

        async def _fetch_all(session):
            todos = await fetch_lms_todo(session)
            events = await fetch_lms_upcoming_events(session)
            return todos, events

        todos, events = await _lms_with_retry(_fetch_all)
        return {
            "success": True,
            "todo_count": len(todos),
            "todos": [
                {
                    "type": t.get("type"),
                    "context_name": t.get("context_name"),
                    "assignment": {
                        "name": t.get("assignment", {}).get("name"),
                        "due_at": t.get("assignment", {}).get("due_at"),
                        "course_id": t.get("assignment", {}).get("course_id"),
                        "points_possible": t.get("assignment", {}).get(
                            "points_possible"
                        ),
                        "html_url": t.get("assignment", {}).get("html_url"),
                    }
                    if t.get("assignment")
                    else None,
                }
                for t in todos
            ],
            "upcoming_events_count": len(events),
            "upcoming_events": [
                {
                    "title": e.get("title"),
                    "start_at": e.get("start_at"),
                    "end_at": e.get("end_at"),
                    "html_url": e.get("html_url"),
                }
                for e in events
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS todo: {e}")
        return {"success": False, "message": f"LMS 할 일 조회 실패: {e}"}


@server.tool()
async def kupid_lms_dashboard() -> dict[str, Any]:
    """Canvas LMS 대시보드를 조회합니다.

    현재 수강 중인 과목 카드와 과제/이벤트 현황을 보여줍니다.
    """
    try:
        cards = await _lms_with_retry(fetch_lms_dashboard)
        course_ids = [c.get("id") for c in cards if c.get("id")]
        announcements = []
        if course_ids:
            try:
                announcements = await _lms_with_retry(
                    fetch_lms_announcements, course_ids[:10]
                )
            except Exception:
                pass  # Announcements may not be available

        return {
            "success": True,
            "courses": [
                {
                    "id": c.get("id"),
                    "name": c.get("shortName", c.get("longName")),
                    "course_code": c.get("courseCode"),
                    "term": c.get("term"),
                }
                for c in cards
            ],
            "announcements": [
                {
                    "id": a.get("id"),
                    "title": a.get("title"),
                    "posted_at": a.get("posted_at"),
                    "context_code": a.get("context_code"),
                    "message": (a.get("message") or "")[:300],
                }
                for a in announcements[:10]
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS dashboard: {e}")
        return {"success": False, "message": f"LMS 대시보드 조회 실패: {e}"}


@server.tool()
async def kupid_lms_announcements(course_id: int | None = None) -> dict[str, Any]:
    """Canvas LMS 공지(announcement)를 조회합니다.

    course_id를 지정하면 해당 과목, 생략하면 현재 활성 과목 전체의 공지를
    가져옵니다. kupid_lms_dashboard와 달리 message 본문을 절단하지 않고
    전문(HTML)으로 반환합니다.

    Args:
        course_id: 과목 ID (생략 시 활성 과목 전체, kupid_lms_courses 참조)
    """
    try:

        async def _fetch(session, cid=course_id):
            if cid is not None:
                ids = [cid]
            else:
                cards = await fetch_lms_dashboard(session)
                ids = [c.get("id") for c in cards if c.get("id")]
            if not ids:
                return []
            return await fetch_lms_announcements(session, ids)

        announcements = await _lms_with_retry(_fetch)
        return {
            "success": True,
            "count": len(announcements),
            "announcements": [
                {
                    "id": a.get("id"),
                    "title": a.get("title"),
                    "posted_at": a.get("posted_at"),
                    "context_code": a.get("context_code"),
                    "author": (a.get("author") or {}).get("display_name"),
                    "url": a.get("html_url") or a.get("url"),
                    "message": a.get("message"),
                }
                for a in announcements
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS announcements: {e}")
        return {"success": False, "message": f"LMS 공지 조회 실패: {e}"}


@server.tool()
async def kupid_lms_grades(course_id: int) -> dict[str, Any]:
    """Canvas LMS 성적/점수를 조회합니다.

    과목별 현재 점수, 최종 점수, 학점(grade)을 확인합니다.
    kupid_lms_courses로 course_id를 먼저 확인하세요.

    Args:
        course_id: 과목 ID (kupid_lms_courses의 id 필드)
    """
    try:

        async def _fetch(session, cid=course_id):
            return await fetch_lms_grades(session, cid)

        enrollments = await _lms_with_retry(_fetch)
        return {
            "success": True,
            "course_id": course_id,
            "enrollments": [
                {
                    "type": e.get("type"),
                    "enrollment_state": e.get("enrollment_state"),
                    "last_activity_at": e.get("last_activity_at"),
                    "grades": {
                        "current_score": e.get("grades", {}).get("current_score"),
                        "current_grade": e.get("grades", {}).get("current_grade"),
                        "final_score": e.get("grades", {}).get("final_score"),
                        "final_grade": e.get("grades", {}).get("final_grade"),
                        "current_period_score": e.get("grades", {}).get(
                            "current_period_computed_current_score"
                        ),
                        "current_period_grade": e.get("grades", {}).get(
                            "current_period_computed_current_grade"
                        ),
                        "html_url": e.get("grades", {}).get("html_url"),
                    }
                    if e.get("grades")
                    else None,
                }
                for e in enrollments
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS grades: {e}")
        return {"success": False, "message": f"LMS 성적 조회 실패: {e}"}


@server.tool()
async def kupid_lms_submissions(course_id: int) -> dict[str, Any]:
    """Canvas LMS 과제 제출 현황을 조회합니다.

    과목의 전체 과제에 대한 제출 여부, 점수, 채점 상태를 확인합니다.
    kupid_lms_courses로 course_id를 먼저 확인하세요.

    Args:
        course_id: 과목 ID (kupid_lms_courses의 id 필드)
    """
    try:

        async def _fetch(session, cid=course_id):
            return await fetch_lms_submissions(session, cid)

        submissions = await _lms_with_retry(_fetch)
        return {
            "success": True,
            "course_id": course_id,
            "count": len(submissions),
            "submissions": [
                {
                    "assignment_id": s.get("assignment_id"),
                    "assignment_name": s.get("assignment", {}).get("name")
                    if s.get("assignment")
                    else None,
                    "due_at": s.get("assignment", {}).get("due_at")
                    if s.get("assignment")
                    else None,
                    "submitted_at": s.get("submitted_at"),
                    "workflow_state": s.get("workflow_state"),
                    "score": s.get("score"),
                    "grade": s.get("grade"),
                    "late": s.get("late"),
                    "missing": s.get("missing"),
                    "points_deducted": s.get("points_deducted"),
                    "attempt": s.get("attempt"),
                    "preview_url": s.get("preview_url"),
                    "attachments": [
                        {
                            "filename": a.get("filename"),
                            "url": a.get("url"),
                            "canvas_file_id": a.get("id"),
                        }
                        for a in (s.get("attachments") or [])
                    ],
                    "comments": [
                        {
                            "author_name": c.get("author_name"),
                            "comment": c.get("comment"),
                            "created_at": c.get("created_at"),
                        }
                        for c in (s.get("submission_comments") or [])
                    ],
                }
                for s in submissions
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS submissions: {e}")
        return {"success": False, "message": f"LMS 제출 현황 조회 실패: {e}"}


@server.tool()
async def kupid_lms_quizzes(course_id: int) -> dict[str, Any]:
    """Canvas LMS 퀴즈/시험 목록을 조회합니다.

    과목의 퀴즈, 시험, 설문 목록과 마감일, 시간제한 등을 확인합니다.
    kupid_lms_courses로 course_id를 먼저 확인하세요.

    Args:
        course_id: 과목 ID (kupid_lms_courses의 id 필드)
    """
    try:

        async def _fetch(session, cid=course_id):
            return await fetch_lms_quizzes(session, cid)

        quizzes = await _lms_with_retry(_fetch)
        return {
            "success": True,
            "course_id": course_id,
            "count": len(quizzes),
            "quizzes": [
                {
                    "id": q.get("id"),
                    "title": q.get("title"),
                    "quiz_type": q.get("quiz_type"),
                    "due_at": q.get("due_at"),
                    "lock_at": q.get("lock_at"),
                    "time_limit": q.get("time_limit"),
                    "question_count": q.get("question_count"),
                    "points_possible": q.get("points_possible"),
                    "published": q.get("published"),
                    "html_url": q.get("html_url"),
                }
                for q in quizzes
            ],
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS quizzes: {e}")
        return {"success": False, "message": f"LMS 퀴즈 조회 실패: {e}"}


@server.tool()
async def kupid_lms_syllabus(
    course_code: str = "", course_id: int = 0
) -> dict[str, Any]:
    """Canvas LMS 수업 계획서(syllabus)를 조회합니다.

    과목의 수업 계획서 내용을 가져옵니다.
    course_code(예: BDC115) 또는 course_id 중 하나를 입력하세요.
    course_code를 입력하면 수강과목 목록에서 자동으로 course_id를 찾습니다.

    Args:
        course_code: 과목코드 (예: BDC115). course_id 대신 사용 가능
        course_id: 과목 ID (kupid_lms_courses의 id 필드). course_code 대신 사용 가능
    """
    from bs4 import BeautifulSoup

    if not course_code and not course_id:
        return {
            "success": False,
            "message": "course_code 또는 course_id 중 하나를 입력하세요.",
        }

    try:
        # course_code로 조회 시 course_id 찾기
        if course_code and not course_id:
            courses = await _lms_with_retry(fetch_lms_courses)
            keyword = course_code.upper()
            matched = [
                c
                for c in courses
                if keyword in (c.get("course_code") or "").upper()
                or keyword in (c.get("name") or "").upper()
            ]
            if not matched:
                return {
                    "success": False,
                    "message": f"'{course_code}'에 해당하는 수강과목을 찾을 수 없습니다. "
                    "kupid_lms_courses로 수강과목 목록을 확인하세요.",
                }
            if len(matched) > 1:
                return {
                    "success": False,
                    "message": f"'{course_code}'에 해당하는 과목이 {len(matched)}개 있습니다. course_id를 지정하세요.",
                    "candidates": [
                        {
                            "id": c.get("id"),
                            "name": c.get("name"),
                            "course_code": c.get("course_code"),
                        }
                        for c in matched
                    ],
                }
            course_id = matched[0]["id"]

        async def _fetch(session, cid=course_id):
            return await fetch_lms_syllabus(session, cid)

        course_data = await _lms_with_retry(_fetch)

        syllabus_html = course_data.get("syllabus_body") or ""
        syllabus_text = ""

        if syllabus_html:
            soup = BeautifulSoup(syllabus_html, "lxml")

            syllabus_text = soup.get_text(separator="\n", strip=True)

        return {
            "success": True,
            "course_id": course_id,
            "course_name": course_data.get("name"),
            "course_code": course_data.get("course_code"),
            "term": course_data.get("term", {}).get("name")
            if course_data.get("term")
            else None,
            "syllabus_url": f"https://mylms.korea.ac.kr/courses/{course_id}/assignments/syllabus",
            "syllabus": syllabus_text
            if syllabus_text
            else "(수업 계획서가 비어 있습니다)",
        }
    except Exception as e:
        logger.error(f"Failed to fetch LMS syllabus: {e}")
        return {"success": False, "message": f"LMS 수업 계획서 조회 실패: {e}"}


@server.tool()
async def kupid_lms_download_file(
    file_id: int,
    save_dir: str,
    filename: str = "",
) -> dict[str, Any]:
    """Canvas LMS 파일을 지정한 디렉토리에 다운로드합니다.

    file_id는 kupid_lms_modules 결과의 items에서 type이 'File'인 항목의
    content_id 필드에서 얻을 수 있습니다.

    Args:
        file_id: Canvas 파일 ID (items[*].content_id)
        save_dir: 저장할 디렉토리 절대경로 (예: /Users/me/Documents/lecture)
        filename: 저장 파일명 (생략 시 Canvas 원본 파일명 사용)
    """
    try:
        # Expand ~ and validate absolute path
        raw_path = save_dir.strip()
        if not raw_path:
            return {"success": False, "message": "save_dir가 비어 있습니다."}
        target_dir = Path(raw_path).expanduser()
        if not target_dir.is_absolute():
            return {
                "success": False,
                "message": f"save_dir는 절대경로여야 합니다: {save_dir}",
            }
        if ".." in target_dir.parts:
            return {
                "success": False,
                "message": "save_dir에 '..'를 포함할 수 없습니다.",
            }

        fname = filename.strip() or None

        async def _fetch(session, fid=file_id, d=target_dir, fn=fname):
            return await download_lms_file(session, fid, d, fn)

        result = await _lms_with_retry(_fetch)
        return {
            "success": True,
            "file_id": file_id,
            **result,
        }
    except Exception as e:
        logger.error(f"Failed to download LMS file {file_id}: {e}")
        return {"success": False, "message": f"LMS 파일 다운로드 실패: {e}"}


@server.tool()
async def kupid_lms_list_boards(course_id: int) -> dict[str, Any]:
    """Canvas LMS 과목의 게시판 목록을 조회합니다.

    Q&A 게시판, 강의자료실 등 교수님이 자료를 올리는 게시판들을 반환합니다.
    Canvas 네이티브 모듈(kupid_lms_modules)에 자료가 없으면 여기서 찾아보세요.

    Args:
        course_id: 과목 ID (kupid_lms_courses의 id 필드)
    """
    try:

        async def _fetch(session, cid=course_id):
            return await fetch_lms_boards(session, cid)

        boards = await _lms_with_retry(_fetch)
        return {
            "success": True,
            "course_id": course_id,
            "count": len(boards),
            "boards": [
                {
                    "id": b.get("id"),
                    "title": b.get("title"),
                    "type": b.get("type"),
                    "slug": b.get("slug"),
                    "use_attachment": b.get("use_attachment"),
                }
                for b in boards
            ],
        }
    except Exception as e:
        logger.error(f"Failed to list LMS boards: {e}")
        return {"success": False, "message": f"LMS 게시판 목록 조회 실패: {e}"}


@server.tool()
async def kupid_lms_list_board_posts(
    course_id: int,
    board_id: int,
    page: int = 1,
    keyword: str = "",
) -> dict[str, Any]:
    """게시판의 게시글 목록을 조회합니다.

    Args:
        course_id: 과목 ID
        board_id: 게시판 ID (kupid_lms_list_boards의 id 필드)
        page: 페이지 번호 (기본 1)
        keyword: 제목 검색어 (기본 전체)
    """
    try:

        async def _fetch(session, cid=course_id, bid=board_id, pg=page, kw=keyword):
            return await fetch_lms_board_posts(session, cid, bid, pg, kw)

        data = await _lms_with_retry(_fetch)
        items = data.get("items", []) if isinstance(data, dict) else []
        return {
            "success": True,
            "course_id": course_id,
            "board_id": board_id,
            "page": page,
            "count": len(items),
            "posts": [
                {
                    "id": p.get("id"),
                    "idx": p.get("idx"),
                    "title": p.get("title"),
                    "user_name": p.get("user_name"),
                    "attachment_count": p.get("attachment_count"),
                    "comment_count": p.get("comment_count"),
                    "view_count": p.get("view_count"),
                    "is_notice": p.get("is_notice"),
                    "created_at": p.get("created_at"),
                }
                for p in items
            ],
        }
    except Exception as e:
        logger.error(f"Failed to list board posts: {e}")
        return {"success": False, "message": f"게시글 목록 조회 실패: {e}"}


@server.tool()
async def kupid_lms_get_board_post(
    course_id: int,
    board_id: int,
    post_id: int,
) -> dict[str, Any]:
    """게시글 상세와 첨부파일, 댓글(첨부 포함)을 조회합니다.

    attachments의 canvas_file_id를 kupid_lms_download_file의 file_id로
    넘기면 파일을 다운로드할 수 있습니다. attachments[].url은 직접
    다운로드 링크입니다(시간제한 verifier 토큰 포함).

    comments에는 각 댓글의 본문과 첨부파일(동영상/PDF 등)이 포함됩니다.
    예: 텀프로젝트 게시판에서 팀별 발표 동영상은 댓글 첨부로 제출됩니다.

    Args:
        course_id: 과목 ID
        board_id: 게시판 ID
        post_id: 게시글 ID (kupid_lms_list_board_posts의 id 필드)
    """
    try:

        async def _fetch(session, cid=course_id, bid=board_id, pid=post_id):
            return await fetch_lms_board_post(session, cid, bid, pid)

        post = await _lms_with_retry(_fetch)

        def _attachments(items):
            return [
                {
                    "id": a.get("id"),
                    "filename": a.get("filename"),
                    "filesize": a.get("filesize"),
                    "canvas_file_id": a.get("canvas_file_id"),
                    "url": a.get("url"),
                }
                for a in (items or [])
            ]

        return {
            "success": True,
            "post": {
                "id": post.get("id"),
                "title": post.get("title"),
                "user_name": post.get("user_name"),
                "content": post.get("content"),
                "created_at": post.get("created_at"),
                "updated_at": post.get("updated_at"),
                "view_count": post.get("view_count"),
                "comment_count": post.get("comment_count"),
                "attachments": _attachments(post.get("attachments")),
                "comments": [
                    {
                        "id": c.get("id"),
                        "user_name": c.get("user_name"),
                        "content": c.get("content"),
                        "created_at": c.get("created_at"),
                        "is_secret": c.get("is_secret"),
                        "attachments": _attachments(c.get("attachments")),
                    }
                    for c in post.get("comments", [])
                    if not c.get("is_deleted")
                ],
            },
        }
    except Exception as e:
        logger.error(f"Failed to get board post: {e}")
        return {"success": False, "message": f"게시글 조회 실패: {e}"}


def main():
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"ku-portal-mcp {__version__}")
        return
    if "--help" in sys.argv or "-h" in sys.argv:
        print("ku-portal-mcp - Korea University KUPID Portal MCP Server")
        print(f"Version: {__version__}")
        print("\nUsage:")
        print("  ku-portal-mcp          Start MCP server (stdio)")
        print("  ku-portal-mcp --version  Show version")
        print("\nEnvironment variables:")
        print("  KU_PORTAL_ID    KUPID portal ID")
        print("  KU_PORTAL_PW    KUPID portal password")
        return

    try:
        logger.info(f"Starting KU Portal MCP Server v{__version__}...")
        logger.info(f"Python: {sys.version}")
        server.run()
    except Exception as e:
        logger.error(f"Server error: {e}")
        import traceback

        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
