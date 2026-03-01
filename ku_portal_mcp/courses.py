"""Course search and syllabus retrieval from KUPID/infodepot.

Accesses infodepot.korea.ac.kr via SSO token handoff.
Requires valid KUPID session.
"""

import re
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .auth import Session, PORTAL_BASE, _BROWSER_HEADERS

logger = logging.getLogger(__name__)

INFODEPOT_BASE = "https://infodepot.korea.ac.kr"

# College code -> name mapping (Seoul campus)
COLLEGE_CODES = {
    "0140": "경영대학",
    "0143": "문과대학",
    "4652": "생명과학대학",
    "0197": "정경대학",
    "0209": "이과대학",
    "0217": "공과대학",
    "0226": "의과대학",
    "0234": "사범대학",
    "0231": "간호대학",
    "5720": "정보대학",
    "5338": "디자인조형학부",
    "7325": "미디어대학",
    "4669": "보건과학대학",
    "6726": "스마트보안학부",
}

TERM_CODES = {
    "1": "1R",
    "summer": "1S",
    "2": "2R",
    "winter": "2W",
}


@dataclass
class CourseInfo:
    campus: str
    course_code: str
    section: str
    course_type: str
    course_name: str
    professor: str
    credits: str
    schedule: str


async def _establish_infodepot_session(client: httpx.AsyncClient, session: Session) -> None:
    """Establish session on infodepot via SSO token handoff."""
    await client.get(
        f"{INFODEPOT_BASE}/session.jsp",
        params={"token": session.ssotoken, "orgtoken": session.ssotoken},
        headers={**_BROWSER_HEADERS, "referer": f"{PORTAL_BASE}/front/Component.kpd"},
        follow_redirects=True,
    )


async def fetch_departments(session: Session, college_code: str, year: str, term: str) -> list[dict]:
    """Fetch department list for a college.

    Returns list of {"code": "5722", "name": "컴퓨터학과"} dicts.
    """
    term_code = TERM_CODES.get(term, term)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        resp = await client.get(
            f"{INFODEPOT_BASE}/lecture/LecDeptPopup.jsp",
            params={
                "frm": "frm_ms",
                "colcd": college_code,
                "deptcd": "",
                "dept": "dept",
                "year": year,
                "term": term_code,
                "languageDiv": "ko",
            },
            headers={**_BROWSER_HEADERS, "referer": f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp"},
        )
        html = resp.content.decode("euc-kr", errors="replace")

    # Parse JavaScript: el.value ="code"; el.text = "name";
    values = re.findall(r'el\.value\s*=\s*"(\w+)"', html)
    texts = re.findall(r'el\.text\s*=\s*"([^"]+)"', html)

    departments = []
    for code, name in zip(values, texts):
        departments.append({"code": code, "name": name.strip()})
    return departments


async def search_courses(
    session: Session,
    year: str = "2026",
    semester: str = "1",
    campus: str = "1",
    college: str = "",
    department: str = "",
) -> list[CourseInfo]:
    """Search courses by college/department.

    Args:
        session: Valid KUPID session.
        year: Academic year (e.g., "2026").
        semester: "1", "2", "summer", "winter".
        campus: "1" (Seoul) or "2" (Sejong).
        college: College code (e.g., "5720" for 정보대학).
        department: Department code (e.g., "5722" for 컴퓨터학과).

    Returns:
        List of CourseInfo objects.
    """
    term_code = TERM_CODES.get(semester, semester)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        resp = await client.get(
            f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp",
            params={
                "yy": year,
                "tm": term_code,
                "sCampus": campus,
                "col": college,
                "dept": department,
                "listSub": "Y",
                "es": "",
            },
            headers={**_BROWSER_HEADERS, "referer": f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp"},
        )
        html = resp.content.decode("euc-kr", errors="replace")

    return _parse_course_table(html)


def _parse_course_table(html: str) -> list[CourseInfo]:
    """Parse course search results HTML table."""
    soup = BeautifulSoup(html, "lxml")
    courses = []

    # Find the results table (the one with >2 rows)
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue

        # Skip header row
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 8:
                continue

            courses.append(CourseInfo(
                campus=cells[0],
                course_code=cells[1],
                section=cells[2],
                course_type=cells[3],
                course_name=cells[4],
                professor=cells[5],
                credits=cells[6],
                schedule=cells[7],
            ))

    return courses


async def fetch_syllabus(
    session: Session,
    course_code: str,
    section: str = "00",
    year: str = "2026",
    semester: str = "1",
    grad_code: str = "",
) -> str:
    """Fetch syllabus (강의계획서) for a course.

    Args:
        session: Valid KUPID session.
        course_code: Course code (e.g., "COSE101").
        section: Section/class number (e.g., "02").
        year: Academic year.
        semester: "1", "2", "summer", "winter".
        grad_code: Graduate code (usually empty for undergrad).

    Returns:
        Syllabus text content.
    """
    term_code = TERM_CODES.get(semester, semester)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        resp = await client.get(
            f"{INFODEPOT_BASE}/common/AllgenNoX.jsp",
            params={
                "flag": "LecPlan",
                "courcd": course_code,
                "courcls": section,
                "year": year,
                "term": term_code,
                "gradcd": grad_code,
            },
            headers={**_BROWSER_HEADERS, "referer": f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp"},
        )
        html = resp.content.decode("euc-kr", errors="replace")

    return _parse_syllabus_html(html)


def _parse_syllabus_html(html: str) -> str:
    """Parse syllabus page HTML into readable text.

    The syllabus page uses Allgen/HanaReport (internal report server).
    If the report server URL is found, extract parameters and return info.
    """
    # Check if response contains the Allgen report server redirect
    report_match = re.search(
        r"PrintObj\('(.+?)','(http[^']+)'\)", html,
    )
    if report_match:
        params_str = report_match.group(1)
        # Parse [:key]=value pairs
        pairs = re.findall(r'\[:(\w+)\]=([^\[]*)', params_str)
        info_parts = []
        for key, val in pairs:
            if val:
                label = {
                    "p_year": "학년도",
                    "p_term": "학기",
                    "p_cour_cd": "학수번호",
                    "p_cour_cls": "분반",
                    "p_grad_cd": "대학원코드",
                }.get(key, key)
                info_parts.append(f"{label}: {val}")

        return (
            "강의계획서는 교내 리포트 서버(Allgen)에서 제공됩니다.\n"
            "KUPID 포털에서 직접 열람해주세요.\n\n"
            + "\n".join(info_parts)
        )

    soup = BeautifulSoup(html, "lxml")

    # Remove scripts and styles
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
