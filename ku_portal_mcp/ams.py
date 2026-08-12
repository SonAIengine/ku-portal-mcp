"""고려대 학사 시스템(ams.korea.ac.kr) 클라이언트.

2026년 전환으로 `infodepot.korea.ac.kr`이 종료되고 학사 기능이 AMS로 이전됐다.
AMS는 **2차 보안인증이 필수**라 일반 SSO 로그인만으로는 들어갈 수 없다.

로그인은 두 단계로 나뉜다. 사용자가 메일에서 인증 코드를 확인해 넣어야 한다.

    start_login()      2차 인증 시작 → 이메일로 코드 발송
    complete_login()   코드 검증 → AMS 세션 확립

인증은 브라우저 없이 순수 HTTP로 처리한다. 다만 SSO가 RelayState를 올바른
형식으로 만들도록 `/exsignon/main/main.jsp` 진입점에서 시작해야 하고, OTP를
검증한 뒤에도 로그인 폼 재제출 → `sso_identify.jsp` → `j_login_sso.do`를
차례로 밟아야 AMS 애플리케이션 세션이 선다.

조회 API는 넥사크로 계열 DataSet 규약을 쓴다. 요청에 메뉴/프로그램 식별자를
그대로 실어야 하고, 조건은 `@d1#<필드>` 형태로 전달한다.
"""

import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import httpx

from . import sso
from ._storage import write_secure_json

logger = logging.getLogger(__name__)

AMS_BASE = "https://ams.korea.ac.kr"
SESSION_CHECK_URL = f"{AMS_BASE}/com/cnst/PropCtr/findViewSession.do"

CACHE_DIR = Path.home() / ".cache" / "ku-portal-mcp"
AMS_SESSION_FILE = CACHE_DIR / "ams_session.json"
AMS_PENDING_FILE = CACHE_DIR / "ams_pending.json"

# AMS 세션은 서버가 3600초를 알려준다. 여유를 두고 50분만 재사용한다.
AMS_SESSION_TTL = 50 * 60
# 인증 코드는 5분간 유효하다. 여유를 둬 그보다 조금 길게 잡는다.
AMS_PENDING_TTL = 8 * 60

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

# 강의계획서는 로그인 없이 열린다. 다만 기본정보와 세부내용이 API가 나뉘어
# 있어, 기본정보만 보고 "계획서가 비었다"고 판단하면 틀린다. 배점 필드
# (tb1000~tbTot)는 계획서가 채워진 과목에서도 늘 0으로 내려온다.
API_SYLLABUS_INFO = AmsApi(
    "/sch/sles/SleslcCtr/findAllLctreSyllaRegPopList.do",
    "MzMzODYzMjY=",
    "",
    "MTg3NDA2",
    "dsSles361",
)
# 평가항목·주차별 계획·참고문헌이 여기 담긴다.
API_SYLLABUS_PLAN = AmsApi(
    "/sch/sles/SleslcCtr/findAllLctreSyllaPopLrnPlanList.do",
    "MzMzODYzMjY=",
    "",
    "MTg3NDA2",
    "dsSles366",
)

# SW·AI융합대학원. 대학원 코드는 소속 대학원마다 다르다.
GSCIT_GRAD_DEPT = "7298"


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
        path.unlink(missing_ok=True)


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


def _login_forms(html: str) -> list:
    """action이 있고 입력이 있는 폼. 로그아웃 계열은 제외한다.

    로그인 직후 페이지에는 로그아웃 폼이 섞여 있어, 아무 폼이나 제출하면
    방금 세운 세션이 SLO(Single Logout)로 날아간다.
    """
    from bs4 import BeautifulSoup

    out = []
    for f in BeautifulSoup(html, "lxml").find_all("form"):
        action = (f.get("action") or "").lower()
        if not action or not f.find_all("input"):
            continue
        if any(k in action for k in ("logout", "slo", "slores")):
            continue
        out.append(f)
    return out


def _form_fields(form) -> dict[str, str]:
    return {
        i["name"]: (i.get("value") or "")
        for i in form.find_all("input")
        if i.get("name")
    }


def _entry_url(menu_id: str) -> str:
    """AMS의 SSO 진입점.

    반드시 이 경로로 들어가야 SSO가 RelayState를 상대 경로 형식으로 만든다.
    `Auth.eps`를 직접 부르면 RelayState가 절대 URL이 되고, 서버가 리다이렉트
    주소를 `base + RelayState`로 이어붙이는 탓에 호스트가 겹친 깨진 URL이 나온다.
    """
    target = f"{AMS_BASE}?menuId={menu_id}&isPc=true"
    token = base64.b64encode(target.encode()).decode().rstrip("=")
    return f"{AMS_BASE}/exsignon/main/main.jsp?RelayState={token}"


