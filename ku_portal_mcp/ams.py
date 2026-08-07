"""고려대 학사 시스템(ams.korea.ac.kr) 클라이언트.

2026년 전환으로 `infodepot.korea.ac.kr`이 종료되고 학사 기능이 AMS로 이전됐다.
AMS는 **2차 보안인증이 필수**라 일반 SSO 로그인만으로는 들어갈 수 없다.

로그인은 두 단계로 나뉜다. 사용자가 인증 코드를 확인해 넣어야 하기 때문이다.

    start_login()      SSO 로그인 → 2차 인증 화면 → 이메일 OTP 발송
                       (진행 상태를 pending 파일에 보관)
    complete_login()   OTP 검증 → 보류된 로그인 폼 재제출 → AMS 세션 확립

2차 인증 화면 HTML에는 이미 암호화된 비밀번호가 담긴 `sso_option_change` 폼이
들어 있어, OTP 검증 뒤 그 폼을 그대로 제출하면 로그인이 끝난다.

조회 API는 넥사크로 계열 DataSet 규약을 쓴다. 요청에 메뉴/프로그램 식별자를
그대로 실어야 하고, 조건은 `@d1#<필드>` 형태로 전달한다.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from . import sso
from ._storage import write_secure_json as _write_secure_json

logger = logging.getLogger(__name__)

AMS_BASE = "https://ams.korea.ac.kr"
ENTRY_URL = f"{AMS_BASE}/com/lgin/SsoCtr/initPageWork.do"

# SSO 서비스 ID (Auth.eps의 id 파라미터)
SERVICE_AMS = "ams"
SESSION_CHECK_URL = f"{AMS_BASE}/com/cnst/PropCtr/findViewSession.do"

EMAIL_MASK_URL = f"{sso.SSO_BASE}/korea/EmailMasking.eps"

CACHE_DIR = Path.home() / ".cache" / "ku-portal-mcp"
AMS_SESSION_FILE = CACHE_DIR / "ams_session.json"
AMS_PENDING_FILE = CACHE_DIR / "ams_pending.json"

# AMS 세션은 서버가 3600초를 알려준다. 여유를 두고 50분만 재사용한다.
AMS_SESSION_TTL = 50 * 60
# OTP 유효시간은 5분. 그보다 짧게 잡아 만료된 상태로 시도하지 않는다.
PENDING_TTL = 4 * 60

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
    for path in (AMS_SESSION_FILE, AMS_PENDING_FILE):
        if path.exists():
            path.unlink()


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


def _dump_cookies(client: httpx.AsyncClient) -> list[dict[str, str]]:
    return [
        {
            "name": c.name,
            "value": c.value or "",
            "domain": c.domain,
            "path": c.path,
        }
        for c in client.cookies.jar
    ]


def _parse_second_login_form(html: str) -> dict[str, str]:
    """2차 인증 통과 후 재제출할 로그인 폼을 읽는다.

    이 폼에는 암호화된 비밀번호가 이미 들어 있어, 비밀번호를 다시 만들 필요가 없다.
    """
    form = BeautifulSoup(html, "lxml").find(id="sso_option_change")
    if not form:
        raise RuntimeError(
            "2차 인증 화면에서 재로그인 폼을 찾지 못했습니다. "
            "인증 절차가 변경되었을 수 있습니다."
        )
    return {
        i["name"]: (i.get("value") or "")
        for i in form.find_all("input")
        if i.get("name")
    }


async def start_login(menu_id: str = MENU_ENROLLMENT) -> str:
    """SSO 로그인 후 이메일로 OTP를 발송한다. 마스킹된 수신 주소를 반환한다.

    이후 `complete_login(code)`로 이어진다.
    """
    user_id = os.environ.get("KU_PORTAL_ID")
    password = os.environ.get("KU_PORTAL_PW")
    if not user_id or not password:
        raise RuntimeError(
            "KU_PORTAL_ID / KU_PORTAL_PW 환경변수가 설정되지 않았습니다."
        )

    client = make_client()
    try:
        # AMS 진입 페이지는 SPA라 브라우저 JS가 세션을 확인한 뒤에야 SSO로 넘어간다.
        # 스크립트에서는 SSO 로그인 폼으로 곧장 들어간다.
        relay = f"{AMS_BASE}/index.html?menuId={menu_id}&isPc=true"
        page = await sso.fetch_login_page(client, SERVICE_AMS, relay)
        resp = await sso.submit_login(client, page, user_id, password)

        if "sso_option_change" not in resp.text:
            raise RuntimeError(
                f"2차 인증 화면에 도달하지 못했습니다 (위치: {resp.url}). "
                "자격증명 또는 인증 절차를 확인하세요."
            )

        pending_form = _parse_second_login_form(resp.text)
        headers = {
            "user-agent": sso._UA,
            "referer": str(resp.url),
            "origin": sso.SSO_BASE,
            "x-requested-with": "XMLHttpRequest",
            "accept": "application/json",
        }

        # 이메일 OTP 모드로 전환하면서 수신 주소를 받는다
        mask = await client.post(EMAIL_MASK_URL, headers=headers)
        masked_email = ""
        try:
            masked_email = mask.json().get("maskEmail") or ""
        except ValueError:
            pass

        sent = await client.post(sso.IOP_OTP_REQ_URL, headers=headers)
        result = sent.json()
        if result.get("returnCode") != "0000":
            raise RuntimeError(
                f"OTP 발송 실패: {result.get('returnMessage') or result}"
            )

        _write_secure_json(
            AMS_PENDING_FILE,
            {
                "cookies": _dump_cookies(client),
                "form": pending_form,
                "referer": str(resp.url),
                "created_at": time.time(),
            },
        )
        return masked_email or result.get("maskEmail") or ""
    finally:
        await client.aclose()


async def complete_login(code: str) -> AmsSession:
    """이메일로 받은 6자리 코드로 2차 인증을 마치고 AMS 세션을 확립한다."""
    code = (code or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise RuntimeError("인증 코드는 6자리 숫자여야 합니다.")

    pending = _load(AMS_PENDING_FILE, PENDING_TTL)
    if not pending:
        raise RuntimeError(
            "진행 중인 인증이 없거나 만료되었습니다. 인증을 다시 시작하세요."
        )

    session = AmsSession(cookies=pending["cookies"], created_at=pending["created_at"])
    client = make_client(session)
    try:
        headers = {
            "user-agent": sso._UA,
            "referer": pending["referer"],
            "origin": sso.SSO_BASE,
            "x-requested-with": "XMLHttpRequest",
            "accept": "application/json",
        }
        verify = await client.post(
            sso.IOP_OTP_VERIFY_URL,
            data={"cert_no": code, "div": "scnd"},
            headers=headers,
        )
        result = verify.json()
        if result.get("returnCode") != "0000":
            raise RuntimeError(
                f"인증 실패: {result.get('returnMessage') or result.get('errMsg') or result}"
            )

        # 보류해 둔 로그인 폼을 그대로 제출하면 로그인이 마무리된다
        resp = await client.post(
            sso.LOGIN_URL,
            data=pending["form"],
            headers={
                "user-agent": sso._UA,
                "referer": pending["referer"],
                "origin": sso.SSO_BASE,
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        # 후처리 리다이렉트가 실패해도 세션은 이미 섰을 수 있다.
        # OTP는 일회용이라 여기서 중단하면 코드를 다시 받아야 하므로, 확인까지 진행한다.
        try:
            resp = await sso.follow_auto_forms(client, resp)
        except Exception as e:
            logger.warning(f"로그인 후처리 중 오류(무시하고 세션 확인): {e}")

        check = await client.get(
            SESSION_CHECK_URL,
            headers={"user-agent": sso._UA, "accept": "application/json"},
        )
        if check.json().get("dmLoginConfirm", {}).get("isLogin") != "1":
            raise RuntimeError(
                f"AMS 로그인이 완료되지 않았습니다 (최종 위치: {resp.url})."
            )

        ams_session = AmsSession(cookies=_dump_cookies(client), created_at=time.time())
    finally:
        await client.aclose()

    _write_secure_json(AMS_SESSION_FILE, asdict(ams_session))
    if AMS_PENDING_FILE.exists():
        AMS_PENDING_FILE.unlink()
    logger.info("AMS login successful")
    return ams_session


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


async def fetch_grades(session: AmsSession) -> tuple[list[dict], list[dict]]:
    """전체 성적과 누계 성적을 반환한다. 둘은 같은 응답에 함께 담겨 온다."""
    data = await query_raw(session, API_GRADES, stuno="")
    return (data.get(API_GRADES.dataset) or [], data.get("dsGradeAcmtlAll") or [])
