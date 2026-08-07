"""AMS 2차 보안인증 헬퍼 (브라우저 자동화).

AMS의 2차 인증은 서버가 브라우저 컨텍스트를 엄격히 검증해, 순수 HTTP 요청으로는
OTP를 맞게 넣어도 세션이 인증됨으로 승격되지 않는다. 이 단계만 실제 브라우저로
처리하고, 인증이 끝나면 쿠키만 넘겨 이후 조회는 httpx로 수행한다.

MCP tool 호출 사이에 브라우저 세션을 유지해야 하므로 별도 프로세스로 돌면서
파일로 신호를 주고받는다.

    python -m ku_portal_mcp._ams_auth <상태디렉토리>

    상태디렉토리/
        auth_status.json   진행 상태 (헬퍼가 기록)
        auth_code.txt      사용자가 넣은 6자리 코드 (호출자가 기록)
        ams_session.json   인증 완료된 쿠키 (헬퍼가 기록)
"""

import json
import os
import sys
import time
from pathlib import Path

_CHROMIUM_GLOBS = (
    "chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
    "chromium-*/chrome-*/Chromium.app/Contents/MacOS/Chromium",
    "chromium-*/chrome-*/chrome",
)

STATUS_FILE = "auth_status.json"
CODE_FILE = "auth_code.txt"
SESSION_FILE = "ams_session.json"

# 사용자가 메일을 확인해 코드를 넣기까지 기다리는 시간
CODE_WAIT_SECONDS = 300


def find_chromium() -> str | None:
    """Playwright가 설치한 Chromium 실행 파일을 찾는다.

    Playwright 패키지 버전과 설치된 브라우저 빌드가 어긋나면 기본 탐색이
    실패하므로, 캐시 디렉토리에서 직접 찾아 넘긴다.
    """
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not cache.exists():
        cache = Path.home() / ".cache" / "ms-playwright"
    if not cache.exists():
        return None

    for pattern in _CHROMIUM_GLOBS:
        matches = sorted(cache.glob(pattern), reverse=True)
        if matches:
            return str(matches[0])
    return None


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def run(state_dir: Path) -> None:
    from playwright.sync_api import sync_playwright

    status_path = state_dir / STATUS_FILE
    code_path = state_dir / CODE_FILE
    session_path = state_dir / SESSION_FILE

    user_id = os.environ.get("KU_PORTAL_ID")
    password = os.environ.get("KU_PORTAL_PW")
    if not user_id or not password:
        _write(
            status_path, {"state": "error", "message": "자격증명 환경변수가 없습니다."}
        )
        return

    launch_kwargs = {"headless": True}
    executable = find_chromium()
    if executable:
        launch_kwargs["executable_path"] = executable

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception as e:
            _write(
                status_path,
                {
                    "state": "error",
                    "message": (
                        f"브라우저를 실행하지 못했습니다: {e}. "
                        "`playwright install chromium`으로 브라우저를 설치하세요."
                    ),
                },
            )
            return

        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 950},
        )
        page = ctx.new_page()
        dialogs: list[str] = []
        page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))

        try:
            page.goto(
                "https://ams.korea.ac.kr?isPc=true&menuId=M111422",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(3000)
            page.wait_for_selector("#ipt_id", timeout=25000)
            page.fill("#ipt_id", user_id)
            page.fill("#ipt_password", password)
            page.evaluate("() => goLogin()")
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except Exception:
                pass
            page.wait_for_timeout(4000)

            if "sso_option_change" not in page.content():
                _write(
                    status_path,
                    {
                        "state": "error",
                        "message": f"2차 인증 화면에 도달하지 못했습니다 (위치: {page.url}).",
                    },
                )
                return

            # 이메일 OTP 모드로 전환하고 코드를 발송한다
            page.evaluate("() => doAuth('o')")
            page.wait_for_timeout(2500)
            page.evaluate("() => otpReq('scnd')")
            page.wait_for_timeout(4000)

            sent = any("sent" in m.lower() or "발송" in m for m in dialogs)
            if not sent:
                _write(
                    status_path,
                    {"state": "error", "message": f"OTP 발송 실패: {dialogs[-3:]}"},
                )
                return

            _write(status_path, {"state": "code_sent", "dialogs": dialogs[-2:]})

            # 사용자가 코드를 넣을 때까지 대기
            code = None
            deadline = time.time() + CODE_WAIT_SECONDS
            while time.time() < deadline:
                if code_path.exists():
                    candidate = code_path.read_text().strip()
                    if len(candidate) == 6 and candidate.isdigit():
                        code = candidate
                        break
                time.sleep(2)

            if not code:
                _write(
                    status_path,
                    {"state": "error", "message": "인증 코드 입력 시간이 지났습니다."},
                )
                return

            before = len(dialogs)
            page.fill("#cert_no", code)
            page.evaluate("() => otpVerify('scnd')")
            try:
                page.wait_for_load_state("networkidle", timeout=60000)
            except Exception:
                pass
            page.wait_for_timeout(6000)

            if "sso.korea.ac.kr" in page.url:
                _write(
                    status_path,
                    {
                        "state": "error",
                        "message": f"인증에 실패했습니다: {dialogs[before:][-2:] or '사유 불명'}",
                    },
                )
                return

            # AMS 세션이 실제로 섰는지 확인하고 쿠키를 넘긴다
            page.goto(
                "https://ams.korea.ac.kr/com/cnst/PropCtr/findViewSession.do",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            if '"isLogin":"1"' not in page.content():
                _write(
                    status_path,
                    {"state": "error", "message": "AMS 세션이 확립되지 않았습니다."},
                )
                return

            cookies = [
                {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c["domain"],
                    "path": c.get("path", "/"),
                }
                for c in ctx.cookies()
            ]
            _write(session_path, {"cookies": cookies, "created_at": time.time()})
            _write(status_path, {"state": "done"})
        except Exception as e:
            _write(
                status_path, {"state": "error", "message": f"{type(e).__name__}: {e}"}
            )
        finally:
            browser.close()


if __name__ == "__main__":
    run(Path(sys.argv[1]))
