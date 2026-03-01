"""KUPID Portal MCP Server.

Provides tools for accessing Korea University portal (KUPID):
- Login/session management
- Notice board (kind=11)
- Academic schedule (kind=89)
- Scholarship notices (kind=88)
- Search across all boards
"""

import sys
import logging
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .auth import login, clear_session, Session
from .scraper import fetch_notice_list, fetch_notice_detail, NoticeItem

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


def main():
    try:
        logger.info("Starting KU Portal MCP Server...")
        logger.info(f"Python: {sys.version}")
        server.run()
    except Exception as e:
        logger.error(f"Server error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
