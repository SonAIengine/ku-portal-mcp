"""HTML scraping and parsing for KUPID portal pages.

Handles EUC-KR decoding and BeautifulSoup-based extraction.
"""

import re
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .auth import Session, GRW_BASE, PORTAL_BASE

logger = logging.getLogger(__name__)


@dataclass
class NoticeItem:
    """A notice/schedule list item."""
    index: str
    message_id: str
    kind: str
    title: str
    date: str
    writer: str
    reply_top: str = "0"
    reply_pos: str = "0"
    reply_to: str = "0"
    row_reply: str = "0"
    depth: str = "0"


@dataclass
class NoticeDetail:
    """Full notice/schedule detail."""
    id: str
    title: str
    date: str
    writer: str
    content: str
    attachments: list[dict]
    url: str


def _decode_euckr(response: httpx.Response) -> str:
    """Decode EUC-KR encoded response content."""
    return response.content.decode("euc-kr", errors="replace")


def _build_cookie_string(session: Session) -> str:
    return (
        f"ssotoken={session.ssotoken}; "
        f"PORTAL_SESSIONID={session.portal_session_id}; "
        f"GRW_SESSIONID={session.grw_session_id};"
    )


async def fetch_notice_list(
    session: Session, kind: str, page: int = 1, count: int = 20
) -> list[NoticeItem]:
    """Fetch notice/schedule list page and parse items."""
    url = (
        f"{GRW_BASE}/GroupWare/user/NoticeList.jsp"
        f"?kind={kind}&compId=148&menuCd=340&language=ko"
        f"&frame=&token={session.ssotoken}&orgtoken={session.ssotoken}"
    )
    cookie_str = _build_cookie_string(session)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            headers={
                "referer": f"{PORTAL_BASE}/",
                "cookie": cookie_str,
            },
            follow_redirects=True,
        )
        resp.raise_for_status()

    html = _decode_euckr(resp)

    if kind == "89":
        return _parse_schedule_list(html, kind)
    else:
        return _parse_notice_list(html, kind)


def _parse_notice_list(html: str, kind: str) -> list[NoticeItem]:
    """Parse notice list from javascript:view() calls in HTML."""
    items = []
    # Pattern: javascript:view(kind, index, message_id, replyTop, replyPos, replyTo, rowReply, depth)
    hrefs = re.findall(r"javascript:view\((.+?)\);", html)

    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("table tr")

    for i, href in enumerate(hrefs):
        nums = re.findall(r"\d+", href)
        if len(nums) < 8:
            continue

        k, index, message_id, reply_top, reply_pos, reply_to, row_reply, depth = nums[:8]

        # Try to extract title and date from corresponding table row
        title = ""
        date = ""
        writer = ""
        # Best-effort extraction from surrounding HTML
        title_match = re.search(
            rf'javascript:view\({re.escape(href.split(",")[0])},{re.escape(href.split(",")[1])}[^)]*\)[^<]*</a>',
            html,
        )

        item = NoticeItem(
            index=index,
            message_id=message_id,
            kind=k,
            title=title,
            date=date,
            writer=writer,
            reply_top=reply_top,
            reply_pos=reply_pos,
            reply_to=reply_to,
            row_reply=row_reply,
            depth=depth,
        )
        items.append(item)

    # Enrich items with title/date/writer from table rows using BeautifulSoup
    _enrich_items_from_table(soup, items)

    return items


def _parse_schedule_list(html: str, kind: str) -> list[NoticeItem]:
    """Parse schedule list from javascript:view1() calls in HTML.

    Actual pattern: javascript:view1( '89','index','msg_id','replyTop','replyPos','replyTo','rowReply','depth' ,'' )
    """
    items = []
    # Extract quoted parameters from view1() calls
    hrefs = re.findall(r"javascript:view1\((.+?)\)", html)

    soup = BeautifulSoup(html, "lxml")

    for href in hrefs:
        # Extract quoted string values
        params = [p.strip().strip("'\"") for p in href.split(",")]
        params = [p for p in params if p]  # remove empty

        if len(params) < 8:
            # Fallback: extract digits
            nums = re.findall(r"\d+", href)
            if len(nums) >= 8:
                params = nums[:8]
            else:
                continue

        k = params[0]
        index = params[1]
        message_id = params[2]
        reply_top = params[3] if len(params) > 3 else "0"
        reply_pos = params[4] if len(params) > 4 else "0"
        reply_to = params[5] if len(params) > 5 else "0"
        row_reply = params[6] if len(params) > 6 else "0"
        depth = params[7] if len(params) > 7 else "0"

        item = NoticeItem(
            index=index,
            message_id=message_id,
            kind=k,
            title="",
            date="",
            writer="",
            reply_top=reply_top,
            reply_pos=reply_pos,
            reply_to=reply_to,
            row_reply=row_reply,
            depth=depth,
        )
        items.append(item)

    _enrich_items_from_table(soup, items)

    return items


