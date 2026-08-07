"""고려대 통합 로그인(sso.korea.ac.kr) 클라이언트.

2026년 차세대 전환으로 기존 KSSO(ksso.korea.ac.kr, `*.do`)가 서비스를 종료하고
`sso.korea.ac.kr`의 `*.eps` 엔드포인트로 이전되었다. 새 로그인 폼은 비밀번호를
브라우저에서 AES-128-CBC로 암호화해 전송한다.

    user_password = base64(AES-CBC(key, iv, "<password>|<salt>")) + "|" + base64(iv)

salt와 폼의 `l_token`은 **로그인 페이지를 받을 때마다 서버가 새로 발급하는 값**이라
반드시 같은 세션(JSESSIONID)에서 받은 페이지의 값을 그대로 되돌려줘야 한다.
AES 키도 페이지에서 파싱해 학교가 값을 교체해도 따라가도록 했다.

2026-07-20부터 학사·행정·LMS 등에 2차 보안인증(OTP/푸시)이 적용되어, 로그인
응답이 추가 인증을 요구할 수 있다. 관련 엔드포인트는 IOP_* 상수 참고.
"""

import base64
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)

SSO_BASE = "https://sso.korea.ac.kr"

AUTH_URL = f"{SSO_BASE}/svc/tk/Auth.eps"
LOGIN_URL = f"{SSO_BASE}/Login.eps"
USER_ID_CHK_URL = f"{SSO_BASE}/korea/UserIdChk.eps"

# 2차 보안인증(IOP) 엔드포인트
IOP_USER_STATUS_URL = f"{SSO_BASE}/korea/auth/IOPUserStatusChk.eps"
IOP_PUSH_AUTH_URL = f"{SSO_BASE}/korea/auth/IOPPushAuth.eps"
IOP_AUTH_CHK_URL = f"{SSO_BASE}/korea/auth/IOPAuthChk.eps"
IOP_OTP_REQ_URL = f"{SSO_BASE}/korea/auth/IOPOtpReq.eps"
IOP_OTP_VERIFY_URL = f"{SSO_BASE}/korea/auth/IOPOtpVerify.eps"

# SSO 서비스 ID (Auth.eps의 id 파라미터)
SERVICE_PORTAL = "portal"
SERVICE_LMS = "lms"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_KEY_PATTERN = re.compile(r'CryptoJS\.enc\.Base64\.parse\(\s*"([^"]+)"\s*\)')
_SALT_PATTERN = re.compile(r'ipt_password"\)\.val\(\)\s*\+\s*"\|([^"]+)"')
# `window.location = "..."` 와 `location.href = "..."` 를 모두 잡는다.
_JS_LOCATION_PATTERN = re.compile(
    r'(?:window\.)?location(?:\.href)?\s*=\s*["\']([^"\']+)["\']'
)
_SUBMIT_CALL_PATTERN = re.compile(r"\.submit\s*\(\s*\)")


@dataclass
class LoginPage:
    """로그인 폼 페이지에서 추출한 세션별 파라미터.

    salt와 l_token은 이 페이지를 발급한 세션에만 유효하다.
    """

    aes_key: bytes
    salt: str
    l_token: str
    url: str


def _pkcs7_pad(data: bytes) -> bytes:
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    return padder.update(data) + padder.finalize()


