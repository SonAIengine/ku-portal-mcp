"""Canvas LMS integration via KSSO SAML SSO.

Accesses mylms.korea.ac.kr (Canvas LMS) through Korea University's
KSSO single sign-on system. The flow is:

1. lms.korea.ac.kr/exsignon -> ksso.korea.ac.kr (SAML IdP)
2. KSSO login (UserTypeCheck -> OTPCheck -> Login.do)
3. SAML redirect chain -> Canvas session establishment
4. RSA-decrypted password -> Canvas native login
5. Canvas REST API access via session cookies

Requires: cryptography (for RSA decryption)
"""

import re
import json
import time
import logging
import base64
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

LMS_BASE = "https://lms.korea.ac.kr"
MYLMS_BASE = "https://mylms.korea.ac.kr"
KSSO_BASE = "https://ksso.korea.ac.kr"

CACHE_DIR = Path.home() / ".cache" / "ku-portal-mcp"
LMS_SESSION_FILE = CACHE_DIR / "lms_session.json"
LMS_SESSION_TTL = 25 * 60  # 25 minutes (conservative)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class LMSSession:
    cookies: dict[str, str]
    user_id: str
    user_name: str
    canvas_user_id: int
    created_at: float

    @property
    def is_valid(self) -> bool:
        return (time.time() - self.created_at) < LMS_SESSION_TTL


def _load_cached_lms_session() -> LMSSession | None:
    if not LMS_SESSION_FILE.exists():
        return None
    try:
        data = json.loads(LMS_SESSION_FILE.read_text())
        session = LMSSession(**data)
        if session.is_valid:
            return session
    except Exception as e:
        logger.warning(f"Failed to load cached LMS session: {e}")
    return None


def _save_lms_session(session: LMSSession) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LMS_SESSION_FILE.write_text(json.dumps(asdict(session)))


def _clear_lms_session() -> None:
    if LMS_SESSION_FILE.exists():
        LMS_SESSION_FILE.unlink()


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=False,
        headers={"user-agent": _UA},
    )


async def _ksso_login(client: httpx.AsyncClient, user_id: str, password: str) -> tuple[str, str]:
    """Perform KSSO SAML login and return (redirect_url, emp_no)."""
    # Step 1: Get KSSO login page via exsignon
    resp = await client.get(
        f"{LMS_BASE}/exsignon/sso/sso_idp_login.php",
        params={"RelayState": f"{LMS_BASE}/xn-sso/gw-cb.php"},
        headers={"accept": "text/html"},
    )
    if resp.status_code != 302:
        raise RuntimeError(f"exsignon redirect failed: {resp.status_code}")
    ksso_url = resp.headers["location"]

    # Step 2: Load login form (get JSESSIONID + CSRF tokens)
    resp = await client.get(
        ksso_url,
        headers={"accept": "text/html", "referer": f"{LMS_BASE}/"},
    )
    html = resp.text
    l_token = re.search(r'name=["\']l_token["\'][^>]*value=["\']([^"\']*)["\']', html)
    c_token = re.search(r'name=["\']c_token["\'][^>]*value=["\']([^"\']*)["\']', html)
    if not l_token or not c_token:
        raise RuntimeError("Failed to extract KSSO CSRF tokens")

    ajax_headers = {
        "referer": ksso_url,
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "accept": "application/json",
        "origin": KSSO_BASE,
    }

    # Step 3: UserTypeCheck
    resp = await client.post(
        f"{KSSO_BASE}/logincheck/UserTypeCheck.do",
        data={
            "l_token": l_token.group(1),
            "user_timezone_offset": "-540",
            "c_token": c_token.group(1),
            "user_id": "",
            "one_id": user_id,
            "user_password": password,
        },
        headers=ajax_headers,
    )
    data = resp.json()
    if data.get("result") != "success":
        raise RuntimeError(f"KSSO UserTypeCheck failed: {data}")
    emp_no = data["types"][0]["user_id"]
    new_c_token = data.get("c_token", c_token.group(1))

    # Step 4: OTP Check
    resp = await client.post(
        f"{KSSO_BASE}/logincheck/OTPCheck.do",
        data={"type": "NeedOTPCheck", "emp_no": emp_no},
        headers=ajax_headers,
    )
    otp_result = resp.json().get("result")
    if otp_result != "false":
        raise RuntimeError(f"OTP required ({otp_result}), not supported in MCP")

    # Step 5: Login.do
    resp = await client.post(
        f"{KSSO_BASE}/Login.do",
        data={
            "l_token": l_token.group(1),
            "user_timezone_offset": "-540",
            "c_token": new_c_token,
            "user_id": emp_no,
            "one_id": user_id,
            "user_password": password,
        },
        headers={
            "referer": ksso_url,
            "content-type": "application/x-www-form-urlencoded",
            "origin": KSSO_BASE,
        },
    )
    if resp.status_code != 302:
        raise RuntimeError(f"KSSO Login.do failed: {resp.status_code}")

    return resp.headers["location"], emp_no