async def _follow_forms(client: httpx.AsyncClient, resp, hops: int = 8):
    """자동 제출 폼 체인을 따라가되 로그인 폼에서 멈춘다."""
    for _ in range(hops):
        forms = _login_forms(resp.text)
        if not forms:
            return resp
        form = forms[0]
        if form.find("input", {"id": "ipt_id"}) or form.find(
            "input", {"name": "user_password"}
        ):
            return resp  # 자격증명을 넣어야 하는 폼
        resp = await client.post(
            urljoin(str(resp.url), form["action"]),
            data=_form_fields(form),
            headers={"user-agent": sso._UA},
        )
    return resp


async def start_login(menu_id: str = MENU_ENROLLMENT) -> str:
    """2차 인증을 시작해 이메일로 인증 코드를 보낸다. 마스킹된 수신 주소를 반환한다.

    브라우저 없이 순수 HTTP로 처리한다. 이어지는 `complete_login()`이 같은
    세션을 써야 하므로, 쿠키와 2차 인증 폼 필드를 디스크에 남긴다.
    """
    user_id = os.environ.get("KU_PORTAL_ID")
    password = os.environ.get("KU_PORTAL_PW")
    if not user_id or not password:
        raise RuntimeError(
            "KU_PORTAL_ID / KU_PORTAL_PW 환경변수가 설정되지 않았습니다."
        )

    async with make_client() as client:
        resp = await client.get(
            _entry_url(menu_id), headers={"user-agent": sso._UA, "accept": "text/html"}
        )
        resp = await _follow_forms(client, resp)

        page = sso.parse_login_page(resp.text, str(resp.url))
        resp = await sso.submit_login(client, page, user_id, password)
        if "sso_option_change" not in resp.text:
            raise RuntimeError(
                f"2차 인증 화면에 도달하지 못했습니다 (위치: {resp.url}). "
                "ID/비밀번호를 확인하세요."
            )

        from bs4 import BeautifulSoup

        form = BeautifulSoup(resp.text, "lxml").find(id="sso_option_change")
        if form is None:
            raise RuntimeError("2차 인증 폼을 찾지 못했습니다.")

        ajax = {
            "user-agent": sso._UA,
            "origin": sso.SSO_BASE,
            "referer": str(resp.url),
            "x-requested-with": "XMLHttpRequest",
            "accept": "application/json",
        }
        # 이메일 OTP 수단으로 전환한 뒤 코드를 발송한다. 둘 다 바디가 없고
        # 서버는 세션 쿠키로 사용자를 식별한다.
        masked = await client.post(sso.EMAIL_MASKING_URL, headers=ajax)
        sent = await client.post(sso.IOP_OTP_REQ_URL, headers=ajax)
        try:
            result = sent.json()
        except ValueError as e:
            raise RuntimeError(f"OTP 요청 응답이 JSON이 아닙니다: {e}") from e
        if result.get("returnCode") != "0000":
            raise RuntimeError(
                result.get("returnMessage") or "인증 코드를 보내지 못했습니다."
            )

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        write_secure_json(
            AMS_PENDING_FILE,
            {
                "cookies": [
                    {
                        "name": c.name,
                        "value": c.value,
                        "domain": c.domain,
                        "path": c.path,
                    }
                    for c in client.cookies.jar
                ],
                "fields": _form_fields(form),
                "referer": str(resp.url),
                "menu_id": menu_id,
                "created_at": time.time(),
            },
        )

    address = result.get("maskEmail") or ""
    if not address:
        try:
            address = masked.json().get("maskEmail", "")
        except ValueError:
            address = ""
    return address