def encrypt_password(password: str, page: LoginPage, iv: bytes | None = None) -> str:
    """로그인 폼과 동일한 방식으로 비밀번호를 암호화한다.

    CryptoJS의 `AES.encrypt(text, key, {iv, CBC, Pkcs7})`와 호환된다.
    """
    if iv is None:
        iv = os.urandom(16)

    plaintext = f"{password}|{page.salt}".encode()
    encryptor = Cipher(algorithms.AES(page.aes_key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(_pkcs7_pad(plaintext)) + encryptor.finalize()

    return base64.b64encode(ciphertext).decode() + "|" + base64.b64encode(iv).decode()


def parse_login_page(html: str, url: str) -> LoginPage:
    """로그인 페이지에서 AES 키, salt, l_token을 추출한다."""
    key_match = _KEY_PATTERN.search(html)
    if not key_match:
        raise RuntimeError(
            "로그인 페이지에서 AES 키를 찾지 못했습니다. 학교가 로그인 방식을 변경했을 수 있습니다."
        )

    salt_match = _SALT_PATTERN.search(html)
    if not salt_match:
        raise RuntimeError(
            "로그인 페이지에서 비밀번호 salt를 찾지 못했습니다. 학교가 로그인 방식을 변경했을 수 있습니다."
        )

    # l_token의 value는 개행을 포함할 수 있어 BeautifulSoup으로 읽는다.
    soup = BeautifulSoup(html, "lxml")
    token_input = soup.find("input", {"name": "l_token"})
    if not token_input or not token_input.get("value"):
        raise RuntimeError("로그인 폼에서 l_token을 찾지 못했습니다.")

    aes_key = base64.b64decode(key_match.group(1))
    if len(aes_key) not in (16, 24, 32):
        raise RuntimeError(f"예상치 못한 AES 키 길이: {len(aes_key)}바이트")

    return LoginPage(
        aes_key=aes_key,
        salt=salt_match.group(1),
        l_token=token_input["value"].strip(),
        url=url,
    )


async def fetch_login_page(
    client: httpx.AsyncClient, service_id: str, relay_state: str
) -> LoginPage:
    """SSO 로그인 폼을 받아 암호화 파라미터를 파싱한다.

    응답의 세션 쿠키는 client에 자동 저장되며 이후 로그인 요청에 필요하다.
    """
    resp = await client.get(
        AUTH_URL,
        params={"id": service_id, "ac": "Y", "ifa": "N", "RelayState": relay_state},
        headers={"user-agent": _UA, "accept": "text/html"},
    )
    resp.raise_for_status()

    if "Universal Login" not in resp.text and "ipt_password" not in resp.text:
        raise RuntimeError(
            f"SSO 로그인 폼이 아닙니다 (status={resp.status_code}, {len(resp.text)}바이트)"
        )

    return parse_login_page(resp.text, str(resp.url))


async def verify_credentials(
    client: httpx.AsyncClient, page: LoginPage, user_id: str, password: str
) -> tuple[bool, str]:
    """UserIdChk.eps로 자격증명을 검증한다. (성공여부, 메시지) 반환.

    세션을 만들지 않고 ID/비밀번호만 확인하므로, 본 로그인 전에 값이 맞는지
    한 번 확인해 불필요한 재시도로 계정이 잠기는 것을 피할 수 있다.
    """
    resp = await client.post(
        USER_ID_CHK_URL,
        data={
            "userId": user_id,
            "password": encrypt_password(password, page),
        },
        headers={
            "user-agent": _UA,
            "referer": page.url,
            "origin": SSO_BASE,
            "x-requested-with": "XMLHttpRequest",
            "accept": "application/json",
        },
    )
    resp.raise_for_status()

    try:
        data = resp.json()
    except ValueError as e:
        raise RuntimeError(f"UserIdChk 응답이 JSON이 아닙니다: {e}") from e

    err_code = data.get("errCd")
    if err_code == 0 or err_code == "0":
        return True, ""
    return False, data.get("errMsg") or f"인증 실패 (errCd={err_code})"


async def submit_login(
    client: httpx.AsyncClient,
    page: LoginPage,
    user_id: str,
    password: str,
    session_check: str = "newSession",
) -> httpx.Response:
    """Login.eps에 로그인 폼을 제출한다.

    Args:
        session_check: 'newSession'이 기본. 중복 로그인 확인 시 'oldSession'으로
            재시도하면 기존 세션을 밀어내고 로그인한다.
    """
    resp = await client.post(
        LOGIN_URL,
        data={
            "sessionChk": session_check,
            "l_token": page.l_token,
            "user_timezone_offset": "-540",
            "user_password": encrypt_password(password, page),
            "user_id": user_id,
            "nextChangeSuccess": "N",
        },
        headers={
            "user-agent": _UA,
            "referer": page.url,
            "origin": SSO_BASE,
            "content-type": "application/x-www-form-urlencoded",
        },
    )
    resp.raise_for_status()
    return resp


def _find_auto_submit_form(html: str):
    """스크립트가 자동 제출하는 리다이렉트 폼을 찾는다. 없으면 None.

    도착 페이지에도 로그아웃·검색 같은 폼이 있으므로, 아무 폼이나 제출하면
    로그인 직후 로그아웃되는 식으로 흐름이 망가진다. 자동 제출 폼은
    (1) 페이지에 `.submit()` 호출이 있고 (2) hidden 입력만 갖는다는 점으로 구분한다.
    """
    if not _SUBMIT_CALL_PATTERN.search(html):
        return None

    for form in BeautifulSoup(html, "lxml").find_all("form"):
        if not form.get("action"):
            continue
        inputs = form.find_all("input")
        if not inputs:
            continue
        if any((i.get("type") or "text").lower() != "hidden" for i in inputs):
            continue  # 사용자 입력이 필요한 폼(로그인 등)
        if not any(i.get("name") for i in inputs):
            continue
        return form

    return None


async def follow_auto_forms(
    client: httpx.AsyncClient, resp: httpx.Response, max_hops: int = 6
) -> httpx.Response:
    """`window.onload`로 자동 제출되는 리다이렉트 폼 체인을 따라간다.

    SSO 구간은 302가 아니라 hidden 필드를 담은 자동 제출 폼으로 이어지므로
    httpx의 follow_redirects만으로는 흐름이 끊긴다. 자격증명 입력이 필요한
    로그인 폼에 도달하면 멈춘다.

    포털의 세션 확립 폼도 이름이 `loginFrm`이라 이름으로는 구분할 수 없다.
    비밀번호 필드(`user_password`)를 가진 폼만 로그인 폼으로 판정한다.
    """
    for _ in range(max_hops):
        form = _find_auto_submit_form(resp.text)

        if form is not None:
            fields = {
                i["name"]: (i.get("value") or "")
                for i in form.find_all("input")
                if i.get("name")
            }
            action = urljoin(str(resp.url), form["action"])
            resp = await client.post(action, data=fields, headers={"user-agent": _UA})
            continue

        # 폼이 없으면 JS location 이동으로 이어지는 구간일 수 있다.
        js_move = _JS_LOCATION_PATTERN.search(resp.text)
        if not js_move:
            break

        raw = js_move.group(1).strip()
        # 빈 값이나 javascript:/about: 같은 비-내비게이션 값은 따라가지 않는다.
        if not raw or raw.lower().startswith(("javascript:", "about:", "#")):
            break

        target = urljoin(str(resp.url), raw)
        if target == str(resp.url) or not target.startswith(("http://", "https://")):
            break
        resp = await client.get(target, headers={"user-agent": _UA})

    return resp


async def login_to_service(
    client: httpx.AsyncClient, idp_url: str, user_id: str, password: str
) -> httpx.Response:
    """서비스의 IdP 진입점에서 시작해 SSO 로그인을 완주한다.

    서비스(LMS/포털)마다 IdP 진입 URL과 RelayState가 다르므로, 진입 URL을
    받아 로그인 폼까지 따라간 뒤 로그인하고 콜백까지 마친 응답을 반환한다.
    세션 쿠키는 client에 누적된다.
    """
    resp = await client.get(idp_url, headers={"user-agent": _UA, "accept": "text/html"})
    resp.raise_for_status()

    resp = await follow_auto_forms(client, resp)
    page = parse_login_page(resp.text, str(resp.url))

    resp = await submit_login(client, page, user_id, password)
    if "ssosession" not in client.cookies:
        raise RuntimeError(
            "SSO 로그인에 실패했습니다. KU_PORTAL_ID / KU_PORTAL_PW를 확인하세요. "
            "(셸 설정에서 큰따옴표 안에 백슬래시를 쓰면 값에 그대로 포함됩니다)"
        )

    return await follow_auto_forms(client, resp)


async def check_second_factor(
    client: httpx.AsyncClient, page: LoginPage, user_id: str, command: str = ""
) -> dict:
    """2차 보안인증 등록 상태를 조회한다.

    2026-07-20부터 학사·행정·LMS에 적용된 IOP 2차 인증의 대상 여부와
    사용 가능한 인증 수단을 확인한다.
    """
    resp = await client.post(
        IOP_USER_STATUS_URL,
        data={"user_id": user_id, "command": command},
        headers={
            "user-agent": _UA,
            "referer": page.url,
            "origin": SSO_BASE,
            "x-requested-with": "XMLHttpRequest",
            "accept": "application/json",
        },
    )
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError as e:
        raise RuntimeError(f"IOPUserStatusChk 응답이 JSON이 아닙니다: {e}") from e
