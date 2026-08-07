"""Next-gen KUPID portal public JSON API + academic calendar.

2026년 차세대 포털 전환으로 레거시 GRW(grw.korea.ac.kr) HTML 스크래핑이
불가능해져, 포털이 로그인 페이지에서 사용하는 게시판 JSON API로 대체한다.

- 게시판 목록: portal.korea.ac.kr/ctt/svc/bulletin — 인증 불필요
- 학사일정: registrar.korea.ac.kr/eduinfo/affairs/schedule.do — 인증 불필요

제약: 목록 2페이지 이후는 서버가 암호화한 encQS URL로만 접근 가능하고
로그인 세션에 바인딩되어 있다. 무인증으로는 ls 파라미터로 최신 N건을
한 번에 받는 방식만 가능하다 (MAX_LIST_SIZE 참고).
"""

import html as html_mod
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PORTAL_BASE = "https://portal.korea.ac.kr"
REGISTRAR_BASE = "https://registrar.korea.ac.kr"

BULLETIN_API = f"{PORTAL_BASE}/ctt/svc/bulletin"
SCHEDULE_URL = f"{REGISTRAR_BASE}/eduinfo/affairs/schedule.do"

# 게시판 ID (b 파라미터). 포털 로그인 페이지의 게시판 목록에서 확인.
BOARD_OBITUARY = 1  # 부고
BOARD_EVENT = 3  # 행사/학술
BOARD_PRAISE = 4  # 칭찬합니다
BOARD_NOTICE = 6  # 공지사항
BOARD_FREE = 7  # 자유게시판
BOARD_SCHOLARSHIP = 10  # 장학
BOARD_ACADEMIC = 11  # 학사 안내
BOARD_INTL = 12  # 국제 협력
BOARD_SEJONG = 13  # 세종캠퍼스
BOARD_FAQ = 19  # 2차 보안인증 FAQ

BOARD_NAMES = {
    BOARD_OBITUARY: "부고",
    BOARD_EVENT: "행사",
    BOARD_PRAISE: "칭찬합니다",
    BOARD_NOTICE: "공지사항",
    BOARD_FREE: "자유게시판",
    BOARD_SCHOLARSHIP: "장학",
    BOARD_ACADEMIC: "학사안내",
    BOARD_INTL: "국제협력",
    BOARD_SEJONG: "세종캠퍼스",
    BOARD_FAQ: "FAQ",
}

# e0(etc0) 필터 = 캠퍼스 구분. 4 = 서울, 미지정 시 전체.
CAMPUS_SEOUL = "4"

# 서버가 ls=500까지 정상 반환하는 것을 확인. 그 이상은 요청하지 않는다.
MAX_LIST_SIZE = 500

_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "accept": "application/json, text/plain, */*",
    "referer": f"{PORTAL_BASE}/index.jsp",
    "x-requested-with": "XMLHttpRequest",
}


@dataclass
class BoardPost:
    """게시판 목록의 게시글 한 건."""

    post_seq: int
    board_id: int
    title: str
    date: str
    writer: str
    department: str
    views: int
    is_notice: bool
    attachments: int
    comments: int
    summary: str
    url: str


@dataclass
class ScheduleEntry:
    """학사일정 항목 한 건."""

    month: str
    date: str
    event: str


@dataclass
class PostDetail:
    """게시글 본문. 포털 로그인이 있어야 조회할 수 있다."""

    title: str
    date: str
    writer: str
    department: str
    approver: str
    views: int
    content: str
    content_html: str
    attachments: list[dict]
    url: str


