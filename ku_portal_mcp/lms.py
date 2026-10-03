"""Canvas LMS integration via 고려대 통합 SSO.

mylms.korea.ac.kr(Canvas)에 접속한다. 2026년 전환으로 KSSO가 폐지되어
sso.korea.ac.kr 기반으로 흐름이 바뀌었다.

1. mylms.korea.ac.kr -> lms.korea.ac.kr/xn-sso/login.php (로그인 방식 선택)
2. '포털 계정 로그인' 링크(exsignon_new/sso/sso_idp_login.php)로 SSO 로그인
3. mylms/learningx/login/from_cc -- Canvas 인계 페이지
4. 페이지에 실린 RSA 개인키로 임시 비밀번호를 복호화해 Canvas 네이티브 로그인
5. 세션 쿠키로 Canvas REST API 호출

Requires: cryptography (for RSA decryption)
"""

import re
import json
import time
import logging
import base64
import mimetypes
import html as html_lib
from urllib.parse import unquote
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from . import sso
from ._storage import write_secure_json as _write_secure_json

logger = logging.getLogger(__name__)

LMS_BASE = "https://lms.korea.ac.kr"
MYLMS_BASE = "https://mylms.korea.ac.kr"

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

    @property
    def should_refresh(self) -> bool:
        """True if session is near expiry (within last 20% of TTL)."""
        elapsed = time.time() - self.created_at
        return elapsed > (LMS_SESSION_TTL * 0.8)


def _load_cached_lms_session() -> LMSSession | None:
    if not LMS_SESSION_FILE.exists():
        return None
    try:
        data = json.loads(LMS_SESSION_FILE.read_text())
        session = LMSSession(**data)
        if session.is_valid:
            return session
        logger.info("Cached LMS session expired (TTL exceeded)")
    except Exception as e:
        logger.warning(f"Failed to load cached LMS session: {e}")
    return None


def _save_lms_session(session: LMSSession) -> None:
    _write_secure_json(LMS_SESSION_FILE, asdict(session))


def _clear_lms_session() -> None:
    if LMS_SESSION_FILE.exists():
        LMS_SESSION_FILE.unlink()
    # Session cookies are gone; any cached board JWTs are tied to them and
    # would otherwise keep returning a stale token for up to _BOARD_JWT_TTL.
    _board_jwt_cache.clear()


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"user-agent": _UA},
    )


async def _sso_login(
    client: httpx.AsyncClient, user_id: str, password: str
) -> httpx.Response:
    """포털 계정 SSO로 로그인해 Canvas 인계 페이지(from_cc)까지 도달한다.

    mylms에서 시작해야 하는 이유: 로그인 방식 선택 페이지가 `cvs_lgn=true`
    컨텍스트를 담은 IdP 링크를 주고, 그 컨텍스트로 로그인해야 Canvas 인계
    페이지로 이어진다. 포털용 IdP로 로그인하면 LMS 세션만 생기고 끝난다.
    """
    resp = await client.get(f"{MYLMS_BASE}/", headers={"accept": "text/html"})
    link = BeautifulSoup(resp.text, "lxml").select_one('a[href*="sso_idp_login.php"]')
    if not link:
        raise RuntimeError(
            "LMS 로그인 페이지에서 포털 계정 로그인 링크를 찾지 못했습니다."
        )

    return await sso.login_to_service(client, link["href"], user_id, password)