def _enrich_items_from_table(soup: BeautifulSoup, items: list[NoticeItem]) -> None:
    """Extract title, date, writer from table rows and attach to items."""
    rows = soup.select("table.boardlist tr, table.list tr, table tr")

    # Find data rows (skip header)
    data_rows = []
    for row in rows:
        tds = row.find_all("td")
        if len(tds) >= 3:
            # Check if this row contains a view() or view1() link
            a_tag = row.find("a", href=re.compile(r"javascript:view"))
            if a_tag:
                data_rows.append(row)

    for i, (row, item) in enumerate(zip(data_rows, items)):
        tds = row.find_all("td")
        if not tds:
            continue

        # Extract title from the anchor tag
        a_tag = row.find("a", href=re.compile(r"javascript:view"))
        if a_tag:
            item.title = a_tag.get_text(strip=True)

        # Typically: [번호, 제목, 작성자, 날짜, 조회수] or similar
        texts = [td.get_text(strip=True) for td in tds]
        if len(texts) >= 4:
            item.writer = texts[-3] if len(texts) >= 5 else texts[-2]
            item.date = texts[-2] if len(texts) >= 5 else texts[-1]
        elif len(texts) >= 3:
            item.date = texts[-1]


async def fetch_notice_detail(session: Session, item: NoticeItem) -> NoticeDetail:
    """Fetch and parse a single notice/schedule detail page."""
    url = (
        f"{GRW_BASE}/GroupWare/user/NoticeView.jsp"
        f"?language=ko&WhereSelect=all&KeyWord=&tab=&temp="
        f"&JOB_MODE=Q&JOBMODE=I&hdCurrPage=1&hdListCount=100"
        f"&hdPageCount=5&hdPageList=&userid="
        f"&index={item.index}&message_id={item.message_id}"
        f"&replyTop={item.reply_top}&replyPos={item.reply_pos}"
        f"&replyTo={item.reply_to}&rowReply={item.row_reply}"
        f"&depth={item.depth}&kind={item.kind}"
        f"&type=0&mode=0&flag=&access_type=Y&calIndex="
        f"&token={session.ssotoken}"
    )
    cookie_str = _build_cookie_string(session)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            headers={
                "referer": f"{GRW_BASE}/GroupWare/user/NoticeList.jsp?kind={item.kind}",
                "cookie": cookie_str,
            },
            follow_redirects=True,
        )
        resp.raise_for_status()

    html = _decode_euckr(resp)
    # Replace encoding declaration for proper display
    html = html.replace("euc-kr", "utf-8")

    return _parse_detail_html(html, item.kind)


def _parse_detail_html(html: str, kind: str) -> NoticeDetail:
    """Parse detail page HTML into structured data."""
    soup = BeautifulSoup(html, "lxml")

    # Extract ID from hidden input
    id_input = soup.find("input", {"type": "hidden", "name": "index"})
    notice_id = id_input["value"].strip() if id_input else ""

    # Parse table rows for metadata
    table_rows = html.split("<tr>")[1:]  # Skip before first <tr>

    writer = ""
    date = ""
    title = ""
    content_html = ""

    # Extract writer from first row
    if table_rows:
        writer_match = re.search(r"<td>(.+?)</td>", table_rows[0], re.DOTALL)
        if writer_match:
            writer = _strip_html(writer_match.group(1)).strip()

    # Date extraction differs by kind
    if kind == "89" and len(table_rows) > 1:
        # Schedule: date in row[1]
        date_parts = table_rows[1].split("<td>")
        if len(date_parts) > 1:
            raw_date = date_parts[1].split("</td>")[0]
            date = _strip_html(raw_date).strip()
            date = re.sub(r"\s+", "", date)
    elif len(table_rows) > 2:
        # Notice: date in row[2]
        date_match = re.search(r'<td colspan="\d">(.+?)</td>', table_rows[2], re.DOTALL)
        if date_match:
            date = _strip_html(date_match.group(1)).strip()

    # Title in row[4]
    if len(table_rows) > 4:
        title_match = re.search(r'<td colspan="\d">(.+?)</td>', table_rows[4], re.DOTALL)
        if title_match:
            title = _strip_html(title_match.group(1)).strip()

    # Content from row[5] onwards
    if len(table_rows) > 5:
        raw_content = "<tr>".join(table_rows[5:])
        content_html = _clean_content(raw_content)

    # Extract attachments
    attachments = _extract_attachments(html)

    portal_url = (
        f"{PORTAL_BASE}/front/IntroNotice/NMainNoticeContent.kpd"
        f"?idx={notice_id}&seq="
    )

    return NoticeDetail(
        id=notice_id,
        title=title,
        date=date,
        writer=writer,
        content=content_html,
        attachments=attachments,
        url=portal_url,
    )


def _strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"(&nbsp;)+", " ", text)
    return text.strip()


def _clean_content(html: str) -> str:
    """Clean up content HTML for readable display."""
    soup = BeautifulSoup(html, "lxml")

    # Remove button inputs
    for btn in soup.find_all("input", {"type": "button"}):
        btn.decompose()

    # Convert to text, preserving some structure
    text = soup.get_text(separator="\n", strip=True)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_attachments(html: str) -> list[dict]:
    """Extract file download links from the page."""
    attachments = []

    # Pattern: javascript:Download('filePath', 'fileName')
    downloads = re.findall(r"javascript:Download\((.+?)\);", html)
    for dl in downloads:
        params = [p.strip().strip("'\"") for p in dl.split(",")]
        if len(params) >= 2:
            file_path, file_name = params[0], params[1]
            download_url = (
                f"{PORTAL_BASE}/common/Download.kpd"
                f"?filePath={file_path}&fileName={file_name}"
            )
            attachments.append({
                "name": file_name,
                "url": download_url,
            })

    return attachments