def _clean_text(value: str | None) -> str:
    """HTML 태그와 엔티티를 제거하고 공백을 정규화한다."""
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", "", value)
    text = html_mod.unescape(text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _format_date(cre_dt: str | None) -> str:
    """'20260719112540' -> '2026.07.19'"""
    if not cre_dt or len(cre_dt) < 8:
        return ""
    return f"{cre_dt[:4]}.{cre_dt[4:6]}.{cre_dt[6:8]}"


def _to_post(raw: dict, board_id: int) -> BoardPost:
    title = _clean_text(raw.get("textTitle")) or _clean_text(raw.get("title"))
    enc_url = raw.get("encPopupUrl") or raw.get("encUrl") or ""
    if enc_url.startswith("/"):
        enc_url = f"{PORTAL_BASE}{enc_url}"

    return BoardPost(
        post_seq=raw.get("postSeq", 0),
        board_id=raw.get("boardId", board_id),
        title=title,
        date=_format_date(raw.get("creDt")),
        writer=_clean_text(raw.get("creUserName")),
        department=_clean_text(raw.get("creUserDeptName")),
        views=raw.get("visitCnt") or 0,
        is_notice=raw.get("noticeYn") == "Y",
        attachments=raw.get("fileCnt") or 0,
        comments=raw.get("cmmtCnt") or 0,
        summary=_clean_text(raw.get("summary")),
        url=enc_url,
    )


async def fetch_board(
    board_id: int, limit: int = 20, campus: str | None = CAMPUS_SEOUL
) -> tuple[list[BoardPost], int]:
    """게시판 목록을 조회한다. (게시글 리스트, 전체 건수)를 반환.

    Args:
        board_id: 게시판 ID (BOARD_* 상수)
        limit: 가져올 최대 건수 (MAX_LIST_SIZE로 상한)
        campus: 캠퍼스 필터. None이면 전체.
    """
    limit = max(1, min(limit, MAX_LIST_SIZE))
    params: dict[str, str | int] = {"b": board_id, "ls": limit}
    if campus:
        params["e0"] = campus

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(BULLETIN_API, params=params, headers=_HEADERS)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(f"게시판 API가 JSON을 반환하지 않았습니다: {e}") from e

    if "postListForm" not in data:
        raise RuntimeError(f"예상치 못한 응답 형식: {list(data)[:5]}")

    posts = [_to_post(raw, board_id) for raw in data.get("postListForm") or []]
    return posts, data.get("totCnt", len(posts))


async def fetch_board_page(
    board_id: int, page: int = 1, count: int = 20, campus: str | None = CAMPUS_SEOUL
) -> tuple[list[BoardPost], int]:
    """page/count 기반 조회. 서버 페이징 대신 넉넉히 받아 슬라이싱한다.

    무인증으로는 encQS 페이징을 쓸 수 없어, page*count 만큼 받아 잘라낸다.
    page*count가 MAX_LIST_SIZE를 넘으면 빈 목록을 반환한다.
    """
    page = max(page, 1)
    count = max(count, 1)
    needed = page * count

    if needed > MAX_LIST_SIZE:
        logger.warning(
            f"요청 범위({needed}건)가 무인증 조회 상한({MAX_LIST_SIZE}건)을 초과"
        )
        return [], 0

    posts, total = await fetch_board(board_id, limit=needed, campus=campus)
    return posts[(page - 1) * count : page * count], total


async def search_boards(
    keyword: str,
    board_ids: list[int],
    limit: int = 100,
    campus: str | None = CAMPUS_SEOUL,
) -> list[tuple[int, BoardPost]]:
    """여러 게시판에서 제목·요약에 키워드가 포함된 글을 찾는다.

    서버에 검색 API가 없어 목록을 받아 클라이언트에서 필터링한다.
    """
    kw = keyword.lower()
    results: list[tuple[int, BoardPost]] = []

    for board_id in board_ids:
        try:
            posts, _ = await fetch_board(board_id, limit=limit, campus=campus)
        except Exception as e:
            logger.warning(f"게시판 {board_id} 검색 실패: {e}")
            continue
        for post in posts:
            if kw in post.title.lower() or kw in post.summary.lower():
                results.append((board_id, post))

    return results


def _split_writer(value: str) -> tuple[str, str]:
    """'권혜정 (차세대정보화추진팀)' -> ('권혜정', '차세대정보화추진팀')"""
    match = re.match(r"^(.*?)\s*\((.*)\)\s*$", value)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return value, ""


# 본문에서 줄바꿈으로 취급할 블록 요소
_BLOCK_TAGS = ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "blockquote")