async def _follow_saml_redirects(client: httpx.AsyncClient, url: str) -> str:
    """Follow the SAML redirect chain until we hit the callback page with iframe."""
    while url:
        resp = await client.get(url, headers={"accept": "text/html"})
        if resp.status_code == 200:
            return resp.text
        url = resp.headers.get("location", "")
    raise RuntimeError("SAML redirect chain ended without callback page")


async def _canvas_login(client: httpx.AsyncClient, iframe_html: str, iframe_url: str = "") -> None:
    """Decrypt Canvas password from iframe and submit Canvas login form."""
    encrypted_token = re.search(r'loginCryption\("([^"]+)"', iframe_html)
    pkey_match = re.search(
        r"(-----BEGIN RSA PRIVATE KEY-----.*?-----END RSA PRIVATE KEY-----)",
        iframe_html,
        re.DOTALL,
    )
    unique_id = re.search(
        r'pseudonym_session\[unique_id\]["\'][^>]*value=["\']([^"\']+)',
        iframe_html,
    )

    if not encrypted_token or not pkey_match or not unique_id:
        raise RuntimeError("Failed to extract Canvas login parameters from iframe")

    # RSA decrypt the Canvas password
    pkey = serialization.load_pem_private_key(pkey_match.group(1).encode(), password=None)
    canvas_password = pkey.decrypt(
        base64.b64decode(encrypted_token.group(1)),
        padding.PKCS1v15(),
    ).decode()

    # Submit Canvas login
    resp = await client.post(
        f"{MYLMS_BASE}/login/canvas",
        data={
            "utf8": "\u2713",
            "redirect_to_ssl": "1",
            "after_login_url": "",
            "pseudonym_session[unique_id]": unique_id.group(1),
            "pseudonym_session[password]": canvas_password,
            "pseudonym_session[remember_me]": "0",
        },
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "origin": MYLMS_BASE,
            "accept": "text/html",
            "referer": iframe_url or f"{MYLMS_BASE}/login",
        },
    )

    if resp.status_code == 302:
        # Follow the success redirect
        await client.get(
            resp.headers["location"],
            headers={"accept": "text/html"},
        )
    elif resp.status_code != 200:
        raise RuntimeError(f"Canvas login failed: {resp.status_code}")


def _extract_cookies(client: httpx.AsyncClient) -> dict[str, str]:
    """Extract relevant cookies from the client's cookie jar."""
    cookies = {}
    jar = client.cookies.jar
    # Use public interface: iterate over all cookies
    for cookie in jar:
        if cookie.domain and "mylms.korea.ac.kr" in cookie.domain:
            cookies[cookie.name] = cookie.value or ""
    return cookies