async def _canvas_login(
    client: httpx.AsyncClient, iframe_html: str, iframe_url: str = ""
) -> None:
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
    pkey = serialization.load_pem_private_key(
        pkey_match.group(1).encode(), password=None
    )
    canvas_password = pkey.decrypt(
        base64.b64decode(encrypted_token.group(1)),
        padding.PKCS1v15(),
    ).decode()

    # Canvas\ub294 Rails \uc571\uc774\ub77c _csrf_token \ucfe0\ud0a4\ub97c authenticity_token\uc73c\ub85c
    # \ub418\ub3cc\ub824\ubc1b\uae38 \uc694\uad6c\ud55c\ub2e4. \ube60\ub728\ub9ac\uba74 400\uc744 \ub3cc\ub824\uc900\ub2e4.
    csrf = ""
    for cookie in client.cookies.jar:
        if cookie.name == "_csrf_token" and "mylms" in (cookie.domain or ""):
            csrf = unquote(cookie.value or "")

    resp = await client.post(
        f"{MYLMS_BASE}/login/canvas",
        data={
            "utf8": "\u2713",
            "redirect_to_ssl": "1",
            "after_login_url": "",
            "pseudonym_session[unique_id]": unique_id.group(1),
            "pseudonym_session[password]": canvas_password,
            "pseudonym_session[remember_me]": "0",
            "authenticity_token": csrf,
        },
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "origin": MYLMS_BASE,
            "accept": "text/html",
            "referer": iframe_url or f"{MYLMS_BASE}/login",
            "x-csrf-token": csrf,
        },
    )

    if resp.status_code not in (200, 302):
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


async def verify_lms_session(session: LMSSession) -> bool:
    """Verify that an LMS session is still valid on the server side."""
    try:
        async with _api_client(session) as client:
            resp = await client.get("/api/v1/users/self")
            return resp.status_code == 200
    except Exception:
        return False


async def lms_login(user_id: str, password: str) -> LMSSession:
    """전체 LMS 로그인: 통합 SSO → Canvas 인계 → Canvas API 접근.

    Canvas API 호출에 쓸 쿠키를 담은 LMSSession을 반환한다.
    """
    if not user_id or not password:
        raise RuntimeError(
            "KU_PORTAL_ID / KU_PORTAL_PW 환경변수가 설정되지 않았습니다. "
            "~/.claude/settings.json의 mcpServers.ku-portal.env를 확인하세요."
        )

    cached = _load_cached_lms_session()
    if cached:
        if not cached.should_refresh:
            logger.info("Using cached LMS session")
            return cached
        # Near expiry — verify server-side before reusing
        if await verify_lms_session(cached):
            logger.info("LMS session near expiry but still valid on server, reusing")
            return cached
        logger.info("LMS session near expiry and invalid on server, re-logging in")

    async with _make_client() as client:
        # 통합 SSO 로그인 → Canvas 인계 페이지(from_cc)
        resp = await _sso_login(client, user_id, password)
        handoff_html, handoff_url = resp.text, str(resp.url)

        if "loginCryption" not in handoff_html:
            raise RuntimeError(
                "Canvas 인계 페이지에 도달하지 못했습니다 "
                f"(위치: {handoff_url}). LMS 로그인 절차가 변경되었을 수 있습니다."
            )

        # 페이지에 실린 RSA 개인키로 임시 비밀번호를 풀어 Canvas 네이티브 로그인
        await _canvas_login(client, handoff_html, handoff_url)

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
        user_id=str(user_data.get("login_id") or user_id),
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


# ---- LearningX Board (LTI tool id=5 "게시판") ---------------------------
# Board posts live in a separate SPA backed by a JWT issued after an LTI
# 1.1 launch. JWTs are short-lived (~2h) and tied to (user, course), so we
# cache them per course_id in-process to avoid re-launching for every call.

_BOARD_API_BASE = f"{MYLMS_BASE}/learningx/api/v1/learningx_board"
_BOARD_JWT_TTL = 90 * 60  # 90 minutes — tool JWT exp is ~2h, leave margin
_board_jwt_cache: dict[int, tuple[str, float]] = {}