def _extract_body_text(node) -> str:
    """본문을 읽기 좋은 텍스트로 변환한다.

    포털 본문은 서식 때문에 `<span>2</span>차` 처럼 인라인 요소로 잘게 쪼개져
    있어, 구분자를 넣어 get_text하면 단어 중간에 줄바꿈이 생긴다.
    블록 요소와 <br>에서만 줄을 나눈다.
    """
    for br in node.find_all("br"):
        br.replace_with("\n")
    for block in node.find_all(_BLOCK_TAGS):
        block.append("\n")

    text = node.get_text("", strip=False)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_post_detail(html: str, url: str) -> PostDetail:
    """게시글 상세 페이지를 파싱한다."""
    soup = BeautifulSoup(html, "lxml")

    area = soup.select_one(".sub_search_area.view")
    if not area:
        raise RuntimeError(
            "게시글 본문 영역을 찾지 못했습니다. 로그인이 만료되었거나 "
            "포털 화면 구조가 변경되었을 수 있습니다."
        )

    title_tag = area.select_one(".tit h3") or area.select_one(".tit")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""

    # 작성자/작성일/승인자/조회수는 dt(레이블) + dd(값) 쌍으로 들어 있다.
    meta: dict[str, str] = {}
    for dl in area.select("dl"):
        label = dl.find("dt")
        value = dl.find("dd")
        if label and value:
            meta[label.get_text(strip=True)] = value.get_text(" ", strip=True)

    # 전체 레이아웃 페이지는 '작성자 (부서)', 팝업 페이지는 '부서'만 제공한다.
    writer, department = _split_writer(meta.get("작성자", ""))
    if not department:
        department = meta.get("부서", "")
    approver, _ = _split_writer(meta.get("승인자", ""))
    views = int(re.sub(r"\D", "", meta.get("조회수", "")) or 0)

    body = area.select_one(".bc-s-post-ctnt-area") or area.select_one(".text_area")
    content_html = str(body) if body else ""
    content = _extract_body_text(body) if body else ""

    attachments = []
    for link in soup.select("#tx_attach_list a[href], .tx-attach-list a[href]"):
        size_tag = link.find("span")
        # '(28KB KB / 다운로드)' 형태에서 크기만 남긴다.
        size = size_tag.get_text(strip=True).strip("()") if size_tag else ""
        size = re.sub(r"\s*KB\s*KB\b", "KB", size.split("/")[0]).strip()
        if size_tag:
            size_tag.extract()
        href = link["href"]
        attachments.append(
            {
                "name": link.get_text(" ", strip=True),
                "size": size,
                "url": f"{PORTAL_BASE}{href}" if href.startswith("/") else href,
            }
        )

    return PostDetail(
        title=title,
        date=meta.get("작성일", ""),
        writer=writer,
        department=department,
        approver=approver,
        views=views,
        content=content,
        content_html=content_html,
        attachments=attachments,
        url=url,
    )


async def fetch_post_detail(client: httpx.AsyncClient, url: str) -> PostDetail:
    """게시글 본문을 조회한다. 인증된 클라이언트가 필요하다."""
    resp = await client.get(url, headers={"user-agent": _HEADERS["user-agent"]})
    resp.raise_for_status()

    if "ipt_password" in resp.text:
        raise RuntimeError("포털 로그인이 필요합니다 (세션이 만료되었습니다).")

    return parse_post_detail(resp.text, url)


async def fetch_academic_schedule(
    year: int | str, semester: int | str
) -> tuple[list[ScheduleEntry], str]:
    """학사일정을 조회한다. (일정 리스트, 표 제목)을 반환.

    Args:
        year: 학년도 (예: 2026)
        semester: 학기 (1 또는 2)
    """
    params = {"cYear": str(year), "hakGi": str(semester)}

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(
            SCHEDULE_URL,
            params=params,
            headers={"user-agent": _HEADERS["user-agent"]},
        )
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    if not table:
        raise RuntimeError("학사일정 표를 찾을 수 없습니다")

    caption_tag = table.find("caption")
    caption = caption_tag.get_text(strip=True) if caption_tag else ""

    entries: list[ScheduleEntry] = []
    current_month = ""

    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if not cells:
            continue

        # 월은 rowspan을 가진 <th>로 한 번만 나오고, 이후 행은 <td> 2개뿐이다.
        if cells[0].name == "th":
            current_month = cells[0].get_text(" ", strip=True)
            cells = cells[1:]

        if len(cells) < 2:
            continue

        date = cells[0].get_text(" ", strip=True)
        event = cells[1].get_text(" ", strip=True)
        if not date and not event:
            continue

        entries.append(ScheduleEntry(month=current_month, date=date, event=event))

    return entries, caption
