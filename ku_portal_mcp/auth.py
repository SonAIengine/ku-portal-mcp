"""차세대 KUPID 포털 인증.

2026년 전환으로 레거시 로그인(`/common/Login.kpd` + GRW 세션)이 폐지되어
`sso.korea.ac.kr` 통합 로그인으로 대체되었다.

포털 앱 세션은 SSO 로그인만으로는 확립되지 않고, 아래 체인을 더 거쳐야 한다.

    /exsignon/sso/sso_index.jsp   → SSO 로그인 (ssosession, at 발급)
    → /index.jsp                  → JS location 이동
    → /exsignon/sso/sso_loginuser.jsp → 자동 제출 폼
    → POST /proc/Login.eps        → 포털 세션(_st) 확립, /p/ST/ 도달

세션은 쿠키 전체를 캐시해 재사용한다.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import httpx

from . import sso
from ._storage import write_secure_json as _write_secure_json

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "ku-portal-mcp"
SESSION_FILE = CACHE_DIR / "session.json"
SESSION_TTL = 30 * 60  # 30 minutes

PORTAL_BASE = "https://portal.korea.ac.kr"
PORTAL_IDP_URL = f"{PORTAL_BASE}/exsignon/sso/sso_index.jsp"
PORTAL_INDEX_URL = f"{PORTAL_BASE}/index.jsp"

# 포털 앱 세션이 확립되면 학생 포털(/p/ST/)로 이동한다.
_AUTHENTICATED_PATH = "/p/"

_BROWSER_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class Session:
    """포털 인증 세션.

    포털과 SSO가 같은 이름(JSESSIONID)의 서로 다른 쿠키를 쓰므로
    이름만으로는 구분할 수 없다. 도메인·경로까지 보존한다.
    """

    cookies: list[dict[str, str]] = field(default_factory=list)
    created_at: float = 0.0

    @property
    def is_valid(self) -> bool:
        return bool(self.cookies) and (time.time() - self.created_at) < SESSION_TTL

    @property
    def should_refresh(self) -> bool:
        """만료가 가까우면(TTL의 마지막 20%) True."""
        elapsed = time.time() - self.created_at
        return elapsed > (SESSION_TTL * 0.8)


def load_cached_session() -> Session | None:
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text())
        session = Session(
            cookies=data.get("cookies") or [], created_at=data.get("created_at", 0.0)
        )
        if session.is_valid:
            return session
        logger.info("Cached session expired")
    except Exception as e:
        logger.warning(f"Failed to load cached session: {e}")
    return None


def save_session(session: Session) -> None:
    _write_secure_json(SESSION_FILE, asdict(session))


def _dump_cookies(client: httpx.AsyncClient) -> list[dict[str, str]]:
    """클라이언트의 쿠키를 도메인·경로와 함께 직렬화한다."""
    return [
        {
            "name": c.name,
            "value": c.value or "",
            "domain": c.domain,
            "path": c.path,
        }
        for c in client.cookies.jar
    ]


def make_client(session: Session | None = None, **kwargs) -> httpx.AsyncClient:
    """세션 쿠키가 적용된 httpx 클라이언트를 만든다."""
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


async def _establish_portal_session(client: httpx.AsyncClient) -> httpx.Response:
    """SSO 로그인 후 포털 앱 세션을 확립한다."""
    resp = await client.get(PORTAL_INDEX_URL, headers=_BROWSER_HEADERS)
    return await sso.follow_auto_forms(client, resp)


async def verify_session(session: Session) -> bool:
    """포털 세션이 서버에서 아직 유효한지 확인한다."""
    try:
        async with make_client(session, timeout=15.0) as client:
            resp = await client.get(PORTAL_INDEX_URL, headers=_BROWSER_HEADERS)
            resp = await sso.follow_auto_forms(client, resp)
            return (
                _AUTHENTICATED_PATH in str(resp.url) and "ipt_password" not in resp.text
            )
    except Exception:
        return False


async def login() -> Session:
    """SSO 로그인 → 포털 앱 세션 확립. 유효한 캐시가 있으면 재사용한다."""
    cached = load_cached_session()
    if cached:
        if not cached.should_refresh:
            logger.info("Using cached session")
            return cached
        if await verify_session(cached):
            logger.info("KUPID session near expiry but still valid on server, reusing")
            return cached
        logger.info("KUPID session near expiry and invalid on server, re-logging in")

    user_id = os.environ.get("KU_PORTAL_ID")
    password = os.environ.get("KU_PORTAL_PW")
    if not user_id or not password:
        raise RuntimeError(
            "KU_PORTAL_ID / KU_PORTAL_PW 환경변수가 설정되지 않았습니다. "
            "~/.claude/settings.json의 mcpServers.ku-portal.env를 확인하세요."
        )

    async with make_client() as client:
        await sso.login_to_service(client, PORTAL_IDP_URL, user_id, password)
        resp = await _establish_portal_session(client)

        if _AUTHENTICATED_PATH not in str(resp.url):
            raise RuntimeError(
                f"포털 세션 확립에 실패했습니다 (최종 위치: {resp.url}). "
                "포털 로그인 절차가 변경되었을 수 있습니다."
            )

        cookies = _dump_cookies(client)

    session = Session(cookies=cookies, created_at=time.time())
    save_session(session)
    logger.info("Login successful, session cached")
    return session


def clear_session() -> None:
    """캐시된 세션을 삭제해 다음 호출에서 다시 로그인하게 한다."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