async def _fetch_board_jwt(session: LMSSession, course_id: int) -> str:
    """Launch LTI 'board' tool (id=5) and return the xn_api_token JWT.

    The board SPA authenticates all its XHR calls with this JWT.
    """
    cached = _board_jwt_cache.get(course_id)
    if cached and (time.time() - cached[1]) < _BOARD_JWT_TTL:
        return cached[0]

    cookie_str = "; ".join(f"{k}={v}" for k, v in session.cookies.items())

    # Step 1: Canvas returns a sessionless_launch URL for tool id=5
    async with _api_client(session) as client:
        resp = await client.get(
            f"/api/v1/courses/{course_id}/external_tools/sessionless_launch",
            params={"id": "5", "launch_type": "course_navigation"},
        )
        resp.raise_for_status()
        launch_url = resp.json()["url"]

    # Step 2: GET launch_url -> Canvas wrapper page with OAuth-signed LTI form
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"user-agent": _UA, "cookie": cookie_str},
        follow_redirects=False,
    ) as client:
        resp = await client.get(launch_url)
        resp.raise_for_status()
        form_match = re.search(
            r'<form[^>]*id=["\']tool_form["\'][^>]*>(.*?)</form>',
            resp.text,
            re.DOTALL,
        )
        if not form_match:
            raise RuntimeError("LTI tool_form not found in launch page")
        form_html = form_match.group(0)
        action = html_lib.unescape(
            re.search(r'action=["\']([^"\']+)["\']', form_html).group(1)
        )
        inputs = re.findall(
            r'<input[^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
            form_html,
        )
        form_data = {name: html_lib.unescape(val) for name, val in inputs}

        # Step 3: POST signed form to LearningX Board endpoint -> Set-Cookie: xn_api_token
        resp = await client.post(action, data=form_data)
        resp.raise_for_status()
        set_cookie = resp.headers.get("set-cookie", "")
        jwt_match = re.search(r"xn_api_token=([^;]+)", set_cookie)
        if not jwt_match:
            raise RuntimeError("xn_api_token not found in LTI launch response")
        jwt = jwt_match.group(1)

    _board_jwt_cache[course_id] = (jwt, time.time())
    return jwt


def _board_client(jwt: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=30.0,
        headers={
            "user-agent": _UA,
            "accept": "application/json",
            "cookie": f"xn_api_token={jwt}",
            "authorization": f"Bearer {jwt}",
        },
    )


async def fetch_lms_boards(session: LMSSession, course_id: int) -> list[dict]:
    """List boards (Q&A 게시판, 강의자료실 등) for a course."""
    jwt = await _fetch_board_jwt(session, course_id)
    async with _board_client(jwt) as client:
        resp = await client.get(f"{_BOARD_API_BASE}/courses/{course_id}/boards")
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_board_posts(
    session: LMSSession,
    course_id: int,
    board_id: int,
    page: int = 1,
    keyword: str = "",
) -> dict:
    """List posts in a board. Returns {items, total, ...}."""
    jwt = await _fetch_board_jwt(session, course_id)
    async with _board_client(jwt) as client:
        resp = await client.get(
            f"{_BOARD_API_BASE}/courses/{course_id}/boards/{board_id}/posts",
            params={"page": str(page), "filter": "title", "keyword": keyword},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_board_post(
    session: LMSSession, course_id: int, board_id: int, post_id: int
) -> dict:
    """Fetch single post detail with attachments (includes canvas_file_id)."""
    jwt = await _fetch_board_jwt(session, course_id)
    async with _board_client(jwt) as client:
        resp = await client.get(
            f"{_BOARD_API_BASE}/courses/{course_id}/boards/{board_id}/posts/{post_id}"
        )
        resp.raise_for_status()
        return resp.json()


# ---- Canvas native endpoints ------------------------------------------


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
    session: LMSSession,
    course_id: int,
    upcoming_only: bool = False,
) -> list[dict]:
    """Fetch assignments for a course (includes the user's own submission)."""
    async with _api_client(session) as client:
        params: list[tuple[str, str]] = [
            ("per_page", "100"),
            ("order_by", "due_at"),
            ("include[]", "submission"),
        ]
        if upcoming_only:
            params.append(("bucket", "upcoming"))
        resp = await client.get(
            f"/api/v1/courses/{course_id}/assignments",
            params=params,  # type: ignore[arg-type]
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_modules(
    session: LMSSession,
    course_id: int,
    include_items: bool = True,
) -> list[dict]:
    """Fetch modules (weekly content) for a course."""
    async with _api_client(session) as client:
        params = {"per_page": "100"}
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
    session: LMSSession,
    course_ids: list[int],
) -> list[dict]:
    """Fetch announcements for specified courses."""
    async with _api_client(session) as client:
        # NOTE: Canvas /announcements windows to ~14 days. Passing start_date
        # without end_date makes it window to start_date+14d (dropping recent
        # posts), so we leave the range default = most recent announcements.
        params: list[tuple[str, str]] = [("per_page", "100")]
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


