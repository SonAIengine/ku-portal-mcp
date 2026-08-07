"""고려대 학사 시스템(ams.korea.ac.kr) 클라이언트.

2026년 전환으로 `infodepot.korea.ac.kr`이 종료되고 학사 기능이 AMS로 이전됐다.
AMS는 **2차 보안인증이 필수**라 일반 SSO 로그인만으로는 들어갈 수 없다.

로그인은 두 단계로 나뉜다. 사용자가 메일에서 인증 코드를 확인해 넣어야 한다.

    start_login()      2차 인증 시작 → 이메일로 코드 발송
    complete_login()   코드 검증 → AMS 세션 확립

인증 단계는 `_ams_auth` 브라우저 헬퍼가 처리한다. 서버가 브라우저 컨텍스트를
엄격히 검증해, 순수 HTTP로는 OTP를 맞게 넣어도 세션이 승격되지 않기 때문이다.
인증이 끝나면 쿠키만 넘겨받아 이후 조회는 httpx로 수행한다.

조회 API는 넥사크로 계열 DataSet 규약을 쓴다. 요청에 메뉴/프로그램 식별자를
그대로 실어야 하고, 조건은 `@d1#<필드>` 형태로 전달한다.
"""

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import _ams_auth, sso

logger = logging.getLogger(__name__)

AMS_BASE = "https://ams.korea.ac.kr"
SESSION_CHECK_URL = f"{AMS_BASE}/com/cnst/PropCtr/findViewSession.do"

CACHE_DIR = Path.home() / ".cache" / "ku-portal-mcp"
AMS_SESSION_FILE = CACHE_DIR / _ams_auth.SESSION_FILE
HELPER_PID_FILE = CACHE_DIR / "ams_auth.pid"

# AMS 세션은 서버가 3600초를 알려준다. 여유를 두고 50분만 재사용한다.
AMS_SESSION_TTL = 50 * 60

# 메뉴 코드 (포털 메뉴 API에서 확인)
MENU_ENROLLMENT = "M111422"  # 수강신청조회
MENU_TIMETABLE = "M111423"  # 시간표조회
MENU_GRADES = "M112493"  # 전체성적조회
MENU_ROOM = "M112596"  # 강의실안내조회


@dataclass(frozen=True)
class AmsApi:
    """AMS 조회 API 한 건. 식별자는 요청에 그대로 실어야 한다."""

    path: str
    menu_id: str
    menu_name: str
    program_id: str
    dataset: str


API_TERMS = AmsApi(
    "/sch/sles/SlesstCtr/findAppcsSyySmtDivSchdlList.do",
    "MTI4MTU5MjY3Njg4NzUzNTAwMDA=",
    "수강신청조회",
    "MTUwMjA4MTgwMjcx",
    "dsSyySmtDivcd",
)
API_ENROLLMENT = AmsApi(
    "/sch/sles/SlesstCtr/findStdAppcsDtlsList.do",
    "MTI4MTU5MjY3Njg4NzUzNTAwMDA=",
    "수강신청조회",
    "MTUwMjA4MTgwMjcx",
    "dsSles511",
)
API_TIMETABLE = AmsApi(
    "/sch/sles/SlesstCtr/findStdLctreTimtbOutptList.do",
    "MTI4MTYyNzE3ODkwMjQxMTUwMDA=",
    "시간표조회",
    "MTUwMjQzMDYzMzI2",
    "dsSles332",
)
API_ROOM_GUIDE = AmsApi(
    "/sch/sles/SleslcCtr/findProfLecrmGudncList.do",
    "MTMyMjUyNTkwMDM4NDY5MjgwMDA=",
    "강의실안내조회",
    "MTUxNDY2NTIxNzUx",
    "dsLecrmGudnc",
)
API_GRADES = AmsApi(
    "/sch/sgra/SgrassCtr/findStdntGradeAllList.do",
    "MTMxODkwMDI3MjA5NjYyOTgwMDA=",
    "전체성적조회",
    "MTkzMzU1NDM4MDY2",
    "dsGradeAll",
)


