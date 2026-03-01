"""KUPID portal authentication module.

Handles login flow, SSO token acquisition, and session caching.
Based on the kukit library (https://github.com/DevKor-github/kukit).
"""

import json
import os
import re
import time
import logging
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "ku-portal-mcp"
SESSION_FILE = CACHE_DIR / "session.json"
SESSION_TTL = 30 * 60  # 30 minutes

PORTAL_BASE = "https://portal.korea.ac.kr"
GRW_BASE = "https://grw.korea.ac.kr"
INFODEPOT_BASE = "https://infodepot.korea.ac.kr"
LIBRSV_BASE = "https://librsv.korea.ac.kr"

INTRO_URL = f"{PORTAL_BASE}/front/Intro.kpd"
LOGIN_URL = f"{PORTAL_BASE}/common/Login.kpd"

# Delimiters to extract dynamic form fields from login page
FIRST_DELIMITER = '<input type="password" name="pw" id="_pw" value="" />'
SECOND_DELIMITER = '<input type="hidden" name="direct_div"/>'

# Browser-like headers required for KUPID portal
_BROWSER_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class Session:
    ssotoken: str
    portal_session_id: str
    grw_session_id: str
    created_at: float

    @property
    def is_valid(self) -> bool:
        return (time.time() - self.created_at) < SESSION_TTL


def load_cached_session() -> Session | None:
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text())
        session = Session(**data)
        if session.is_valid:
            return session
        logger.info("Cached session expired")
    except Exception as e:
        logger.warning(f"Failed to load cached session: {e}")
    return None


def save_session(session: Session) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(asdict(session)))


def _extract_cookie(response: httpx.Response, name: str) -> str | None:
    for key, value in response.headers.multi_items():
        if key.lower() == "set-cookie" and value.startswith(f"{name}="):
            cookie_val = value.split(";")[0].split("=", 1)[1]
            return cookie_val
    return None


async def _get_login_fields(client: httpx.AsyncClient) -> dict:
    """Fetch login page and extract dynamic form field names + CSRF token."""
    resp = await client.get(
        INTRO_URL,
        headers={**_BROWSER_HEADERS, "referer": f"{PORTAL_BASE}/"},
    )
    resp.raise_for_status()
    text = resp.text

    # PORTAL_SESSIONID is now in client.cookies (auto-managed)
    portal_session_id = str(client.cookies.get("PORTAL_SESSIONID", ""))
    if not portal_session_id:
        raise RuntimeError("Failed to get PORTAL_SESSIONID cookie")

    # Split HTML to find dynamic fields between the two delimiters
    parts = text.split(FIRST_DELIMITER)
    if len(parts) < 2:
        raise RuntimeError("Failed to find first delimiter in login page")
    after_pw = parts[1]

    parts2 = after_pw.split(SECOND_DELIMITER)
    if len(parts2) < 2:
        raise RuntimeError("Failed to find second delimiter in login page")
    between = parts2[0]

    # Extract the 4 dynamic hidden fields
    lines = [line.strip() for line in between.split("\n") if line.strip()]
    if len(lines) != 4:
        raise RuntimeError(f"Expected 4 dynamic fields, got {len(lines)}: {lines}")

    id_elem, pw_elem, csrf_elem, fake_elem = lines

    id_key = re.search(r'name="(\w+)"', id_elem)
    pw_key = re.search(r'name="(\w+)"', pw_elem)
    csrf_val = re.search(r'value="(.+)"', csrf_elem)
    fake_val = re.search(r'value="(\w+)"', fake_elem)

    if not all([id_key, pw_key, csrf_val, fake_val]):
        raise RuntimeError("Failed to parse dynamic form fields")

    fake_key_match = re.search(r'name="(\w+)"', fake_elem)
    if not fake_key_match:
        raise RuntimeError("Failed to parse fake field name")

    return {
        "id_key": id_key.group(1),  # type: ignore[union-attr]
        "pw_key": pw_key.group(1),  # type: ignore[union-attr]
        "csrf": csrf_val.group(1),  # type: ignore[union-attr]
        "fake_key": fake_key_match.group(1),
        "fake_val": fake_val.group(1),  # type: ignore[union-attr]
        "portal_session_id": portal_session_id,
    }


async def _do_login(client: httpx.AsyncClient, user_id: str, password: str, fields: dict) -> str:
    """Submit login form and extract ssotoken.

    Uses httpx auto cookie management — cookies from the GET login page
    (WMONID, PORTAL_SESSIONID) are automatically sent with the POST.
    """
    form_data = {
        fields["id_key"]: user_id,
        fields["pw_key"]: password,
        "_csrf": fields["csrf"],
        fields["fake_key"]: fields["fake_val"],
        "direct_div": "",
        "pw_pass": "",
        "browser": "chrome",
    }

    resp = await client.post(
        LOGIN_URL,
        data=form_data,
        headers={
            **_BROWSER_HEADERS,
            "referer": INTRO_URL,
            "origin": PORTAL_BASE,
            "content-type": "application/x-www-form-urlencoded",
        },
        follow_redirects=False,
    )

    if resp.status_code != 302:
        raise RuntimeError(f"Login failed with status {resp.status_code}")

    ssotoken = str(client.cookies.get("ssotoken", ""))
    if not ssotoken:
        ssotoken = _extract_cookie(resp, "ssotoken") or ""
    if not ssotoken:
        raise RuntimeError("Failed to extract ssotoken from login response")

    return ssotoken


async def _get_grw_session(
    client: httpx.AsyncClient, token: str, portal_session_id: str
) -> str:
    """Access GRW to obtain GRW_SESSIONID.

    GRW is a separate domain, so we must manually set cookies
    (httpx auto cookies are per-domain).
    """
    url = (
        f"{GRW_BASE}/GroupWare/user/NoticeList.jsp"
        f"?kind=11&compId=148&menuCd=340&language=ko"
        f"&frame=&token={token}&orgtoken={token}"
    )
    cookie_str = f"ssotoken={token}; PORTAL_SESSIONID={portal_session_id};"

    resp = await client.get(
        url,
        headers={
            "referer": f"{PORTAL_BASE}/",
            "cookie": cookie_str,
        },
    )
    resp.raise_for_status()

    grw_session_id = _extract_cookie(resp, "GRW_SESSIONID")
    if not grw_session_id:
        raise RuntimeError("Failed to get GRW_SESSIONID")

    return grw_session_id


async def login() -> Session:
    """Full login flow: credentials -> ssotoken -> GRW session.

    Uses cached session if still valid. Credentials from environment variables.
    """
    cached = load_cached_session()
    if cached:
        logger.info("Using cached session")
        return cached

    user_id = os.environ.get("KU_PORTAL_ID")
    password = os.environ.get("KU_PORTAL_PW")
    if not user_id or not password:
        raise RuntimeError(
            "KU_PORTAL_ID and KU_PORTAL_PW environment variables are required"
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        fields = await _get_login_fields(client)
        ssotoken = await _do_login(client, user_id, password, fields)
        grw_session_id = await _get_grw_session(
            client, ssotoken, fields["portal_session_id"]
        )

    session = Session(
        ssotoken=ssotoken,
        portal_session_id=fields["portal_session_id"],
        grw_session_id=grw_session_id,
        created_at=time.time(),
    )
    save_session(session)
    logger.info("Login successful, session cached")
    return session


def clear_session() -> None:
    """Remove cached session to force re-login."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
