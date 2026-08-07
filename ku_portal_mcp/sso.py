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