async def lms_login(user_id: str, password: str) -> LMSSession:
    """Full LMS login: KSSO -> SAML -> Canvas -> API access.

    Returns an LMSSession with cookies for Canvas API calls.
    """
    cached = _load_cached_lms_session()
    if cached:
        logger.info("Using cached LMS session")
        return cached

    async with _make_client() as client:
        # KSSO login
        redirect_url, emp_no = await _ksso_login(client, user_id, password)

        # Follow SAML redirects to callback page
        callback_html = await _follow_saml_redirects(client, redirect_url)

        # Extract iframe URL and load it
        iframe_src = re.search(r'iframe\.src="([^"]+)"', callback_html)
        if not iframe_src:
            raise RuntimeError("No iframe found in callback page")

        iframe_url = iframe_src.group(1)
        resp = await client.get(
            iframe_url,
            headers={"accept": "text/html", "referer": f"{LMS_BASE}/"},
        )
        iframe_html = resp.text

        # Canvas login with RSA decryption
        await _canvas_login(client, iframe_html, iframe_url)

        # Extract cookies
        cookies = _extract_cookies(client)

        # Verify: get user info
        resp = await client.get(
            f"{MYLMS_BASE}/api/v1/users/self",
            headers={"accept": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Canvas API verification failed: {resp.status_code}")

        user_data = resp.json()

    session = LMSSession(
        cookies=cookies,
        user_id=emp_no,
        user_name=user_data.get("name", ""),
        canvas_user_id=user_data.get("id", 0),
        created_at=time.time(),
    )
    _save_lms_session(session)
    logger.info(f"LMS login successful: {session.user_name}")
    return session


def _api_client(session: LMSSession) -> httpx.AsyncClient:
    """Create an httpx client configured for Canvas API calls."""
    cookie_str = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    return httpx.AsyncClient(
        timeout=30.0,
        base_url=MYLMS_BASE,
        headers={
            "user-agent": _UA,
            "accept": "application/json",
            "cookie": cookie_str,
        },
    )


async def fetch_lms_courses(session: LMSSession) -> list[dict]:
    """Fetch enrolled courses from Canvas LMS."""
    async with _api_client(session) as client:
        resp = await client.get(
            "/api/v1/courses",
            params={"per_page": "100", "include[]": "term"},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_assignments(
    session: LMSSession, course_id: int, upcoming_only: bool = False,
) -> list[dict]:
    """Fetch assignments for a course."""
    async with _api_client(session) as client:
        params = {"per_page": "50", "order_by": "due_at"}
        if upcoming_only:
            params["bucket"] = "upcoming"
        resp = await client.get(
            f"/api/v1/courses/{course_id}/assignments",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_modules(
    session: LMSSession, course_id: int, include_items: bool = True,
) -> list[dict]:
    """Fetch modules (weekly content) for a course."""
    async with _api_client(session) as client:
        params = {"per_page": "50"}
        if include_items:
            params["include[]"] = "items"
        resp = await client.get(
            f"/api/v1/courses/{course_id}/modules",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_todo(session: LMSSession) -> list[dict]:
    """Fetch user's todo items (upcoming assignments/quizzes)."""
    async with _api_client(session) as client:
        resp = await client.get("/api/v1/users/self/todo")
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_upcoming_events(session: LMSSession) -> list[dict]:
    """Fetch upcoming calendar events."""
    async with _api_client(session) as client:
        resp = await client.get("/api/v1/users/self/upcoming_events")
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_dashboard(session: LMSSession) -> list[dict]:
    """Fetch dashboard cards (active courses)."""
    async with _api_client(session) as client:
        resp = await client.get("/api/v1/dashboard/dashboard_cards")
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_announcements(
    session: LMSSession, course_ids: list[int],
) -> list[dict]:
    """Fetch announcements for specified courses."""
    async with _api_client(session) as client:
        params: list[tuple[str, str]] = [("per_page", "30")]
        for cid in course_ids:
            params.append(("context_codes[]", f"course_{cid}"))
        resp = await client.get(
            "/api/v1/announcements",
            params=params,  # type: ignore[arg-type]
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json()