async def complete_login(code: str) -> AmsSession:
    """이메일로 받은 6자리 코드로 2차 인증을 마치고 AMS 세션을 확립한다."""
    code = (code or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise RuntimeError("인증 코드는 6자리 숫자여야 합니다.")

    pending = _load(AMS_PENDING_FILE, AMS_PENDING_TTL)
    if not pending:
        raise RuntimeError(
            "진행 중인 인증이 없거나 만료됐습니다. "
            "kupid_ams_auth_start()로 다시 시작하세요."
        )

    session = AmsSession(cookies=pending["cookies"])
    async with make_client(session) as client:
        ajax = {
            "user-agent": sso._UA,
            "origin": sso.SSO_BASE,
            "referer": pending["referer"],
            "x-requested-with": "XMLHttpRequest",
            "accept": "application/json",
        }
        resp = await client.post(
            sso.IOP_OTP_VERIFY_URL,
            data={"cert_no": code, "div": "scnd"},
            headers=ajax,
        )
        try:
            result = resp.json()
        except ValueError as e:
            raise RuntimeError(f"OTP 검증 응답이 JSON이 아닙니다: {e}") from e
        if result.get("returnCode") != "0000":
            raise RuntimeError(
                result.get("returnMessage") or "인증 코드가 올바르지 않습니다."
            )

        # 인증을 마친 뒤 로그인 폼을 다시 제출해야 SSO 세션이 선다.
        # 비밀번호는 폼에 이미 암호화된 채로 들어 있어 재암호화하지 않는다.
        resp = await client.post(
            sso.LOGIN_URL,
            data=pending["fields"],
            headers={
                "user-agent": sso._UA,
                "origin": sso.SSO_BASE,
                "referer": pending["referer"],
                "content-type": "application/x-www-form-urlencoded",
                "accept": "text/html",
            },
        )
        if "ssosession" not in client.cookies:
            raise RuntimeError("2차 인증은 통과했지만 SSO 세션이 서지 않았습니다.")

        # SSO 티켓을 AMS로 넘긴다 (RelayState는 상대 경로).
        forms = _login_forms(resp.text)
        if not forms:
            raise RuntimeError("AMS로 넘어가는 폼을 찾지 못했습니다.")
        resp = await client.post(
            urljoin(str(resp.url), forms[0]["action"]),
            data=_form_fields(forms[0]),
            headers={"user-agent": sso._UA},
        )

        # 티켓만으로는 부족하고, 이 경로를 밟아야 AMS 애플리케이션 세션이 선다.
        menu_id = pending.get("menu_id") or MENU_ENROLLMENT
        target = f"{AMS_BASE}?menuId={menu_id}&isPc=true"
        token = base64.b64encode(target.encode()).decode().rstrip("=")
        for url in (
            f"{AMS_BASE}/com/lgin/SsoCtr/j_login_sso.do?addParam={token}",
            f"{AMS_BASE}/?menuId={menu_id}&isPc=true",
            f"{AMS_BASE}/com/lgin/SsoCtr/initPageWork.do"
            f"?requestTimeStr={int(time.time() * 1000)}&menuId={menu_id}&isPc=true",
        ):
            await client.get(url, headers={"user-agent": sso._UA})

        established = AmsSession(
            cookies=[
                {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                for c in client.cookies.jar
                if "ams.korea" in (c.domain or "")
            ],
            created_at=time.time(),
        )

    if not await verify_session(established):
        raise RuntimeError("인증은 끝났지만 AMS 세션이 확립되지 않았습니다.")

    write_secure_json(
        AMS_SESSION_FILE,
        {"cookies": established.cookies, "created_at": established.created_at},
    )
    AMS_PENDING_FILE.unlink(missing_ok=True)
    logger.info("AMS login successful")
    return established


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


async def query_raw(session: AmsSession | None, api: AmsApi, **conditions: str) -> dict:
    """AMS 조회 API를 호출해 응답 전체(여러 DataSet)를 반환한다.

    세션 없이(``None``) 부를 수 있다. 강의계획서처럼 인증이 필요 없는
    조회가 있다.
    """
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


async def fetch_syllabus(
    course_code: str,
    year: str,
    term: str,
    section: str = "00",
    grad_dept: str = GSCIT_GRAD_DEPT,
) -> dict | None:
    """강의계획서를 조회한다. 로그인이 필요 없다.

    두 번 호출하는 이유가 있다. 평가항목과 주차별 계획은 기본정보와 다른
    API에 있고, 그 API는 개설학과 코드(``estblDeprtCd``)가 정확해야 내용을
    채워 준다. 틀리면 오류 대신 **빈 목록**이 와서 "미등록"으로 오인하기
    쉽다. 학과 코드는 기본정보 응답에 들어 있으므로 받아서 그대로 쓴다.

    과목이 개설되지 않았으면 ``None``, 개설됐지만 교수가 아직 계획서를
    작성하지 않았으면 ``evaluation``/``weekly``가 빈 목록이 된다.
    """
    cond = {
        "syy": year,
        "smtDivcd": term,
        "faclyGschDeptCd": grad_dept,
        "estblDeprtCd": grad_dept,
        "sbjtnb": course_code,
        "dvcno": section,
        "profEmpno": "",
        "regIgnoreYn": "0",
        "locale": "ko",
        "sysUseUnitDivcd": "A0136",
    }

    info = await query_raw(None, API_SYLLABUS_INFO, **cond)
    rows = info.get(API_SYLLABUS_INFO.dataset) or []
    if not rows:
        return None

    base = rows[0]
    cond["estblDeprtCd"] = base.get("estblDeprtCd") or grad_dept
    plan = await query_raw(None, API_SYLLABUS_PLAN, **cond)

    return {
        "base": base,
        "evaluation": sorted(
            plan.get("dsSles364") or [], key=lambda r: r.get("seqno") or 0
        ),
        "weekly": sorted(
            plan.get("dsSles366") or [], key=lambda r: r.get("lessnWkOdr") or 0
        ),
        "references": plan.get("dsSles373") or [],
    }