@dataclass
class AmsSession:
    cookies: list[dict[str, str]] = field(default_factory=list)
    created_at: float = 0.0

    @property
    def is_valid(self) -> bool:
        return bool(self.cookies) and (time.time() - self.created_at) < AMS_SESSION_TTL


def _load(path: Path, ttl: float) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if (time.time() - data.get("created_at", 0)) < ttl:
            return data
    except Exception as e:
        logger.warning(f"Failed to load {path.name}: {e}")
    return None


def load_session() -> AmsSession | None:
    data = _load(AMS_SESSION_FILE, AMS_SESSION_TTL)
    if not data:
        return None
    return AmsSession(cookies=data.get("cookies") or [], created_at=data["created_at"])


def clear_session() -> None:
    _stop_helper()
    for name in (_ams_auth.SESSION_FILE, _ams_auth.STATUS_FILE, _ams_auth.CODE_FILE):
        (CACHE_DIR / name).unlink(missing_ok=True)


def make_client(session: AmsSession | None = None, **kwargs) -> httpx.AsyncClient:
    kwargs.setdefault("timeout", 30.0)
    kwargs.setdefault("follow_redirects", True)
    client = httpx.AsyncClient(**kwargs)
    for cookie in session.cookies if session else []:
        client.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain", ""),
            path=cookie.get("path", "/"),
        )
    return client


