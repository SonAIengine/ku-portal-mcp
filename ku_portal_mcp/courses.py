"""Course search and syllabus retrieval from KUPID/infodepot.

Accesses infodepot.korea.ac.kr via SSO token handoff.
Requires valid KUPID session.
"""

import re
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .academic import resolve_year_semester
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


@dataclass
class EnrolledCourse:
    course_code: str  # e.g. AAI110
    section: str  # e.g. 00
    course_type: str  # e.g. 전공선택
    course_name: str  # e.g. 딥러닝
    professor: str  # e.g. 석흥일
    credits: str  # e.g. 2(2)
    schedule: str  # e.g. 월(7-8) 애기능생활관 301호
    retake: bool  # 재수강여부
    status: str  # e.g. 신청
    grad_code: str  # e.g. 7298 (for syllabus link)
    dept_code: str  # e.g. 7313 (for syllabus link)


async def _establish_infodepot_session(
    client: httpx.AsyncClient, session: Session
) -> None:
    """Establish session on infodepot via SSO token handoff."""
    await client.get(
        f"{INFODEPOT_BASE}/session.jsp",
        params={"token": session.ssotoken, "orgtoken": session.ssotoken},
        headers={**_BROWSER_HEADERS, "referer": f"{PORTAL_BASE}/front/Component.kpd"},
        follow_redirects=True,
    )


async def fetch_departments(
    session: Session, college_code: str, year: str | None = None, term: str | None = None
) -> list[dict]:
    """Fetch department list for a college.

    Returns list of {"code": "5722", "name": "컴퓨터학과"} dicts.
    """
    year, term = resolve_year_semester(year, term)
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
            headers={
                **_BROWSER_HEADERS,
                "referer": f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp",
            },
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
    year: str | None = None,
    semester: str | None = None,
    campus: str = "1",
    college: str = "",
    department: str = "",
) -> list[CourseInfo]:
    """Search courses by college/department.

    Args:
        session: Valid KUPID session.
        year: Academic year (e.g., "2027").
        semester: "1", "2", "summer", "winter".
        campus: "1" (Seoul) or "2" (Sejong).
        college: College code (e.g., "5720" for 정보대학).
        department: Department code (e.g., "5722" for 컴퓨터학과).

    Returns:
        List of CourseInfo objects.
    """
    year, semester = resolve_year_semester(year, semester)
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
            headers={
                **_BROWSER_HEADERS,
                "referer": f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp",
            },
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

            courses.append(
                CourseInfo(
                    campus=cells[0],
                    course_code=cells[1],
                    section=cells[2],
                    course_type=cells[3],
                    course_name=cells[4],
                    professor=cells[5],
                    credits=cells[6],
                    schedule=cells[7],
                )
            )

    return courses