async def fetch_lms_grades(
    session: LMSSession,
    course_id: int,
) -> list[dict]:
    """Fetch enrollment grades for a course.

    Returns enrollment data including current/final scores and grades.
    """
    async with _api_client(session) as client:
        params: list[tuple[str, str]] = [
            ("user_id", "self"),
            ("include[]", "grades"),
            ("include[]", "current_grading_period_scores"),
        ]
        resp = await client.get(
            f"/api/v1/courses/{course_id}/enrollments",
            params=params,  # type: ignore[arg-type]
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_submissions(
    session: LMSSession,
    course_id: int,
) -> list[dict]:
    """Fetch all assignment submissions for the current user in a course.

    Returns submission status, score, grade, and workflow state.
    """
    async with _api_client(session) as client:
        params: list[tuple[str, str]] = [
            ("student_ids[]", "self"),
            ("per_page", "100"),
            ("include[]", "assignment"),
            ("include[]", "submission_comments"),
        ]
        resp = await client.get(
            f"/api/v1/courses/{course_id}/students/submissions",
            params=params,  # type: ignore[arg-type]
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_quizzes(
    session: LMSSession,
    course_id: int,
) -> list[dict]:
    """Fetch quizzes for a course.

    Returns quiz list with due dates, time limits, and question counts.
    Returns empty list if quizzes feature is not enabled (New Quizzes).
    """
    async with _api_client(session) as client:
        # Classic Quizzes API
        resp = await client.get(
            f"/api/v1/courses/{course_id}/quizzes",
            params={"per_page": "100"},
        )
        if resp.status_code == 404:
            # Quizzes not enabled or using New Quizzes (quiz_next)
            # Try assignments with quiz type as fallback
            resp2 = await client.get(
                f"/api/v1/courses/{course_id}/assignments",
                params={"per_page": "100"},
            )
            if resp2.status_code == 200:
                assignments = resp2.json()
                return [
                    a
                    for a in assignments
                    if a.get("is_quiz_assignment")
                    or "quizzes.next" in (a.get("html_url") or "")
                    or a.get("submission_types") == ["external_tool"]
                ]
            return []
        resp.raise_for_status()
        return resp.json()


async def fetch_lms_file_info(session: LMSSession, file_id: int) -> dict:
    """Fetch Canvas file metadata (filename, url, size, content-type)."""
    async with _api_client(session) as client:
        resp = await client.get(f"/api/v1/files/{file_id}")
        resp.raise_for_status()
        return resp.json()


def _sanitize_filename(name: str) -> str:
    """Remove path separators and null bytes from filename."""
    name = name.replace("\x00", "").replace("/", "_").replace("\\", "_")
    # Strip leading dots to prevent hidden file / traversal
    name = name.lstrip(".")
    return name or "unnamed"


async def download_lms_file(
    session: LMSSession,
    file_id: int,
    save_dir: Path,
    filename: str | None = None,
) -> dict:
    """Download a Canvas file to save_dir.

    Streams content chunk-by-chunk to handle large files efficiently.
    Returns dict with path, size, content_type, filename.
    """
    info = await fetch_lms_file_info(session, file_id)
    download_url = info.get("url")
    if not download_url:
        raise RuntimeError(
            f"파일 다운로드 URL을 가져올 수 없습니다 (file_id={file_id})"
        )

    actual_name = _sanitize_filename(
        filename or info.get("display_name") or f"file_{file_id}"
    )
    save_dir.mkdir(parents=True, exist_ok=True)

    # Avoid overwriting existing files
    target = save_dir / actual_name
    if target.exists():
        stem, suffix = target.stem, target.suffix
        i = 1
        while (save_dir / f"{stem}_{i}{suffix}").exists():
            i += 1
        target = save_dir / f"{stem}_{i}{suffix}"

    # Canvas /files/:id/download redirects to a pre-signed S3 URL; both legs
    # may need the session cookie (Canvas gates the redirect).
    cookie_str = "; ".join(f"{k}={v}" for k, v in session.cookies.items())
    total = 0
    async with httpx.AsyncClient(
        timeout=300.0,
        headers={"user-agent": _UA, "cookie": cookie_str},
        follow_redirects=True,
    ) as client:
        async with client.stream("GET", download_url) as resp:
            resp.raise_for_status()
            with target.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    total += len(chunk)

    return {
        "path": str(target),
        "filename": target.name,
        "size": total,
        "content_type": info.get("content-type") or info.get("content_type"),
    }


# ---- Assignment submission ------------------------------------------------
# Canvas 3-step file upload for online_upload assignments:
#   1. POST .../submissions/self/files  -> upload slot (upload_url + params)
#   2. POST the file to upload_url      -> file id
#   3. POST .../submissions             -> actually submits (irreversible-ish)
# Only step 3 changes the grade-relevant state, so the server tool keeps a
# dry-run default and requires an explicit confirm flag.

# Used only when the assignment does not declare allowed_extensions.
_DEFAULT_SUBMIT_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "hwp",
    "hwpx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "txt",
    "zip",
    "png",
    "jpg",
    "jpeg",
    "py",
    "ipynb",
    "md",
}


def _csrf_headers(session: LMSSession) -> dict[str, str]:
    """Canvas rejects cookie-authenticated writes without X-CSRF-Token."""
    token = session.cookies.get("_csrf_token")
    if not token:
        raise RuntimeError("LMS 세션에 _csrf_token 쿠키가 없습니다. 다시 로그인하세요.")
    return {"x-csrf-token": unquote(token)}


async def fetch_lms_assignment(
    session: LMSSession, course_id: int, assignment_id: int
) -> dict:
    """Fetch one assignment including the user's own submission."""
    async with _api_client(session) as client:
        resp = await client.get(
            f"/api/v1/courses/{course_id}/assignments/{assignment_id}",
            params=[("include[]", "submission")],
        )
        resp.raise_for_status()
        return resp.json()


def _parse_canvas_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_submission_plan(
    assignment: dict,
    file_path: Path,
    now: datetime | None = None,
) -> dict:
    """Decide whether file_path may be submitted to assignment (no network).

    Returns {"ok": bool, "problems": [...], "warnings": [...]}. Problems block
    the submission; warnings (e.g. past due) are shown but do not.
    """
    now = now or datetime.now(timezone.utc)
    problems: list[str] = []
    warnings: list[str] = []

    types = assignment.get("submission_types") or []
    if "online_upload" not in types:
        problems.append(
            f"파일 업로드 제출이 불가능한 과제입니다 (submission_types={types})"
        )

    unlock_at = _parse_canvas_time(assignment.get("unlock_at"))
    lock_at = _parse_canvas_time(assignment.get("lock_at"))
    due_at = _parse_canvas_time(assignment.get("due_at"))
    if unlock_at and now < unlock_at:
        problems.append(
            f"아직 열리지 않은 과제입니다 (unlock_at={assignment.get('unlock_at')})"
        )
    if lock_at and now > lock_at:
        problems.append(f"제출이 잠긴 과제입니다 (lock_at={assignment.get('lock_at')})")
    if assignment.get("locked_for_user") and not problems:
        problems.append(
            f"제출이 잠긴 과제입니다 ({assignment.get('lock_explanation') or 'locked_for_user'})"
        )
    if due_at and now > due_at and not problems:
        warnings.append(
            f"마감({assignment.get('due_at')})이 지나 늦은 제출로 처리될 수 있습니다"
        )

    ext = file_path.suffix.lstrip(".").lower()
    allowed = [
        e.lstrip(".").lower() for e in (assignment.get("allowed_extensions") or [])
    ]
    if allowed:
        if ext not in allowed:
            problems.append(
                f"허용되지 않는 확장자입니다: .{ext} (허용: {', '.join(allowed)})"
            )
    elif ext not in _DEFAULT_SUBMIT_EXTENSIONS:
        problems.append(f"제출 가능한 문서 확장자가 아닙니다: .{ext}")

    attempts = assignment.get("allowed_attempts")
    sub = assignment.get("submission") or {}
    if (
        isinstance(attempts, int)
        and attempts > 0
        and (sub.get("attempt") or 0) >= attempts
    ):
        problems.append(f"제출 가능 횟수({attempts}회)를 모두 사용했습니다")
    if sub.get("workflow_state") in ("submitted", "graded", "pending_review"):
        warnings.append(
            "이미 제출된 과제입니다. 새로 제출하면 재제출(새 attempt)이 됩니다"
        )

    return {"ok": not problems, "problems": problems, "warnings": warnings}


async def submit_lms_assignment(
    session: LMSSession,
    course_id: int,
    assignment_id: int,
    file_path: Path,
) -> dict:
    """Upload file_path and submit it to the assignment (online_upload).

    This really submits. Callers must have checked check_submission_plan and
    obtained user confirmation first.
    """
    name = _sanitize_filename(file_path.name)
    size = file_path.stat().st_size
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    csrf = _csrf_headers(session)
    base = f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions"

    async with _api_client(session) as client:
        # 1. upload slot
        resp = await client.post(
            f"{base}/self/files",
            data={"name": name, "size": str(size), "content_type": content_type},
            headers=csrf,
        )
        resp.raise_for_status()
        slot = resp.json()
        upload_url = slot.get("upload_url")
        if not upload_url:
            raise RuntimeError(f"업로드 URL을 받지 못했습니다: {slot}")

        # 2. send the bytes. The upload host can be a third party (S3/InstFS),
        # so use a client WITHOUT the Canvas session cookie.
        async with httpx.AsyncClient(
            timeout=300.0, headers={"user-agent": _UA}, follow_redirects=False
        ) as up:
            with file_path.open("rb") as fh:
                up_resp = await up.post(
                    upload_url,
                    data=slot.get("upload_params") or {},
                    files={"file": (name, fh, content_type)},
                )
        if up_resp.status_code in (301, 302, 303):
            # Canvas-hosted flow: the Location is the confirmation endpoint and
            # needs the session.
            location = up_resp.headers.get("location")
            if not location:
                raise RuntimeError("업로드 확인 URL(Location)이 없습니다.")
            conf = await client.get(location)
            conf.raise_for_status()
            uploaded = conf.json()
        else:
            up_resp.raise_for_status()
            uploaded = up_resp.json()
        file_id = uploaded.get("id")
        if not file_id:
            raise RuntimeError(f"업로드된 파일 ID를 확인하지 못했습니다: {uploaded}")

        # 3. submit
        resp = await client.post(
            base,
            data={
                "submission[submission_type]": "online_upload",
                "submission[file_ids][]": [str(file_id)],
            },
            headers=csrf,
        )
        resp.raise_for_status()
        result = resp.json()

    return {
        "file_id": file_id,
        "filename": name,
        "size": size,
        "workflow_state": result.get("workflow_state"),
        "submitted_at": result.get("submitted_at"),
        "attempt": result.get("attempt"),
        "late": result.get("late"),
        "attachments": [
            {
                "id": a.get("id"),
                "filename": a.get("display_name") or a.get("filename"),
                "size": a.get("size"),
            }
            for a in (result.get("attachments") or [])
        ],
    }


async def fetch_lms_syllabus(
    session: LMSSession,
    course_id: int,
) -> dict:
    """Fetch syllabus (수업 계획서) for a course.

    Uses Canvas API to get the syllabus_body HTML content.
    """
    async with _api_client(session) as client:
        params: list[tuple[str, str]] = [
            ("include[]", "syllabus_body"),
            ("include[]", "term"),
        ]
        resp = await client.get(
            f"/api/v1/courses/{course_id}",
            params=params,  # type: ignore[arg-type]
        )
        resp.raise_for_status()
        return resp.json()