def _stop_helper() -> None:
    """살아 있는 인증 헬퍼 프로세스를 정리한다."""
    if not HELPER_PID_FILE.exists():
        return
    try:
        os.kill(int(HELPER_PID_FILE.read_text().strip()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    HELPER_PID_FILE.unlink(missing_ok=True)


async def _await_status(wanted: set[str], timeout: float) -> dict:
    """헬퍼가 기록하는 상태 파일을 원하는 상태가 될 때까지 지켜본다."""
    status_path = CACHE_DIR / _ams_auth.STATUS_FILE
    deadline = time.time() + timeout
    while time.time() < deadline:
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text())
            except json.JSONDecodeError:
                status = {}
            if status.get("state") in wanted:
                return status
        await asyncio.sleep(1)
    _stop_helper()
    raise RuntimeError("인증 절차가 시간 안에 끝나지 않았습니다.")


async def start_login(menu_id: str = MENU_ENROLLMENT) -> str:
    """2차 인증을 시작해 이메일로 인증 코드를 보낸다. 마스킹된 수신 주소를 반환한다.

    AMS는 순수 HTTP 요청으로는 OTP를 맞게 넣어도 세션이 승격되지 않아,
    이 단계만 브라우저 헬퍼에 맡긴다. 헬퍼는 사용자가 코드를 넣을 때까지
    살아 있어야 하므로 별도 프로세스로 띄우고 파일로 신호를 주고받는다.
    """
    if not os.environ.get("KU_PORTAL_ID") or not os.environ.get("KU_PORTAL_PW"):
        raise RuntimeError(
            "KU_PORTAL_ID / KU_PORTAL_PW 환경변수가 설정되지 않았습니다."
        )

    _stop_helper()
    for name in (_ams_auth.STATUS_FILE, _ams_auth.CODE_FILE):
        (CACHE_DIR / name).unlink(missing_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    process = subprocess.Popen(
        [sys.executable, "-m", "ku_portal_mcp._ams_auth", str(CACHE_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    HELPER_PID_FILE.write_text(str(process.pid))

    status = await _await_status({"code_sent", "error"}, timeout=120)
    if status.get("state") == "error":
        raise RuntimeError(status.get("message") or "인증을 시작하지 못했습니다.")

    # 발송 안내 문구에 마스킹된 주소가 실려 온다
    for message in status.get("dialogs") or []:
        found = re.search(r"[\w.*-]+@[\w.*-]+", message)
        if found:
            return found.group(0)
    return ""


async def complete_login(code: str) -> AmsSession:
    """이메일로 받은 6자리 코드로 2차 인증을 마치고 AMS 세션을 확립한다."""
    code = (code or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise RuntimeError("인증 코드는 6자리 숫자여야 합니다.")

    status_path = CACHE_DIR / _ams_auth.STATUS_FILE
    if not status_path.exists():
        raise RuntimeError(
            "진행 중인 인증이 없습니다. kupid_ams_auth_start()로 다시 시작하세요."
        )

    (CACHE_DIR / _ams_auth.CODE_FILE).write_text(code)
    status = await _await_status({"done", "error"}, timeout=180)
    _stop_helper()

    if status.get("state") == "error":
        raise RuntimeError(status.get("message") or "인증에 실패했습니다.")

    session = load_session()
    if not session:
        raise RuntimeError("인증은 끝났지만 세션을 읽지 못했습니다.")
    logger.info("AMS login successful")
    return session


async def verify_session(session: AmsSession) -> bool:
    """AMS 세션이 서버에서 아직 유효한지 확인한다."""
    try:
        async with make_client(session, timeout=15.0) as client:
            resp = await client.get(
                SESSION_CHECK_URL,
                headers={"user-agent": sso._UA, "accept": "application/json"},
            )
            return resp.json().get("dmLoginConfirm", {}).get("isLogin") == "1"
    except Exception:
        return False


async def query_raw(session: AmsSession, api: AmsApi, **conditions: str) -> dict:
    """AMS 조회 API를 호출해 응답 전체(여러 DataSet)를 반환한다."""
    payload = {
        "_menuId": api.menu_id,
        "_menuNm": api.menu_name,
        "_pgmId": api.program_id,
        "@d#": "@d1#",
        "@d1#": "dmCond",
        "@d1#tp": "dm",
    }
    for key, value in conditions.items():
        payload[f"@d1#{key}"] = value

    async with make_client(session) as client:
        resp = await client.post(
            AMS_BASE + api.path,
            data=payload,
            headers={
                "user-agent": sso._UA,
                "referer": f"{AMS_BASE}/index.html",
                "origin": AMS_BASE,
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(
                f"AMS 응답이 JSON이 아닙니다(세션 만료 가능): {e}"
            ) from e

    if not data.get("_METADATA_", {}).get("success", True):
        raise RuntimeError(f"AMS 조회 실패: {data.get('_METADATA_')}")

    return data


async def query(session: AmsSession, api: AmsApi, **conditions: str) -> list[dict]:
    """AMS 조회 API를 호출해 기본 DataSet의 행들을 반환한다."""
    data = await query_raw(session, api, **conditions)
    return data.get(api.dataset) or []


async def fetch_terms(session: AmsSession) -> list[dict]:
    """조회 가능한 학기 목록. [{'code': '20261R', 'fullNm': '2026학년도 1학기'}]"""
    return await query(session, API_TERMS, syySmtDivcd="")


async def fetch_enrollment(session: AmsSession, term_code: str) -> list[dict]:
    """수강신청 내역."""
    return await query(session, API_ENROLLMENT, syySmtDivcd=term_code)


async def fetch_timetable(session: AmsSession, term_code: str) -> list[dict]:
    """시간표(교시 × 요일 격자)."""
    return await query(session, API_TIMETABLE, syySmtDivcd=term_code)


async def fetch_room_guide(session: AmsSession, keyword: str) -> list[dict]:
    """교과목명 키워드로 강의실 안내를 조회한다. 키워드는 필수다."""
    return await query(session, API_ROOM_GUIDE, subjtKwrd=keyword)


async def fetch_grades(session: AmsSession) -> tuple[list[dict], list[dict]]:
    """전체 성적과 누계 성적을 반환한다. 둘은 같은 응답에 함께 담겨 온다."""
    data = await query_raw(session, API_GRADES, stuno="")
    return (data.get(API_GRADES.dataset) or [], data.get("dsGradeAcmtlAll") or [])