async def fetch_syllabus(
    session: Session,
    course_code: str,
    section: str = "00",
    year: str | None = None,
    semester: str | None = None,
    grad_code: str = "",
) -> str:
    """Fetch syllabus (강의계획서) for a course.

    Strategy:
    1. Try AllgenNoX.jsp -> extract Allgen report URL
    2. If Allgen redirect found, try direct report server access
    3. Fallback: search course listing pages for course info

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
    year, semester = resolve_year_semester(year, semester)
    term_code = TERM_CODES.get(semester, semester)

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        # Step 1: Try AllgenNoX.jsp
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
            headers={
                **_BROWSER_HEADERS,
                "referer": f"{INFODEPOT_BASE}/lecture/LecMajorSub.jsp",
            },
        )
        html = resp.content.decode("euc-kr", errors="replace")

        # Step 2: If Allgen redirect, try direct report server access
        report_match = re.search(r"PrintObj\('(.+?)','(http[^']+)'\)", html)
        if report_match:
            report_content = await _try_allgen_report(client, report_match)
            if report_content:
                return report_content

            # Step 3: Fallback to course listing search
            course_info = await _search_course_info(
                client,
                course_code,
                section,
                year,
                term_code,
            )
            if course_info:
                return course_info

            # Final fallback: return extracted params
            return _format_allgen_params(report_match.group(1))

    return _parse_syllabus_html(html)


async def _try_allgen_report(
    client: httpx.AsyncClient,
    report_match: re.Match,
) -> str | None:
    """Try to directly fetch from Allgen report server (campus network only)."""
    params_str = report_match.group(1)
    report_url = report_match.group(2)

    pairs = re.findall(r"\[:(\w+)\]=([^\[]*)", params_str)
    form_data = {key: val for key, val in pairs}

    try:
        resp = await client.post(
            report_url,
            data=form_data,
            headers={
                **_BROWSER_HEADERS,
                "content-type": "application/x-www-form-urlencoded",
            },
            timeout=10.0,
        )
        if resp.status_code == 200 and len(resp.content) > 200:
            content_type = resp.headers.get("content-type", "")
            if "euc-kr" in content_type.lower():
                text = resp.content.decode("euc-kr", errors="replace")
            else:
                try:
                    text = resp.content.decode("utf-8")
                except UnicodeDecodeError:
                    text = resp.content.decode("euc-kr", errors="replace")
            return _parse_report_html(text)
    except (httpx.HTTPError, httpx.ConnectError, OSError) as e:
        logger.debug(f"Allgen report server not accessible: {e}")

    return None


# Course code prefix -> (college_code, department_code, is_grad)
_PREFIX_TO_DEPT: dict[str, tuple[str, str, bool]] = {
    # 경영대학
    "BUSS": ("0140", "0142", False),
    "HMB": ("0140", "0142", False),
    # 문과대학
    "COLA": ("0143", "4067", False),
    "KORE": ("0143", "0145", False),
    "ENGL": ("0143", "0146", False),
    "PHIL": ("0143", "0147", False),
    "HOKA": ("0143", "0148", False),
    "HOEW": ("0143", "0803", False),
    "SOCI": ("0143", "0152", False),
    "GERM": ("0143", "0153", False),
    "FRAN": ("0143", "0154", False),
    "CHIN": ("0143", "0155", False),
    "RUSS": ("0143", "0156", False),
    "JAPN": ("0143", "0157", False),
    "SPAN": ("0143", "0158", False),
    "HANM": ("0143", "0159", False),
    "LING": ("0143", "4391", False),
    "LALW": ("0143", "5539", False),
    "MHUM": ("0143", "6342", False),
    "EMLA": ("0143", "5672", False),
    "LBNC": ("0143", "6093", False),
    "HMCI": ("0143", "6094", False),
    "GLEA": ("0143", "6095", False),
    "UNIP": ("0143", "6463", False),
    "HUSS": ("0143", "7284", False),
    # 생명과학대학
    "LIBS": ("4652", "4653", False),
    "LIBT": ("4652", "4654", False),
    "LIET": ("4652", "4656", False),
    "LESE": ("4652", "4657", False),
    "LESF": ("4652", "4425", False),
    "LIST": ("4652", "4719", False),
    "CCST": ("4652", "5186", False),
    "LIFS": ("4652", "5564", False),
    # 정경대학
    "POLI": ("0197", "0199", False),
    "ECON": ("0197", "0200", False),
    "STAT": ("0197", "0201", False),
    "PAPP": ("0197", "0203", False),
    "FNEG": ("0197", "5046", False),
    # 이과대학
    "MATH": ("0209", "0211", False),
    "PHYS": ("0209", "0212", False),
    "CHEM": ("0209", "0213", False),
    "EAES": ("0209", "0215", False),
    # 공과대학
    "EGRN": ("0217", "4065", False),
    "KECE": ("0217", "5597", False),
    "CHBE": ("0217", "4084", False),
    "SEMI": ("0217", "6723", False),
    "KMSE": ("0217", "4630", False),
    "IMEN": ("0217", "5320", False),
    "MECH": ("0217", "4952", False),
    "ARCH": ("0217", "4887", False),
    "ACEE": ("0217", "5204", False),
    "ENGY": ("0217", "6724", False),
    "COMM": ("0217", "7076", False),
    "NEIK": ("0217", "7055", False),
    "TEEN": ("0217", "6544", False),
    "ECOC": ("0217", "7282", False),
    "KISE": ("0217", "7414", False),
    # 의과대학
    "PMED": ("0226", "0228", False),
    "MEDI": ("0226", "0229", False),
    # 사범대학
    "EDUC": ("0234", "0236", False),
    "PHEK": ("0234", "0237", False),
    "SAEK": ("0234", "0237", False),
    "HEED": ("0234", "0238", False),
    "MATE": ("0234", "0239", False),
    "KLLE": ("0234", "0240", False),
    "ELED": ("0234", "0241", False),
    "GEOG": ("0234", "0242", False),
    "HISE": ("0234", "0243", False),
    "FADM": ("0234", "4638", False),
    "MUKE": ("0234", "5753", False),
    # 간호대학
    "NRSG": ("0231", "0233", False),
    # 정보대학
    "COSE": ("5720", "5722", False),
    "DATA": ("5720", "6725", False),
    "CSAI": ("5720", "7343", False),
    "BNCS": ("5720", "6666", False),
    "ISEC": ("5720", "5944", False),
    "STEP": ("5720", "5965", False),
    # 디자인조형학부
    "ARDE": ("5338", "5339", False),
    # 미디어대학
    "JMCO": ("7325", "7326", False),
    "GMES": ("7325", "7327", False),
    # 보건과학대학
    "BMED": ("4669", "5693", False),
    "BSMS": ("4669", "5694", False),
    "KHES": ("4669", "5695", False),
    "KHPM": ("4669", "5696", False),
    # 스마트보안학부
    "SMRT": ("6726", "6727", False),
    "CYDF": ("6726", "6880", False),
    "DTPR": ("6726", "7283", False),
    # 대학원 — SW·AI융합대학원
    "AAI": ("7298", "7313", True),
}


async def _search_course_info(
    client: httpx.AsyncClient,
    course_code: str,
    section: str,
    year: str,
    term_code: str,
) -> str | None:
    """Search course listing pages to find course details as syllabus fallback.

    Uses course code prefix to directly look up the correct college/department.
    """
    prefix = re.match(r"[A-Z]+", course_code)
    if not prefix:
        return None

    dept_info = _PREFIX_TO_DEPT.get(prefix.group())
    if not dept_info:
        return None

    col_code, dept_code, is_grad = dept_info
    jsp = "LecGradMajorSub.jsp" if is_grad else "LecMajorSub.jsp"

    try:
        resp = await client.get(
            f"{INFODEPOT_BASE}/lecture/{jsp}",
            params={
                "yy": year,
                "tm": term_code,
                "sCampus": "1",
                "col": col_code,
                "dept": dept_code,
                "listSub": "Y",
            },
            headers={**_BROWSER_HEADERS, "referer": f"{INFODEPOT_BASE}/lecture/{jsp}"},
            timeout=15.0,
        )
        html = resp.content.decode("euc-kr", errors="replace")
        if course_code in html:
            return _extract_course_detail(html, course_code, section)
    except httpx.HTTPError:
        pass

    return None


def _extract_course_detail(html: str, course_code: str, section: str) -> str | None:
    """Extract course details from a course listing page for the target course."""
    soup = BeautifulSoup(html, "lxml")

    # Collect all matching rows, pick the best section match
    matches: list[tuple[int, list[str]]] = []  # (code_idx, cells)

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue

        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 8:
                continue

            code_idx = -1
            for i, cell in enumerate(cells[:3]):
                if (
                    course_code == cell
                ):  # Exact match to avoid COSE101 matching COSE1011
                    code_idx = i
                    break

            if code_idx >= 0:
                matches.append((code_idx, cells))

    if not matches:
        return None

    # Find exact section match, or fall back to first match
    best = matches[0]
    for code_idx, cells in matches:
        sect_idx = code_idx + 1
        if sect_idx < len(cells) and cells[sect_idx] == section:
            best = (code_idx, cells)
            break

    code_idx, cells = best
    return _format_course_detail(cells, code_idx)


def _format_course_detail(cells: list[str], code_idx: int) -> str:
    """Format course detail cells into readable text."""
    # Columns: (campus), 학수번호, 분반, 이수구분, 교과목명, 담당교수, 학점(시간), 강의시간, ...
    parts = ["[강의계획서 — 개설과목 정보]"]
    labels = [
        "학수번호",
        "분반",
        "이수구분",
        "교과목명",
        "담당교수",
        "학점(시간)",
        "강의시간",
    ]

    for j, label in enumerate(labels):
        idx = code_idx + j
        if idx < len(cells) and cells[idx]:
            parts.append(f"{label}: {cells[idx]}")

    parts.append("")
    parts.append("※ 상세 강의계획서(주차별 계획, 교재, 평가방법 등)는")
    parts.append("  KUPID 포털 > 수업 > 개설과목에서 학수번호 클릭 시 확인 가능합니다.")

    return "\n".join(parts)


def _format_allgen_params(params_str: str) -> str:
    """Format Allgen parameters as a readable fallback message."""
    pairs = re.findall(r"\[:(\w+)\]=([^\[]*)", params_str)
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
        "강의계획서 리포트 서버(Allgen) 접속 불가 (교내 네트워크 전용).\n"
        "KUPID 포털에서 직접 열람해주세요.\n\n" + "\n".join(info_parts)
    )


def _parse_report_html(html: str) -> str:
    """Parse Allgen report server response into readable syllabus text."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "head"]):
        tag.decompose()

    sections: list[str] = []
    tables = soup.find_all("table")
    if tables:
        for table in tables:
            for row in table.find_all("tr"):
                cells = [
                    td.get_text(strip=True)
                    for td in row.find_all(["td", "th"])
                    if td.get_text(strip=True)
                ]
                if cells:
                    if len(cells) == 2:
                        sections.append(f"{cells[0]}: {cells[1]}")
                    else:
                        sections.append(" | ".join(cells))

    if sections:
        result = "\n".join(sections)
    else:
        result = soup.get_text(separator="\n", strip=True)

    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip() if result.strip() else ""


