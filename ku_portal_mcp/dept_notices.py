"""Department notice scraper for Korea University department websites.

Parses notice boards from department/graduate school homepages that share
a common CMS structure (e.g., gscit, cs, edu, info subdomains).
No authentication required — these are public boards.
"""

import re
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class DeptNotice:
    """A department notice list item."""
    article_no: str
    title: str
    writer: str
    date: str
    views: str
    is_pinned: bool
    has_attachment: bool


@dataclass
class DeptNoticeDetail:
    """Full department notice detail."""
    article_no: str
    title: str
    content: str
    attachments: list[dict]
    url: str


async def fetch_dept_notice_list(
    base_url: str, offset: int = 0, limit: int = 20
) -> list[DeptNotice]:
    """Fetch notice list from a department board page.

    Args:
        base_url: Full URL of the department notice board
                  (e.g., https://gscit.korea.ac.kr/gscit/board/notice_master.do)
        offset: Pagination offset (article.offset parameter)
        limit: Maximum items to return
    """
    params = {"article.offset": str(offset)}

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(base_url, params=params, headers=_HEADERS)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    items: list[DeptNotice] = []

    rows = soup.select("table tbody tr")
    if not rows:
        rows = soup.select("table tr")

    for row in rows:
        link = row.select_one("a.article-title")
        if not link:
            link = row.select_one("a[href*='articleNo']")
        if not link:
            continue

        href = link.get("href") or ""
        href_str = href if isinstance(href, str) else str(href)
        m = re.search(r"articleNo=(\d+)", href_str)
        if not m:
            continue
        article_no = m.group(1)

        title = link.get_text(strip=True)
        row_classes = row.get("class") or []
        class_list: list[str] = row_classes if isinstance(row_classes, list) else [str(row_classes)]
        is_pinned = "top-notice" in class_list or bool(
            row.select_one(".top-notice-bg")
        ) or "top-notice-bg" in " ".join(class_list)
        has_attachment = bool(row.select_one(".file-icon, .ico-file, img[alt*='파일']"))

        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        # Common column layouts:
        #   [번호, 제목, 작성자, 등록일, 조회수]  (5 cols)
        #   [번호, 제목, 작성자, 조회수, 등록일]  (5 cols, alt order)
        #   [제목, 작성자, 등록일, 조회수]         (4 cols)
        writer = ""
        date = ""
        views = ""

        if len(cells) >= 5:
            writer = cells[2]
            # Detect which of cells[3]/cells[4] is a date vs view count
            if re.match(r"\d{4}[.\-/]", cells[3]):
                date = cells[3]
                views = cells[4]
            else:
                views = cells[3]
                date = cells[4]
        elif len(cells) >= 4:
            writer = cells[1]
            if re.match(r"\d{4}[.\-/]", cells[2]):
                date = cells[2]
                views = cells[3]
            else:
                views = cells[2]
                date = cells[3]

        items.append(DeptNotice(
            article_no=article_no,
            title=title,
            writer=writer,
            date=date,
            views=views,
            is_pinned=is_pinned,
            has_attachment=has_attachment,
        ))

        if len(items) >= limit:
            break

    return items


async def fetch_dept_notice_detail(
    base_url: str, article_no: str
) -> DeptNoticeDetail:
    """Fetch detail page for a specific notice article.

    Args:
        base_url: Board base URL (same as used for list)
        article_no: Article number from the list
    """
    params = {"mode": "view", "articleNo": article_no}

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(base_url, params=params, headers=_HEADERS)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # Title extraction
    title = ""
    # Try: th containing "제목" with adjacent td
    for th in soup.select("th"):
        if th.get_text(strip=True) == "제목":
            td = th.find_next_sibling("td")
            if td:
                title = td.get_text(strip=True)
            break
    if not title:
        # Fallback: .article-title or first h2/h3 in content area
        el = soup.select_one(".article-title, .view-title, h2.title")
        if el:
            title = el.get_text(strip=True)

    # Content extraction
    content = ""
    content_el = soup.select_one(".article-text, .view-content, .board-view-content")
    if content_el:
        content = content_el.get_text(separator="\n", strip=True)
    else:
        # Fallback: th containing "내용" with adjacent td
        for th in soup.select("th"):
            if th.get_text(strip=True) == "내용":
                td = th.find_next_sibling("td")
                if td:
                    content = td.get_text(separator="\n", strip=True)
                break

    # Collapse excessive blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)

    # Attachments
    attachments = []
    from urllib.parse import urlparse
    for a_tag in soup.select("a[href*='mode=download']"):
        raw_href = a_tag.get("href") or ""
        href_s = raw_href if isinstance(raw_href, str) else str(raw_href)
        name = a_tag.get_text(strip=True)
        if not name:
            name = "첨부파일"
        # Build absolute URL
        if href_s.startswith("http"):
            dl_url = href_s
        elif href_s.startswith("/"):
            parsed = urlparse(base_url)
            dl_url = f"{parsed.scheme}://{parsed.netloc}{href_s}"
        else:
            dl_url = href_s
        attachments.append({"name": name, "url": dl_url})

    # Build canonical view URL
    view_url = f"{base_url}?mode=view&articleNo={article_no}"

    return DeptNoticeDetail(
        article_no=article_no,
        title=title,
        content=content,
        attachments=attachments,
        url=view_url,
    )