async def fetch_my_courses(
    session: Session,
    year: str | None = None,
    semester: str | None = None,
) -> tuple[list[EnrolledCourse], str]:
    """Fetch enrolled courses from infodepot CourseListSearch.

    Args:
        session: Valid KUPID session.
        year: Academic year (e.g., "2027").
        semester: "1", "2", "summer", "winter".

    Returns:
        Tuple of (list of EnrolledCourse, total_credits string).
    """
    year, semester = resolve_year_semester(year, semester)
    term_code = TERM_CODES.get(semester, semester)
    yt = f"{year}{term_code}"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        await _establish_infodepot_session(client, session)

        # Initial GET to establish page
        await client.get(
            f"{INFODEPOT_BASE}/course/CourseListSearch.jsp",
            params={"compId": "82", "menuCd": "247", "language": "ko"},
            headers={**_BROWSER_HEADERS, "referer": f"{INFODEPOT_BASE}/"},
        )

        # POST to set year/term
        resp = await client.post(
            f"{INFODEPOT_BASE}/course/CourseListSearch.jsp",
            data={"yt": yt},
            headers={
                **_BROWSER_HEADERS,
                "referer": f"{INFODEPOT_BASE}/course/CourseListSearch.jsp",
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        html = resp.content.decode("euc-kr", errors="replace")

    return _parse_enrolled_courses(html)


def _parse_enrolled_courses(html: str) -> tuple[list[EnrolledCourse], str]:
    """Parse enrolled courses HTML table and total credits."""
    soup = BeautifulSoup(html, "lxml")
    courses: list[EnrolledCourse] = []

    # Extract total credits: "신청하신 총 학점수는 X.X학점 입니다."
    total_credits = "0"
    credits_match = re.search(r"신청하신\s*총\s*학점수는\s*(\d+\.?\d*)\s*학점", html)
    if credits_match:
        total_credits = credits_match.group(1)

    # Build a map of (course_code, section) -> (grad_code, dept_code) from f_go() links
    fgo_map: dict[tuple[str, str], tuple[str, str]] = {}
    for a_tag in soup.find_all("a", href=re.compile(r"javascript:f_go")):
        onclick = a_tag.get("href", "")
        # f_go('YYYY','1R','7298','7313','AAI110','00','딥러닝')
        m = re.search(
            r"f_go\(\s*'[^']*'\s*,\s*'[^']*'\s*,\s*'(\w+)'\s*,\s*'(\w+)'\s*,\s*'(\w+)'\s*,\s*'(\w+)'",
            onclick,
        )
        if m:
            fgo_map[(m.group(3), m.group(4))] = (m.group(1), m.group(2))

    # Find the main data table (11-column course table)
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 10:
                continue

            cell_texts = [td.get_text(strip=True) for td in cells]

            # Column 0: No (순번) — should be a digit
            if not cell_texts[0].isdigit():
                continue

            course_code = cell_texts[1]
            section = cell_texts[2] if len(cell_texts) > 2 else ""
            grad_code, dept_code = fgo_map.get((course_code, section), ("", ""))

            retake_text = cell_texts[8] if len(cells) > 8 else ""
            retake = retake_text in ("Y", "재수강")

            courses.append(
                EnrolledCourse(
                    course_code=course_code,
                    section=section,
                    course_type=cell_texts[3],
                    course_name=cell_texts[4],
                    professor=cell_texts[5],
                    credits=cell_texts[6],
                    schedule=cell_texts[7],
                    retake=retake,
                    status=cell_texts[9] if len(cells) > 9 else "",
                    grad_code=grad_code,
                    dept_code=dept_code,
                )
            )

    return courses, total_credits


def _parse_syllabus_html(html: str) -> str:
    """Parse syllabus page HTML into readable text (non-Allgen responses)."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
